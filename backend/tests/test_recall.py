"""Cross-case attacker recall.

The capability: block an attack on one vendor, then recognise the same tradecraft when it arrives
against a DIFFERENT vendor. Before this, every case started from zero and the fleet could be hit
by the same operation repeatedly without noticing.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import DEMO_EPOCH, FrozenClock, Settings
from app.models.domain import CaseState
from app.orchestrator.pipeline import build_pipeline
from app.orchestrator.runner import CaseRunner
from app.platform.memory import LocalMemory
from app.platform.recall import (
    MATCH_THRESHOLD,
    Fingerprint,
    LocalRecall,
    _homoglyph_technique,
    fingerprint_from_request,
    score_match,
)
from app.seed.generate import seed_all
from app.seed.scenarios import build_request
from app.services.payments import PaymentService
from app.store.memory import InMemoryRepository

# --- fingerprinting ----------------------------------------------------------

@pytest.mark.parametrize(
    "observed,legit,expected",
    [
        ("northwind-cornponents.test", "northwind-components.test", "m->rn"),
        ("ashfield-chernical.test", "ashfield-chemical.test", "m->rn"),
        ("kestrel-machining.test", "kestrel-machining.test", None),
    ],
)
def test_homoglyph_technique_is_named_not_just_detected(observed, legit, expected):
    """The technique is the durable signal. Attackers burn domains constantly and reuse tradecraft,
    so 'm->rn' generalises where a domain string does not."""
    assert _homoglyph_technique(observed, legit) == expected


def _attack_fp(beneficiary="NW Holdings Group", bank="Cascade Union Trust",
               reply_to="northwind-cornponents.test", vendor="northwind-components.test",
               age=11, phone="+1-702-555-0199", channel="email") -> Fingerprint:
    return fingerprint_from_request(
        proposed_account_name=beneficiary, proposed_bank=bank, reply_to_domain=reply_to,
        vendor_domain=vendor, domain_age_days=age, supplied_phone=phone, channel=channel,
    )


def test_same_operation_against_a_different_vendor_scores_a_match():
    first = _attack_fp()
    second = _attack_fp(reply_to="ashfield-chernical.test", vendor="ashfield-chemical.test",
                        age=9, phone="+1-702-555-0143", channel="invoice_pdf")
    score, matched = score_match(second, first)
    assert score >= MATCH_THRESHOLD
    assert any("beneficiary" in m for m in matched)
    assert any("technique" in m for m in matched)


def test_a_genuine_change_does_not_match_a_remembered_attack():
    """False positives here are expensive: they would block legitimate vendors."""
    attack = _attack_fp()
    genuine = fingerprint_from_request(
        proposed_account_name="Kestrel Machining Inc.", proposed_bank="Harbor Point Bank",
        reply_to_domain="kestrel-machining.test", vendor_domain="kestrel-machining.test",
        domain_age_days=2700, supplied_phone=None, channel="email",
    )
    score, _ = score_match(genuine, attack)
    assert score < MATCH_THRESHOLD


def test_two_unrelated_attacks_sharing_only_a_new_domain_do_not_match():
    """A new domain alone is far too common to imply a shared operation."""
    a = _attack_fp(beneficiary="Atlas Receivables", bank="Granite Fidelity", phone=None)
    b = _attack_fp(beneficiary="Meridian Factoring", bank="Lakeshore National", phone=None)
    score, _ = score_match(b, a)
    assert score < MATCH_THRESHOLD


async def test_only_blocked_cases_are_remembered():
    """Remembering a RELEASE would teach the fleet to distrust legitimate behaviour."""
    recall = LocalRecall()
    fp = _attack_fp()
    await recall.remember("CASE-RELEASED", "V-1", "RELEASE", fp)
    await recall.remember("CASE-ESCALATED", "V-2", "ESCALATE", fp)
    assert await recall.known_count() == 0
    await recall.remember("CASE-BLOCKED", "V-3", "BLOCK", fp)
    assert await recall.known_count() == 1


async def test_remember_is_idempotent_per_case():
    recall = LocalRecall()
    fp = _attack_fp()
    for _ in range(3):
        await recall.remember("CASE-X", "V-1", "BLOCK", fp)
    assert await recall.known_count() == 1


# --- end to end through the real pipeline ------------------------------------

@pytest.fixture
def stub_fleet():
    from app.models.domain import ChallengeResult, Decision, EvidenceRef, Finding, Rebuttal

    def finding(agent, verdict, conf):
        return Finding(
            finding_id=f"F-{agent}", agent=agent, agent_version="1.0.0",
            signal=f"{agent}_signal", verdict=verdict, confidence=conf,
            evidence=[EvidenceRef(source="t", locator=agent, excerpt="observed")],
            reasoning=f"{agent} reasoning",
        )

    async def fanout(ctx):
        return [
            finding("provenance", "contradicts", 0.94),
            finding("registry-check", "contradicts", 0.91),
            finding("ledger", "inconclusive", 0.40),
            finding("callback", "contradicts", 0.97),
        ]

    async def challenge(ctx, findings):
        return ChallengeResult(
            strongest_legitimate_explanation="A factoring arrangement could explain this.",
            rebuttals=[Rebuttal(finding_id=f.finding_id, argument="considered", succeeds=False)
                       for f in findings],
            survived=False, reasoning="No rebuttal survives the callback denial.",
        )

    async def adjudicate(ctx, findings, ch):
        return Decision(outcome="BLOCK", confidence=0.98,
                        rationale="Unrebutted contradictions.", decided_at=ctx.clock.now())

    return fanout, challenge, adjudicate


async def test_second_victim_of_the_same_attacker_is_recognised_on_arrival(stub_fleet):
    """The headline capability, end to end through the real pipeline.

    S1 targets Northwind and is blocked, which records the tradecraft. S2 then targets a
    completely different vendor using the same beneficiary and technique, and the fleet must
    recognise it BEFORE the verification lanes run.
    """
    fanout, challenge, adjudicate = stub_fleet
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    recall, memory = LocalRecall(), LocalMemory()
    payments = PaymentService(repo, clock)
    await seed_all(repo, clock.now())

    from app.agents.base import AgentContext
    from app.agents.sentry import SentryAgent

    sentry = SentryAgent(Settings())

    async def run(scenario_id: str):
        request = build_request(scenario_id, clock.now(), f"REQ-{scenario_id}")
        await repo.save_request(request)
        ctx = AgentContext(case_id="", repo=repo, clock=clock, settings=Settings(),
                           replay=None, telemetry=None, llm=None,
                           payload={"request_id": request.request_id})
        case = await sentry.open_case(ctx, request)
        case.session_id = await memory.open_session(case.case_id, clock.now().isoformat())
        await repo.save_case(case)
        runner = CaseRunner(repo, clock, build_pipeline(
            payments, fanout, challenge, adjudicate, recall=recall, memory=memory))
        await runner.advance(case.case_id, {"callback_response": "denied"})
        return await repo.get_case(case.case_id)

    # First victim. Nothing to recall yet.
    first = await run("S1")
    assert first.state is CaseState.BLOCKED
    assert first.exposure_amount == Decimal("340000.00")
    assert first.finding_by_agent("attribution") is None, (
        "nothing should be attributed on the first sighting"
    )
    assert await recall.known_count() == 1, "the block must have been remembered"

    # Second victim, different vendor, same operation.
    second = await run("S2")
    assert second.vendor_id != first.vendor_id, "S2 must target a different vendor"

    hit = second.finding_by_agent("attribution")
    assert hit is not None, "the repeat attacker was NOT recognised"
    assert hit.verdict == "contradicts"
    assert hit.confidence >= 0.6
    assert hit.evidence, "a recall finding must cite the prior case"
    # The locator names the operation and the case, e.g. "Hollow Ledger (CASE-3ADDFA)".
    assert any(first.case_id in e.locator for e in hit.evidence), (
        f"the finding must name the earlier case by ID; got "
        f"{[e.locator for e in hit.evidence]}"
    )


async def test_recall_finding_arrives_before_the_verification_lanes(stub_fleet):
    """Ordering is the point: a recognised attacker should be on screen immediately, not after
    four lanes finish."""
    fanout, challenge, adjudicate = stub_fleet
    payments = PaymentService(InMemoryRepository(), FrozenClock(DEMO_EPOCH))
    steps = build_pipeline(payments, fanout, challenge, adjudicate,
                           recall=LocalRecall(), memory=LocalMemory())
    names = [s.name for s in steps]
    assert names.index("recall_prior_art") < names.index("fanout_verification")


async def test_retrieval_costs_no_model_calls(stub_fleet):
    """RETRIEVAL is a deterministic match over structured tradecraft. It must never need an LLM,
    both for cost and because it must be structurally incapable of inventing a prior case.

    Attribution — deciding the match MEANS the same operator — is a separate, agentic step.
    """
    recall = LocalRecall()
    await recall.remember("CASE-A", "V-1", "BLOCK", _attack_fp())
    # llm is None throughout; a model call would raise AttributeError.
    matches = await recall.recall(_attack_fp(reply_to="ashfield-chernical.test",
                                             vendor="ashfield-chemical.test"))
    assert matches and matches[0].prior_case_id == "CASE-A"


async def test_attribution_is_delegated_to_an_agent_when_one_is_available(stub_fleet):
    """The judgement must be agentic. Retrieval finds candidates; an agent decides what the
    resemblance MEANS, and its verdict is what lands on the case."""
    fanout, challenge, adjudicate = stub_fleet
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    recall, memory = LocalRecall(), LocalMemory()
    payments = PaymentService(repo, clock)
    await seed_all(repo, clock.now())

    called: list[str] = []

    async def fake_attribute(ctx, dossier, match, request_summary):
        called.append(match["prior_case_id"])
        # Deliberately disagree with the structured matcher to prove the agent's verdict wins.
        return {
            "verdict": "inconclusive",
            "confidence": 0.31,
            "same_operator": False,
            "reasoning": "Shared regional bank is common; not enough to attribute.",
        }

    async def fake_scribe(ctx, case):
        return {"designation": "Hollow Ledger", "assessment": "test",
                "tradecraft": [], "indicators": [],
                "likely_next_target": "another transport vendor", "confidence": 0.6,
                "first_seen_case_id": case.case_id}

    from app.agents.base import AgentContext
    from app.agents.sentry import SentryAgent

    sentry = SentryAgent(Settings())

    async def run(scenario_id: str):
        request = build_request(scenario_id, clock.now(), f"REQ-{scenario_id}")
        await repo.save_request(request)
        ctx = AgentContext(case_id="", repo=repo, clock=clock, settings=Settings(),
                           replay=None, telemetry=None, llm=None,
                           payload={"request_id": request.request_id})
        case = await sentry.open_case(ctx, request)
        await repo.save_case(case)
        runner = CaseRunner(repo, clock, build_pipeline(
            payments, fanout, challenge, adjudicate, recall=recall, memory=memory,
            attribute=fake_attribute, scribe=fake_scribe))
        await runner.advance(case.case_id, {"callback_response": "denied"})
        return await repo.get_case(case.case_id)

    first = await run("S1")
    library = await recall.library()
    assert library and library[0]["designation"] == "Hollow Ledger", (
        "Scribe's dossier must be stored with the fingerprint"
    )

    second = await run("S2")
    assert called == [first.case_id], "the attribution agent was not consulted"
    hit = second.finding_by_agent("attribution")
    assert hit is not None
    assert hit.verdict == "inconclusive", "the agent's verdict must override the matcher's default"
    assert hit.evidence == [], "an inconclusive finding must cite nothing"


async def test_case_still_blocks_when_the_attribution_agent_fails(stub_fleet):
    """Attribution is enrichment, not a gate. A model outage must not stop an interdiction."""
    fanout, challenge, adjudicate = stub_fleet
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    recall, memory = LocalRecall(), LocalMemory()
    payments = PaymentService(repo, clock)
    await seed_all(repo, clock.now())

    async def exploding_attribute(*_a, **_k):
        raise RuntimeError("model unavailable")

    async def exploding_scribe(*_a, **_k):
        raise RuntimeError("model unavailable")

    from app.agents.base import AgentContext
    from app.agents.sentry import SentryAgent

    sentry = SentryAgent(Settings())

    async def run(scenario_id: str):
        request = build_request(scenario_id, clock.now(), f"REQ-{scenario_id}")
        await repo.save_request(request)
        ctx = AgentContext(case_id="", repo=repo, clock=clock, settings=Settings(),
                           replay=None, telemetry=None, llm=None,
                           payload={"request_id": request.request_id})
        case = await sentry.open_case(ctx, request)
        await repo.save_case(case)
        runner = CaseRunner(repo, clock, build_pipeline(
            payments, fanout, challenge, adjudicate, recall=recall, memory=memory,
            attribute=exploding_attribute, scribe=exploding_scribe))
        await runner.advance(case.case_id, {"callback_response": "denied"})
        return await repo.get_case(case.case_id)

    first = await run("S1")
    assert first.state is CaseState.BLOCKED, "a Scribe outage must not stop the block"
    assert await recall.known_count() == 1, "the fingerprint must still be remembered"

    second = await run("S2")
    assert second.state is CaseState.BLOCKED
    hit = second.finding_by_agent("attribution")
    assert hit is not None, "the deterministic match must still stand alone"
    assert hit.verdict == "contradicts"


async def test_a_woken_case_supersedes_its_stale_findings(stub_fleet):
    """Beat 5. A dormant case that wakes with a vendor confirmation must not keep the earlier
    'callback: inconclusive' finding beside the new one.

    It did, and because `finding_by_agent` returns the first match, the adjudicator read the
    stale verdict and escalated a case the vendor had just confirmed on the number of record.
    """
    import uuid

    from app.models.domain import EvidenceRef, Finding

    _, challenge, adjudicate = stub_fleet
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    payments = PaymentService(repo, clock)
    await seed_all(repo, clock.now())

    def finding(agent, verdict, conf):
        # A fresh id each run, exactly like the real agents.
        return Finding(
            finding_id=f"F-{agent}-{uuid.uuid4().hex[:6]}", agent=agent,
            agent_version="1.0.0", signal=f"{agent}_signal", verdict=verdict, confidence=conf,
            evidence=[EvidenceRef(source="t", locator=agent, excerpt="observed")]
            if verdict != "inconclusive" else [],
            reasoning=f"{agent} reasoning",
        )

    async def fanout(ctx):
        cb = ctx.payload.get("callback_response")
        return [
            finding("callback", "supports" if cb == "confirmed" else "inconclusive",
                    1.0 if cb == "confirmed" else 0.0),
            finding("registry-check", "supports", 0.98),
            finding("ledger", "inconclusive", 0.85),
        ]

    from app.agents.base import AgentContext
    from app.agents.sentry import SentryAgent

    request = build_request("S3", clock.now(), "REQ-S3")
    await repo.save_request(request)
    ctx = AgentContext(case_id="", repo=repo, clock=clock, settings=Settings(),
                       replay=None, telemetry=None, llm=None,
                       payload={"request_id": request.request_id})
    case = await SentryAgent(Settings()).open_case(ctx, request)
    await repo.save_case(case)

    steps = build_pipeline(payments, fanout, challenge, adjudicate)
    runner = CaseRunner(repo, clock, steps)

    # First pass: nobody answers, the case goes dormant.
    await runner.advance(case.case_id, {"callback_response": None})
    dormant = await repo.get_case(case.case_id)
    assert dormant.state is CaseState.AWAITING_CALLBACK
    assert dormant.finding_by_agent("callback").verdict == "inconclusive"

    # The vendor calls back and confirms.
    await runner.advance(case.case_id, {"callback_response": "confirmed"})
    woken = await repo.get_case(case.case_id)

    per_agent = [f.agent for f in woken.findings]
    assert len(per_agent) == len(set(per_agent)), (
        f"each agent must hold exactly one current finding; got {per_agent}"
    )
    assert woken.finding_by_agent("callback").verdict == "supports", (
        "the woken case is still reading the stale callback verdict"
    )


async def test_the_library_groups_by_operation_not_by_case():
    """A second sighting of the same operators is not a second adversary. Listing one row per
    blocked case showed the same designation twice, which reads as two groups."""
    from app.platform.recall import LocalRecall, fingerprint_from_request

    recall = LocalRecall()
    dossier = {"designation": "Deceptive Transit", "first_seen_case_id": "CASE-A"}
    fp = fingerprint_from_request(
        proposed_account_name="NW Holdings Group", proposed_bank="Cascade Union Trust",
        reply_to_domain="a-lookalike.test", vendor_domain="a.test",
        domain_age_days=9, supplied_phone="+1-555-0100", channel="email",
    )
    await recall.remember("CASE-A", "V-1", "BLOCK", fp, dossier)
    await recall.remember("CASE-B", "V-2", "BLOCK", fp, dossier)

    library = await recall.library()
    assert len(library) == 1, f"expected one operation, got {[e['designation'] for e in library]}"
    entry = library[0]
    assert entry["designation"] == "Deceptive Transit"
    assert entry["sighting_count"] == 2
    assert sorted(entry["victims"]) == ["V-1", "V-2"]
    assert await recall.known_count() == 2, "the underlying sighting count is unchanged"
