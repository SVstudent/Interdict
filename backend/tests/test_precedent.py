"""Precedent — the fleet learns what this organisation actually decided.

An ESCALATE used to dead-end at a person: they chose, the money moved or did not, and their
reasoning left the building with them. These tests pin the two halves of closing that gap — where
the similarity line is drawn, and the fact that a precedent can only ever make the fleet more
cautious.

The second half matters more than the first. A precedent argues for moving money and it does so
carrying the authority of a named person who never looked at this case, so the interesting
question is not what it can do but what it structurally cannot.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.adjudicator import CONSERVATISM, AdjudicatorAgent
from app.agents.base import AgentContext
from app.agents.precedent import PrecedentClerkAgent
from app.agents.scopes import FLEET_SCOPES, Scope, ScopeViolation
from app.api.precedent import (
    Resolution,
    get_precedent,
    list_precedents,
    precedent_for_case,
    resolve_case,
)
from app.config import DEMO_EPOCH, FrozenClock, Settings
from app.models.domain import (
    Case,
    CaseState,
    EvidenceRef,
    Finding,
    Payment,
    PaymentStatus,
    Precedent,
    Vendor,
)
from app.orchestrator.pipeline import build_pipeline
from app.orchestrator.runner import CaseRunner, StepContext
from app.platform.precedent import CITE_THRESHOLD, LocalPrecedent, key_from_case
from app.state import AppState, build_state
from app.store.memory import InMemoryRepository

from conftest import banking

SETTINGS = Settings()

# The shape of the case a human actually gets asked about: every lane supports the request, the
# vendor was reached on the number of record, and the only thing stopping an automatic release is
# that $300,000 sits above the auto-release ceiling. Rail 4 exists to put exactly this in front of
# a person, which makes it the case a precedent is most tempted to answer.
ESCALATION_LANES = [
    ("callback", "supports", 0.95),
    ("ledger", "supports", 0.90),
    ("provenance", "supports", 0.88),
    ("registry-check", "supports", 0.90),
]


def _finding(agent: str, verdict: str, confidence: float) -> Finding:
    return Finding(
        finding_id=f"F-{agent}",
        agent=agent,
        agent_version="1.0.0",
        signal=f"{agent}_signal",
        verdict=verdict,
        confidence=confidence,
        evidence=[EvidenceRef(source="test", locator=agent, excerpt="observed value")]
        if verdict != "inconclusive"
        else [],
        reasoning=f"{agent} reasoning",
    )


def _case(
    case_id: str,
    *,
    exposure: str = "300000.00",
    lanes=ESCALATION_LANES,
    tenant_id: str = "riverbend",
    vendor_id: str = "V-NORTHWIND",
    state: CaseState = CaseState.ESCALATED,
) -> Case:
    return Case(
        case_id=case_id,
        request_id=f"REQ-{case_id}",
        tenant_id=tenant_id,
        vendor_id=vendor_id,
        state=state,
        exposure_amount=Decimal(exposure),
        opened_at=DEMO_EPOCH,
        deadline_at=DEMO_EPOCH + timedelta(days=7),
        findings=[_finding(*lane) for lane in lanes],
    )


def _key(case: Case, vendor: Vendor | None = None):
    return key_from_case(
        case, vendor, now=DEMO_EPOCH,
        callback_threshold=SETTINGS.CALLBACK_REQUIRED_THRESHOLD,
        release_ceiling=SETTINGS.AUTO_RELEASE_CEILING,
    )


def _precedent(case: Case, *, precedent_id: str = "PR-TEST01", outcome: str = "RELEASE",
               rationale: str = "Confirmed with the CFO on the number of record.") -> Precedent:
    return Precedent(
        precedent_id=precedent_id,
        case_id=case.case_id,
        tenant_id=case.tenant_id,
        outcome=outcome,
        rationale=rationale,
        decided_by="D. Whitfield, Business Manager",
        decided_at=DEMO_EPOCH,
        key=_key(case),
        vendor_id=case.vendor_id,
        exposure_amount=case.exposure_amount,
    )


def _citation(*, outcome: str = "RELEASE", governs: bool = True,
              opinion: bool = True) -> dict:
    citation = {
        "precedent_id": "PR-TEST01",
        "prior_case_id": "CASE-PRIOR",
        "outcome": outcome,
        "rationale": "Confirmed with the CFO on the number of record.",
        "decided_by": "D. Whitfield, Business Manager",
        "decided_at": DEMO_EPOCH.isoformat(),
        "score": 0.9,
        "matched_on": ["same exposure band 'above_release_ceiling'"],
        "key": {},
    }
    if opinion:
        citation["opinion"] = {
            "governs": governs,
            "confidence": 0.8,
            "reasoning": "Same rail regime, same lanes, same callback state.",
            "distinguished_by": None if governs else "the earlier vendor had ten years' tenure",
        }
    return citation


async def _state(repo: InMemoryRepository) -> AppState:
    state = build_state(SETTINGS, repo)
    state.clock = FrozenClock(DEMO_EPOCH)
    return state


# --- INV-8: a decision that cannot show its work ------------------------------

@pytest.mark.parametrize("rationale", ["", "   ", "\n\t"])
def test_a_precedent_without_a_rationale_is_rejected(rationale):
    """INV-8. Same reasoning as INV-1, applied to a human: a position that cannot show its work
    must not be citable in an adjudication, and a blank one is worse than none — it carries a
    named reviewer's authority with nothing behind it."""
    with pytest.raises(ValidationError):
        Precedent(
            precedent_id="PR-BLANK",
            case_id="CASE-A1B2C3",
            outcome="RELEASE",
            rationale=rationale,
            decided_by="D. Whitfield, Business Manager",
            decided_at=DEMO_EPOCH,
            key=_key(_case("CASE-A1B2C3")),
        )


async def test_the_api_refuses_a_blank_rationale_before_the_money_moves():
    """The validator is the backstop, not the gate. A caller must get a 422, and the payments must
    still be held when they do."""
    repo = InMemoryRepository()
    state = await _state(repo)
    case = _case("CASE-BLANK")
    await repo.save_case(case)

    with pytest.raises(HTTPException) as exc:
        await resolve_case(case.case_id, Resolution(
            outcome="RELEASE", rationale="   ", decided_by="D. Whitfield"), state)
    assert exc.value.status_code == 422
    assert (await repo.get_case(case.case_id)).state is CaseState.ESCALATED


# --- scopes: enforced, not asserted -------------------------------------------

async def test_the_precedent_clerk_holds_no_money_power():
    """A precedent is an argument put to the adjudicator, never an instruction. The agent that
    remembers what the organisation decided must not also be able to act on it."""
    grant = FLEET_SCOPES["precedent-clerk"]
    assert grant.permits(Scope.FINDINGS_READ)
    assert grant.permits(Scope.PRECEDENT_READ)
    assert grant.permits(Scope.PRECEDENT_WRITE)
    for denied in (Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK, Scope.PAYMENTS_FREEZE,
                   Scope.ERP_WRITE, Scope.VENDOR_BANKING_READ, Scope.THREATINTEL_WRITE):
        assert not grant.permits(denied), f"the clerk must not hold {denied}"

    # Enforcement, through a real call_tool rather than a permits() assertion.
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    clerk = PrecedentClerkAgent(SETTINGS)
    ctx = AgentContext(case_id="CASE-A1B2C3", repo=repo, clock=clock, settings=SETTINGS,
                       replay=None, telemetry=None, llm=None)
    vendor = Vendor(
        vendor_id="V-NORTHWIND", legal_name="Northwind Components LLC",
        onboarded_at=DEMO_EPOCH - timedelta(days=6 * 365),
        contact_email_of_record="ap@northwind-components.test",
        contact_phone_of_record="+1-503-555-0142", banking=banking(),
        operating_country="US",
    )
    with pytest.raises(ScopeViolation):
        await clerk.call_tool(ctx, "scheduled_exposure", payments=[])
    with pytest.raises(ScopeViolation):
        await clerk.call_tool(ctx, "read_vendor_banking", vendor=vendor)

    denials = [e for e in await repo.list_posture_events() if e["kind"] == "identity_denial"]
    assert len(denials) == 2, "a denial the system cannot show is one a reviewer assumes we faked"
    assert {d["policy_id"] for d in denials} == {"interdict-policy/precedent-clerk-v1"}


# --- the similarity boundary, in both directions ------------------------------

async def test_a_precedent_is_scoped_to_one_tenant():
    """Tradecraft travels between districts; risk appetite does not. One district's willingness to
    release at $300,000 says nothing about another's, and the reviewer named in it has no standing
    over there."""
    repo = InMemoryRepository()
    book = LocalPrecedent(repo)
    decided = _case("CASE-RIVER", tenant_id="riverbend")
    await book.record(_precedent(decided))

    live = _case("CASE-OTHER", tenant_id="brightwater")
    assert await book.match(_key(live), "brightwater") == []
    assert await book.match(_key(live), "riverbend"), (
        "the same characteristics must still match inside the district that decided them"
    )


async def test_a_different_exposure_band_is_not_citable():
    """$40,000 cannot speak for $400,000. The bands are the rails themselves — below the callback
    threshold nobody had to be phoned, above the ceiling nothing could have been released without
    a human — so a different band means a different question was being answered."""
    repo = InMemoryRepository()
    book = LocalPrecedent(repo)
    await book.record(_precedent(_case("CASE-SMALL", exposure="40000.00")))

    live = _case("CASE-LARGE", exposure="400000.00")
    assert await book.match(_key(live), "riverbend") == []

    # Everything else about the two cases is identical, so the band is doing the work alone.
    same_band = _case("CASE-ALSO-SMALL", exposure="45000.00")
    assert await book.match(_key(same_band), "riverbend"), (
        "two cases under the same rail regime must still be citable"
    )


async def test_an_unanswered_callback_cannot_cite_a_confirmed_callback_precedent():
    """Silence is never confirmation. A precedent set after a person actually spoke to the vendor
    on the number of record cannot govern a case where nobody answered — those are different
    facts, not a weaker version of the same one."""
    repo = InMemoryRepository()
    book = LocalPrecedent(repo)
    await book.record(_precedent(_case("CASE-ANSWERED")))

    unanswered = _case("CASE-SILENT", lanes=[
        ("callback", "inconclusive", 0.0),
        ("ledger", "supports", 0.90),
        ("provenance", "supports", 0.88),
        ("registry-check", "supports", 0.90),
    ])
    assert _key(unanswered).callback_resolved is False
    assert await book.match(_key(unanswered), "riverbend") == []


async def test_three_of_four_lanes_agreeing_still_cites_but_two_of_four_does_not():
    """The Jaccard gradient, pinned. Exact equality on the verdict pattern would make a precedent
    essentially never citable twice — four lanes with three verdicts each is too large a space —
    so overlap degrades instead: three of four is a weaker citation, two of four is not one."""
    repo = InMemoryRepository()
    book = LocalPrecedent(repo)
    await book.record(_precedent(_case("CASE-PRIOR")))

    one_lane_differs = _case("CASE-THREE", lanes=[
        ("callback", "supports", 0.95),
        ("ledger", "inconclusive", 0.40),
        ("provenance", "supports", 0.88),
        ("registry-check", "supports", 0.90),
    ])
    two_lanes_differ = _case("CASE-TWO", lanes=[
        ("callback", "supports", 0.95),
        ("ledger", "inconclusive", 0.40),
        ("provenance", "inconclusive", 0.35),
        ("registry-check", "supports", 0.90),
    ])

    cited = await book.match(_key(one_lane_differs), "riverbend")
    assert cited and cited[0].score >= CITE_THRESHOLD
    assert await book.match(_key(two_lanes_differ), "riverbend") == [], (
        "half the fleet reaching a different conclusion is a different case"
    )


async def test_tenure_is_the_only_characteristic_allowed_to_differ_alone():
    """A five-year vendor and a six-year one read identically, which is why tenure is worth 0.10.
    It is the one dimension that can move on its own without breaking the citation."""
    repo = InMemoryRepository()
    book = LocalPrecedent(repo)
    established = Vendor(
        vendor_id="V-NORTHWIND", legal_name="Northwind Components LLC",
        onboarded_at=DEMO_EPOCH - timedelta(days=6 * 365),
        contact_email_of_record="ap@northwind-components.test",
        contact_phone_of_record="+1-503-555-0142", banking=banking(), operating_country="US",
    )
    new = established.model_copy(update={"onboarded_at": DEMO_EPOCH - timedelta(days=30)})

    decided = _case("CASE-ESTABLISHED")
    await book.record(Precedent(
        precedent_id="PR-TENURE", case_id=decided.case_id, tenant_id=decided.tenant_id,
        outcome="RELEASE", rationale="Long relationship, confirmed by phone.",
        decided_by="D. Whitfield, Business Manager", decided_at=DEMO_EPOCH,
        key=_key(decided, established), vendor_id=decided.vendor_id,
        exposure_amount=decided.exposure_amount,
    ))

    live = _case("CASE-NEW-VENDOR")
    matches = await book.match(_key(live, new), "riverbend")
    assert matches, "tenure alone must not sink an otherwise identical case"
    assert matches[0].score < 1.0, "and it must still cost the citation something"


# --- the safety property ------------------------------------------------------

@pytest.mark.parametrize("railed", ["RELEASE", "ESCALATE", "BLOCK"])
@pytest.mark.parametrize("prior", ["RELEASE", "BLOCK"])
@pytest.mark.parametrize("governs", [True, False])
def test_precedent_can_only_ever_make_an_outcome_more_conservative(railed, prior, governs):
    """The whole safety argument, exhaustively. Whatever the rails settled on and whatever the
    book says, a precedent may move the outcome UP the conservatism scale and never down."""
    adjudicator = AdjudicatorAgent(SETTINGS)
    outcome, _ = adjudicator.apply_precedent(
        _citation(outcome=prior, governs=governs), railed
    )
    assert CONSERVATISM[outcome] >= CONSERVATISM[railed]
    if prior == "RELEASE":
        assert outcome == railed, (
            "a human releasing one case must not become a rule that releases the next"
        )


async def test_precedent_alone_cannot_turn_an_escalate_into_a_release():
    """The named safety property, through the real adjudicator.

    Every lane supports the request, the vendor was reached, the model asks for a release, and a
    governing precedent records a person releasing a structurally identical case. The auto-release
    ceiling still holds: this one goes to a human, and the precedent goes into their reading.
    """
    adjudicator = AdjudicatorAgent(SETTINGS)

    async def proposes_release(_ctx, _prompt, _obs):
        return {"outcome": "RELEASE", "confidence": 0.93,
                "rationale": "Every lane supports the change.", "dissenting_findings": []}

    adjudicator.infer = proposes_release  # type: ignore[method-assign]
    case = _case("CASE-CEILING", state=CaseState.ADJUDICATING)
    ctx = AgentContext(
        case_id=case.case_id, repo=InMemoryRepository(), clock=FrozenClock(DEMO_EPOCH),
        settings=SETTINGS, replay=None, telemetry=None, llm=None,
        payload={"precedent": _citation(outcome="RELEASE", governs=True)},
    )

    decision = await adjudicator.decide(ctx, case, case.findings, None)
    assert decision.outcome == "ESCALATE"
    assert "auto-release ceiling" in decision.rationale
    assert "CASE-PRIOR" in decision.rationale
    assert "D. Whitfield" in decision.rationale, (
        "the reviewer's earlier reasoning is what the human on this case wants to read"
    )


async def test_an_adjudication_with_no_precedent_is_unchanged_by_this_feature():
    """The replay cache is keyed on (agent, model, prompt, observations), so a prompt that grew a
    paragraph would silently invalidate every recorded adjudication and force live model calls
    mid-demo. A case with no citation must reach the model exactly as it did before."""
    from app.agents.adjudicator import PROMPT

    adjudicator = AdjudicatorAgent(SETTINGS)
    seen: dict[str, object] = {}

    async def capture(_ctx, prompt, observations):
        seen["prompt"], seen["observations"] = prompt, observations
        return {"outcome": "ESCALATE", "confidence": 0.5, "rationale": "Needs a person."}

    adjudicator.infer = capture  # type: ignore[method-assign]
    case = _case("CASE-NO-BOOK", state=CaseState.ADJUDICATING)
    ctx = AgentContext(case_id=case.case_id, repo=InMemoryRepository(),
                       clock=FrozenClock(DEMO_EPOCH), settings=SETTINGS,
                       replay=None, telemetry=None, llm=None)

    decision = await adjudicator.decide(ctx, case, case.findings, None)
    assert seen["prompt"] == PROMPT
    assert "precedent" not in seen["observations"]
    assert "Precedent" not in decision.rationale


async def test_a_precedent_never_overrides_the_block_rail():
    """Rail 1 is absolute. An unrebutted high-confidence contradiction blocks whatever the model
    said, and a precedent is not a rebuttal — nobody argued this finding away, they decided a
    different case."""
    adjudicator = AdjudicatorAgent(SETTINGS)

    async def proposes_release(_ctx, _prompt, _obs):
        return {"outcome": "RELEASE", "confidence": 0.9, "rationale": "Looks routine.",
                "dissenting_findings": []}

    adjudicator.infer = proposes_release  # type: ignore[method-assign]
    case = _case("CASE-CONTRADICTED", state=CaseState.ADJUDICATING, lanes=[
        ("callback", "supports", 0.95),
        ("ledger", "supports", 0.90),
        ("provenance", "contradicts", 0.94),
        ("registry-check", "supports", 0.90),
    ])
    ctx = AgentContext(
        case_id=case.case_id, repo=InMemoryRepository(), clock=FrozenClock(DEMO_EPOCH),
        settings=SETTINGS, replay=None, telemetry=None, llm=None,
        payload={"precedent": _citation(outcome="RELEASE", governs=True)},
    )

    decision = await adjudicator.decide(ctx, case, case.findings, None)
    assert decision.outcome == "BLOCK"


async def test_a_governing_block_precedent_stops_the_money_without_asking_again():
    """The payoff, in the only direction it is safe. This district has already stopped a case with
    the same exposure band, verdict pattern and callback state; stopping this one is the direction
    every other rail moves, and a payment held in error is paid late rather than gone."""
    adjudicator = AdjudicatorAgent(SETTINGS)
    outcome, note = adjudicator.apply_precedent(
        _citation(outcome="BLOCK", governs=True), "ESCALATE"
    )
    assert outcome == "BLOCK"
    assert "raised from ESCALATE to BLOCK" in note

    # Against live evidence of legitimacy it goes to a person instead, rather than overruling the
    # lanes on the strength of an older case.
    outcome, _ = adjudicator.apply_precedent(_citation(outcome="BLOCK", governs=True), "RELEASE")
    assert outcome == "ESCALATE"


def test_a_precedent_that_does_not_govern_changes_nothing_but_is_still_shown():
    """An operator overruling the clerk needs to know what it thought was different."""
    adjudicator = AdjudicatorAgent(SETTINGS)
    outcome, note = adjudicator.apply_precedent(
        _citation(outcome="BLOCK", governs=False), "ESCALATE"
    )
    assert outcome == "ESCALATE"
    assert "ten years' tenure" in note


# --- enrichment, never a gate -------------------------------------------------

def test_a_matched_precedent_with_no_opinion_is_not_a_ruling():
    """A missing opinion means the clerk was unavailable, not that it agreed. The match stands as
    a match; no argument was made on it, so nothing about the outcome moves."""
    adjudicator = AdjudicatorAgent(SETTINGS)
    outcome, note = adjudicator.apply_precedent(
        _citation(outcome="BLOCK", opinion=False), "ESCALATE"
    )
    assert outcome == "ESCALATE"
    assert "no argument was made" in note


async def test_a_case_decides_normally_when_the_clerk_is_unavailable(
    repo, clock, payments, world, stub_agents
):
    """Enrichment, not a gate. A broken book and an empty one must both leave the case deciding
    exactly as it did before precedent existed."""
    events: list[tuple[str, dict]] = []

    async def emit(event: str, data: dict) -> None:
        events.append((event, data))

    async def exploding_precedent(_ctx, _case):
        raise RuntimeError("model unavailable")

    runner = CaseRunner(
        repo=repo, clock=clock,
        steps=build_pipeline(
            payments, stub_agents["fanout"], stub_agents["challenge"],
            stub_agents["adjudicate"], precedent=exploding_precedent,
        ),
        emit=emit,
    )
    await runner.advance(world["case"].case_id, {"callback_response": "denied"})

    case = await repo.get_case(world["case"].case_id)
    assert case.state is CaseState.BLOCKED
    assert case.exposure_amount == Decimal("340000.00")
    assert any(name == "precedent_unavailable" for name, _ in events)


async def test_a_citation_reaches_the_adjudicator_and_the_operator(
    repo, clock, payments, world, stub_agents
):
    """The wiring, executed rather than assumed.

    A citation that is stashed in the payload but never read by the agent, or never emitted to the
    console, is the defect class a green suite keeps missing: the path was never run (D-018).
    """
    events: list[tuple[str, dict]] = []
    seen: dict[str, object] = {}

    async def emit(event: str, data: dict) -> None:
        events.append((event, data))

    async def cite(_ctx, _case):
        return _citation(outcome="BLOCK", governs=True)

    async def adjudicate(ctx, findings, challenge_result):
        seen["precedent"] = ctx.payload.get("precedent")
        return await stub_agents["adjudicate"](ctx, findings, challenge_result)

    runner = CaseRunner(
        repo=repo, clock=clock,
        steps=build_pipeline(
            payments, stub_agents["fanout"], stub_agents["challenge"], adjudicate,
            precedent=cite,
        ),
        emit=emit,
    )
    await runner.advance(world["case"].case_id, {"callback_response": "denied"})

    assert seen["precedent"], "the adjudicator never saw the citation"
    assert seen["precedent"]["prior_case_id"] == "CASE-PRIOR"
    cited = [data for name, data in events if name == "precedent_cited"]
    assert cited and cited[0]["decided_by"] == "D. Whitfield, Business Manager"


async def test_the_clerk_never_invents_a_rationale_the_human_did_not_give():
    """An empty resolution stays empty, and costs no model call to stay that way. A model asked to
    explain a blank one supplies reasoning the reviewer never gave, and the fleet then cites a
    named person for a position they never took."""
    clerk = PrecedentClerkAgent(SETTINGS)

    async def must_not_run(*_a, **_k):
        raise AssertionError("a blank rationale must never reach the model")

    clerk.infer = must_not_run  # type: ignore[method-assign]
    ctx = AgentContext(case_id="CASE-A1B2C3", repo=InMemoryRepository(),
                       clock=FrozenClock(DEMO_EPOCH), settings=SETTINGS,
                       replay=None, telemetry=None, llm=None)
    assert await clerk.summarise_resolution(ctx, {"case_id": "CASE-A1B2C3"}, "   ") == ""

    async def returns_nothing(_ctx, _prompt, _obs):
        return {"rationale": ""}

    clerk.infer = returns_nothing  # type: ignore[method-assign]
    written = "Spoke to their controller; the consolidation is real."
    assert await clerk.summarise_resolution(ctx, {}, written) == written, (
        "their words are the fallback, never a generated stand-in for them"
    )


async def test_an_evasive_generation_does_not_govern():
    """`governs` defaults false because absence of an argument is not an argument."""
    clerk = PrecedentClerkAgent(SETTINGS)

    async def evasive(_ctx, _prompt, _obs):
        return {"reasoning": "It is hard to say either way."}

    clerk.infer = evasive  # type: ignore[method-assign]
    ctx = AgentContext(case_id="CASE-A1B2C3", repo=InMemoryRepository(),
                       clock=FrozenClock(DEMO_EPOCH), settings=SETTINGS,
                       replay=None, telemetry=None, llm=None)
    opinion = await clerk.opine(ctx, _citation(), {"case_id": "CASE-A1B2C3"})
    assert opinion.governs is False


# --- the API surface ----------------------------------------------------------

async def test_resolving_a_terminal_case_is_a_conflict():
    """Same as api/callback.py: a decision already applied is not one to apply again."""
    repo = InMemoryRepository()
    state = await _state(repo)
    settled = _case("CASE-SETTLED", state=CaseState.BLOCKED)
    await repo.save_case(settled)

    with pytest.raises(HTTPException) as exc:
        await resolve_case(settled.case_id, Resolution(
            outcome="RELEASE", rationale="Reconsidered.", decided_by="D. Whitfield"), state)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as unknown:
        await resolve_case("CASE-NOPE", Resolution(
            outcome="RELEASE", rationale="Reconsidered.", decided_by="D. Whitfield"), state)
    assert unknown.value.status_code == 404


async def test_a_resolution_records_who_decided_and_finalises_the_money():
    """The record and the money move together, or the book describes a district that does not
    exist."""
    repo = InMemoryRepository()
    state = await _state(repo)
    case = _case("CASE-RESOLVE")
    for i, amount in enumerate(("150000.00", "150000.00")):
        await repo.save_payment(Payment(
            payment_id=f"PAY-RES{i}", vendor_id=case.vendor_id, amount=Decimal(amount),
            status=PaymentStatus.HELD, held_by_case_id=case.case_id,
            scheduled_for=DEMO_EPOCH + timedelta(days=2),
        ))
        case.held_payment_ids.append(f"PAY-RES{i}")
    case.assert_exposure_matches(await repo.get_payments(case.held_payment_ids))
    await repo.save_case(case)

    result = await resolve_case(case.case_id, Resolution(
        outcome="RELEASE",
        rationale="Spoke to their controller; the consolidation is real.",
        decided_by="D. Whitfield, Business Manager",
    ), state)

    assert result["state"] == "released"
    assert result["precedent_id"].startswith("PR-")
    stored = await repo.get_case(case.case_id)
    assert stored.state is CaseState.RELEASED
    settled = await repo.get_payments(stored.held_payment_ids)
    assert [p.status for p in settled] == [PaymentStatus.RELEASED] * 2, (
        "the record moved but the money did not"
    )
    assert stored.decision.decided_by == "human"
    assert stored.decision.human_reviewer == "D. Whitfield, Business Manager"

    precedent = await get_precedent(result["precedent_id"], state)
    assert precedent["rationale"] == "Spoke to their controller; the consolidation is real."
    assert precedent["exposure_amount"] == "300000.00", "money crosses the wire as a string"
    assert [e["kind"] for e in await repo.list_posture_events()] == ["precedent_recorded"]

    with pytest.raises(HTTPException) as missing:
        await get_precedent("PR-NOTHERE", state)
    assert missing.value.status_code == 404


async def test_the_second_identical_escalation_cites_the_first():
    """The end-to-end claim, with no model call anywhere in it.

    A person resolves an escalation. A structurally identical case arrives later and the fleet
    hands the next reviewer the earlier ruling, by name, with the reasons it matched.
    """
    repo = InMemoryRepository()
    state = await _state(repo)

    first = _case("CASE-FIRST")
    await repo.save_case(first)
    resolved = await resolve_case(first.case_id, Resolution(
        outcome="RELEASE",
        rationale="Spoke to their controller; the consolidation is real.",
        decided_by="D. Whitfield, Business Manager",
    ), state)

    second = _case("CASE-SECOND", vendor_id="V-ASHFIELD")
    await repo.save_case(second)
    match = await precedent_for_case(second.case_id, state)

    assert match["candidates_considered"] == 1
    cited = match["cited"]
    assert cited is not None, "the second identical escalation cited nothing"
    assert cited["precedent_id"] == resolved["precedent_id"]
    assert cited["prior_case_id"] == first.case_id, "a citation must name its source case"
    assert cited["decided_by"] == "D. Whitfield, Business Manager"
    assert cited["score"] >= CITE_THRESHOLD
    assert cited["matched_on"], "a citation that cannot say why it matched is not auditable"

    # And the book records which later cases leaned on that one ruling, which is what makes it
    # auditable: a reviewer can ask what a single decision of theirs went on to shape.
    await state.platform.precedent.cite(resolved["precedent_id"], second.case_id)
    book = await list_precedents(None, state)
    assert book["count"] == 1
    assert book["precedents"][0]["cited_by_case_ids"] == [second.case_id]
    assert book["precedents"][0]["case_id"] == first.case_id


async def test_the_book_is_listed_per_district():
    repo = InMemoryRepository()
    state = await _state(repo)
    for tenant, case_id in (("riverbend", "CASE-R1"), ("brightwater", "CASE-B1")):
        case = _case(case_id, tenant_id=tenant)
        await repo.save_case(case)
        await resolve_case(case.case_id, Resolution(
            outcome="BLOCK", rationale="Never reached them on the number of record.",
            decided_by="D. Whitfield, Business Manager"), state)

    assert (await list_precedents(None, state))["count"] == 2
    riverbend = await list_precedents("riverbend", state)
    assert riverbend["count"] == 1
    assert riverbend["precedents"][0]["case_id"] == "CASE-R1"


# --- The path nobody had executed --------------------------------------------

async def test_a_resolution_survives_a_session_this_process_never_opened():
    """The reviewer's case is almost never one this process opened.

    A case carries its `session_id` in the store, and the store outlives the process. Seeded
    history arrives holding literal ids, and a restart leaves every live case holding one that
    `LocalMemory` has no record of. Journalling the resolution against such an id used to raise,
    and it raised *after* `finalize` had already moved the money and marked the case terminal —
    so the reviewer was told their block had failed by a handler that had in fact completed it,
    and the obvious response was to press the button again.
    """
    repo = InMemoryRepository()
    state = await _state(repo)
    case = _case("CASE-STALESESSION")
    case.session_id = "sess-openedbyapreviousprocess"
    await repo.save_payment(Payment(
        payment_id="PAY-STALE0", vendor_id=case.vendor_id, amount=Decimal("300000.00"),
        status=PaymentStatus.HELD, held_by_case_id=case.case_id,
        scheduled_for=DEMO_EPOCH + timedelta(days=2),
    ))
    case.held_payment_ids.append("PAY-STALE0")
    await repo.save_case(case)

    result = await resolve_case(case.case_id, Resolution(
        outcome="BLOCK",
        rationale="Reached them on the number of record; they never asked for the change.",
        decided_by="D. Whitfield, Business Manager"), state)

    assert result["state"] == "blocked"
    stored = await repo.get_case(case.case_id)
    assert stored.state is CaseState.BLOCKED
    assert [p.status for p in await repo.get_payments(stored.held_payment_ids)] == [
        PaymentStatus.BLOCKED
    ], "the reviewer was told it worked, so the money must actually have stopped"

    # And the journal took the entry rather than being quietly dropped: beat 5 rehydrates from it.
    events = await state.platform.memory.rehydrate(case.session_id)
    assert [e.kind for e in events] == ["precedent_recorded"]


async def test_the_book_records_only_the_rulings_that_actually_shaped_a_case():
    """`cited_by_case_ids` answers "which decisions did this ruling shape", so it may not count
    a case the ruling was explicitly not applied to.

    The two halves of the feature disagreed here. `apply_precedent` reads a missing opinion as
    the clerk being unavailable and declines to apply the precedent; the citation recorder read
    the same missing key as consent and wrote the case into the book anyway.
    """
    repo = InMemoryRepository()
    state = await _state(repo)
    first = _case("CASE-SHAPED")
    await repo.save_case(first)
    resolved = await resolve_case(first.case_id, Resolution(
        outcome="BLOCK", rationale="Never reached them on the number of record.",
        decided_by="D. Whitfield, Business Manager"), state)

    # The clerk is unavailable, so no argument is made that the earlier ruling governs.
    class _MuteClerk:
        model = "stub"

        async def opine(self, *args, **kwargs):
            raise RuntimeError("clerk unavailable")

    state.agents["precedent-clerk"] = _MuteClerk()
    second = _case("CASE-UNSHAPED", vendor_id="V-ASHFIELD")
    await repo.save_case(second)

    # The production closure itself, lifted off the step that owns it, rather than a
    # reimplementation of it here — the whole point is that this path gets executed.
    cite = next(
        s.precedent for s in state.build_runner()._steps if getattr(s, "precedent", None)
    )
    citation = await cite(
        StepContext(case=second, repo=repo, clock=state.clock, emit=state.emit), second
    )
    assert citation is not None, "the match still stands as a match"
    assert "opinion" not in citation, "the clerk never rendered one"

    book = await list_precedents(None, state)
    assert book["precedents"][0]["precedent_id"] == resolved["precedent_id"]
    assert book["precedents"][0]["cited_by_case_ids"] == [], (
        "a precedent the fleet declined to apply must not claim it shaped the case"
    )
