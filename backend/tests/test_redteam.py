"""Red Team — the fleet attacks itself and publishes the score.

Two things are being pinned here. The first is the blast radius: an invented attack runs against
a sandbox tenant, and nothing it does may reach a district's docket, its payment book, its threat
library or the shared exchange. The second is the arithmetic, because the number IS the feature —
a hit rate that counts a variant that was never executed, or that reports a miss nobody can act
on, is worse than no number at all.

Stub agents throughout. A red team that measures a mocked fleet proves nothing, but a red team
TEST that calls a real model measures the weather.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.base import AgentContext
from app.agents.redteam import AttackVariant, RedTeamRun, RedTeamTrial, is_rerun
from app.agents.scopes import FLEET_SCOPES, Scope, ScopeViolation
from app.agents.tools import TOOL_SPECS, ToolSpec
from app.api.redteam import _scoreboard
from app.config import Settings
from app.models.domain import DEFAULT_TENANT_ID, CaseState, PaymentStatus
from app.seed.generate import seed_all
from app.services.simulation import (
    SIMULATION_TENANT_ID,
    TARGET_DOMAIN,
    TARGET_PAYMENTS,
    run_variant,
)
from app.state import build_state
from app.store.memory import InMemoryRepository


def _variant(**overrides) -> AttackVariant:
    """An attack the fleet would open a case on: it names a bank and asks for a change."""
    fields = dict(
        variant_id="AV-TEST01",
        name="Quiet Consolidation",
        technique="parent-company treasury notice",
        novelty="No library operation has claimed a parent company the district can look up.",
        based_on_designation=None,
        artifact=(
            "Subject: Updated remittance details for our account\n\n"
            "Following a group treasury consolidation, please update the bank account we are "
            "paid into ahead of the next scheduled run."
        ),
        proposed_account_name="Merrivale Group Treasury",
        proposed_bank="Stonebridge Commercial",
        # A lookalike of the target's domain of record, so the provenance lane has something to
        # observe and its findings can carry evidence.
        reply_to_domain="merrivale-instructionaI.test",
        supplied_phone="+1-702-555-0143",
    )
    fields.update(overrides)
    return AttackVariant(**fields)


def _fleet(verdict: str = "contradicts", confidence: float = 0.94, outcome: str = "BLOCK"):
    """One reply that satisfies every agent in the fleet, monkeypatched onto `infer`.

    The lanes read `verdict`, the Challenger reads its own three keys and the Adjudicator reads
    `outcome` — which its rails then override or allow, exactly as in production.
    """
    reply = {
        "verdict": verdict,
        "confidence": confidence,
        "reasoning": "Stubbed lane reasoning for a red-team trial.",
        "action": "investigate",
        "reason": "Asks to change where money is sent.",
        "outcome": outcome,
        "rationale": "Stubbed adjudication.",
        "dissenting_findings": [],
        "strongest_legitimate_explanation": "A treasury consolidation could explain this.",
        "rebuttals": [],
        "survived": False,
        "same_operator": True,
        "explanation": "The intake filter never opened a case, so nothing was ever frozen.",
    }

    async def infer(_ctx, _prompt, _observations):
        return dict(reply)

    return infer


async def _world(**fleet):
    """A district with its real corpus seeded, and a fleet that costs nothing to run."""
    repo = InMemoryRepository()
    state = build_state(Settings(), repo)
    await seed_all(repo, state.clock.now())
    infer = _fleet(**fleet)
    for agent in state.agents.values():
        agent.infer = infer  # type: ignore[method-assign]
    return state


# --- what Red Team is not allowed to do ---------------------------------------

async def test_redteam_may_read_the_threat_library_but_never_write_it(monkeypatch):
    """A red team that can edit the record it is testing against measures its own edits.

    The fleet ships no threat-library write TOOL today, so the test registers one for the
    duration. The claim being made is about the identity, not about which tools happen to exist:
    the day someone adds that tool, this denial is already in force.
    """
    grant = FLEET_SCOPES["redteam"]
    assert grant.permits(Scope.THREATINTEL_READ)
    assert not grant.permits(Scope.THREATINTEL_WRITE)

    monkeypatch.setitem(TOOL_SPECS, "write_threat_library", ToolSpec(
        "write_threat_library", Scope.THREATINTEL_WRITE,
        "Write an entry into the fleet's threat library.", lambda **_: {"written": True},
    ))
    state = await _world()
    ctx = AgentContext(case_id="RT-PROBE", repo=state.repo, clock=state.clock,
                       settings=state.settings, replay=state.replay,
                       telemetry=state.platform.telemetry, llm=None)

    with pytest.raises(ScopeViolation):
        await state.agents["redteam"].call_tool(ctx, "write_threat_library", entry={})

    denials = [e for e in await state.repo.list_posture_events()
               if e["kind"] == "identity_denial" and e["agent"] == "redteam"]
    assert denials, "a denial must leave a posture event; an enforcement you cannot show is one a judge assumes you did not build"
    assert denials[0]["scope"] == Scope.THREATINTEL_WRITE
    assert denials[0]["policy_id"] == "interdict-policy/redteam-v1"


async def test_redteam_cannot_open_a_real_case_or_move_money():
    """It proposes attacks. The fleet decides what happens to them, and only the fleet moves
    money — an invented attack must never be able to freeze a district's payments."""
    state = await _world()
    redteam = state.agents["redteam"]
    ctx = AgentContext(case_id="RT-PROBE", repo=state.repo, clock=state.clock,
                       settings=state.settings, replay=state.replay,
                       telemetry=state.platform.telemetry, llm=None)

    payments = await state.repo.list_payments()
    with pytest.raises(ScopeViolation):
        await redteam.call_tool(ctx, "scheduled_exposure", payments=payments[:1])
    with pytest.raises(ScopeViolation):
        await redteam.call_tool(ctx, "read_vendor_banking",
                                vendor=(await state.repo.list_vendors())[0])

    grant = FLEET_SCOPES["redteam"]
    for denied in (Scope.CASES_WRITE, Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK,
                   Scope.PAYMENTS_FREEZE):
        assert not grant.permits(denied), f"redteam must not hold {denied}"
    assert grant.permits(Scope.CASES_SIMULATE), (
        "simulating a case and opening one against real money are different permissions"
    )


# --- the blast radius of a simulated case -------------------------------------

async def test_a_simulated_case_never_appears_in_a_district_docket():
    state = await _world()
    trial = await run_variant(state, _variant())

    assert trial.simulated_case_id, "the case must have been opened for the trial to mean anything"
    district = await state.repo.list_cases(DEFAULT_TENANT_ID)
    assert trial.simulated_case_id not in [c.case_id for c in district]
    sandbox = await state.repo.list_cases(SIMULATION_TENANT_ID)
    assert [c.case_id for c in sandbox] == [trial.simulated_case_id]


async def test_a_simulated_case_never_freezes_a_district_payment():
    """Hunter sweeps the whole payment book on a block. Turned loose from a fictional case it
    would stop real money over an attack that never happened."""
    state = await _world()
    before = {p.payment_id: p.status for p in await state.repo.list_payments(
        tenant_id=DEFAULT_TENANT_ID)}

    trial = await run_variant(state, _variant())
    assert trial.outcome == "BLOCK"

    after = {p.payment_id: p.status for p in await state.repo.list_payments(
        tenant_id=DEFAULT_TENANT_ID)}
    assert after == before
    assert all(s is PaymentStatus.SCHEDULED for s in after.values())

    held = await state.repo.list_payments(tenant_id=SIMULATION_TENANT_ID)
    assert sum((p.amount for p in held), Decimal("0")) == sum(TARGET_PAYMENTS, Decimal("0"))
    assert all(p.status is PaymentStatus.BLOCKED for p in held)


async def test_a_simulated_block_never_enters_the_shared_exchange():
    """District B must never be told it was attacked by an operation that never existed."""
    state = await _world()
    trial = await run_variant(state, _variant())

    assert trial.outcome == "BLOCK"
    assert await state.platform.exchange.entries() == []
    assert await state.platform.exchange.recognitions() == []


async def test_a_simulated_block_never_writes_the_threat_library():
    """`threatintel:write` denied in the scope manifest and enforced at the port: the sandbox
    hands the pipeline a threat library it cannot write to."""
    state = await _world()
    await run_variant(state, _variant())

    assert await state.platform.recall.known_count() == 0
    assert await state.platform.recall.library() == []


# --- the arithmetic -----------------------------------------------------------

async def test_escalate_counts_as_caught_and_release_does_not():
    """Stopping the money and asking a human is the designed outcome of an ambiguous case, not a
    miss. Only a RELEASE is an escape, because only a RELEASE moves the money."""
    escalating = await _world(verdict="inconclusive", confidence=0.4, outcome="ESCALATE")
    escalated = await run_variant(escalating, _variant())
    assert escalated.outcome == "ESCALATE"
    assert escalated.caught is True

    releasing = await _world(verdict="supports", confidence=0.93, outcome="RELEASE")
    released = await run_variant(releasing, _variant())
    assert released.outcome == "RELEASE"
    assert released.caught is False

    run = RedTeamRun(run_id="RT-1", tenant_id=SIMULATION_TENANT_ID, started_at="now",
                     trials=[escalated, released])
    assert run.caught == 1
    assert run.hit_rate == 0.5


def test_hit_rate_is_zero_when_no_trials_ran():
    """A dry run generates attacks and executes none. Dividing by that is a crash, and reporting
    it as a perfect score is a lie."""
    run = RedTeamRun(run_id="RT-2", tenant_id=SIMULATION_TENANT_ID, started_at="now",
                     variants=[_variant()])
    assert run.hit_rate == 0.0
    assert run.caught == 0
    assert run.as_dict()["total"] == 0


def test_the_scoreboard_accumulates_across_runs():
    """One run saying 'caught 4 of 5' is an anecdote. The series is the measurement."""
    def trial(caught: bool) -> dict:
        return RedTeamTrial(
            variant_id="AV-1", variant_name="v", technique="t", caught=caught,
            outcome="BLOCK" if caught else "RELEASE", simulated_case_id="CASE-1",
            escaped_reason=None if caught else "a rail was loosened",
        ).as_dict()

    runs = [
        {"variants": [1, 2], "trials": [trial(True), trial(True)]},
        {"variants": [1, 2], "trials": [trial(True), trial(False)]},
        {"variants": [1], "trials": []},  # a dry run contributes a variant and no verdict
    ]
    board = _scoreboard(runs)
    assert board["trials"] == 4
    assert board["caught"] == 3
    assert board["hit_rate"] == 0.75
    assert board["variants_generated"] == 5
    assert len(board["escaped"]) == 1


# --- a miss is the valuable output --------------------------------------------

async def test_every_escape_carries_a_reason():
    """A trial with `caught=False` and no `escaped_reason` is a bug report nobody can act on."""
    state = await _world(verdict="supports", confidence=0.93, outcome="RELEASE")
    trial = await run_variant(state, _variant())

    assert trial.caught is False
    assert trial.escaped_reason
    assert "rail" in trial.escaped_reason.lower(), (
        "the reason must name the control that failed, not merely that one did"
    )


async def test_an_attack_that_never_reaches_the_fleet_is_a_miss_not_a_pass():
    """The reachable escape. Triage exists because six model calls per message is not
    affordable, which makes it the fleet's cost optimisation and its attack surface: a message
    with no payment vocabulary is filtered out for free and no case is ever opened."""
    state = await _world()
    quiet = _variant(artifact=(
        "Subject: Record refresh for our supplier file\n\n"
        "As part of a group reorganisation our receiving institution has moved. Please refresh "
        "the details we hold on file before the next disbursement run."
    ))

    trial = await run_variant(state, quiet)

    assert trial.caught is False
    assert trial.simulated_case_id == ""
    assert trial.outcome is None
    assert "triage" in trial.escaped_reason.lower()
    # Nothing was frozen, which is precisely what makes it a miss.
    sandbox = await state.repo.list_payments(tenant_id=SIMULATION_TENANT_ID)
    assert all(p.status is PaymentStatus.SCHEDULED for p in sandbox)


async def test_an_escape_is_still_reported_when_the_agent_cannot_explain_it():
    """Enrichment, never a gate. The deterministic half of the reason is written first."""
    state = await _world(verdict="supports", confidence=0.93, outcome="RELEASE")

    async def unavailable(_ctx, _prompt, _observations):
        raise RuntimeError("model unavailable")

    state.agents["redteam"].infer = unavailable  # type: ignore[method-assign]
    trial = await run_variant(state, _variant())

    assert trial.caught is False
    assert trial.escaped_reason


# --- the generated attack itself ----------------------------------------------

async def test_a_generated_attack_is_a_real_change_request_the_pipeline_can_process():
    """A red team that tests a parallel simulation proves nothing about the product."""
    state = await _world()
    trial = await run_variant(state, _variant())

    case = await state.repo.get_case(trial.simulated_case_id)
    request = await state.repo.get_request(case.request_id)
    assert request is not None
    assert request.vendor_id == case.vendor_id
    assert request.proposed_banking.account_name == "Merrivale Group Treasury"
    assert request.artifact_metadata["reply_to"] == "ap@merrivale-instructionaI.test"
    assert case.state is CaseState.BLOCKED
    assert case.exposure_amount == sum(TARGET_PAYMENTS, Decimal("0")), (
        "the case must hold real payment documents, not an asserted figure"
    )
    assert trial.top_signal, "a caught trial must name the lane that carried the verdict"


async def test_dry_run_generates_the_attacks_without_executing_any_of_them():
    """Runs are expensive: a full fan-out per variant. The capability has to be inspectable
    without spending that, and the expensive path must be the one you ask for."""
    state = await _world()
    generated = {"calls": 0}

    async def invent(_ctx, _prompt, _observations):
        generated["calls"] += 1
        return {"variants": [{
            "name": "Quiet Consolidation",
            "technique": "parent-company treasury notice",
            "novelty": "Claims a parent company the district can look up.",
            "artifact": "Subject: Remittance\n\nPlease update the bank account we are paid into.",
            "proposed_account_name": "Merrivale Group Treasury",
            "proposed_bank": "Stonebridge Commercial",
            "reply_to_domain": "merrivale-group-treasury.test",
            "supplied_phone": None,
        }]}

    state.agents["redteam"].infer = invent  # type: ignore[method-assign]

    from app.api.redteam import RunRequest, start_run

    run = await start_run(RunRequest(variants=1), state)

    assert generated["calls"] == 1, "a dry run still costs the one generation call"
    assert len(run["variants"]) == 1
    assert run["trials"] == []
    assert run["hit_rate"] == 0.0
    assert await state.repo.list_cases() == [], "a dry run must open no case"
    assert await state.repo.list_vendors(SIMULATION_TENANT_ID) == []


async def test_a_variant_with_no_claim_to_novelty_is_dropped():
    """`novelty` is the agent's own argument for why the fleet has not seen this. Without one the
    attack is not a variant, and executing it would inflate the hit rate with a rerun."""
    state = await _world()

    async def invent(_ctx, _prompt, _observations):
        return {"variants": [
            {"name": "No argument", "technique": "t", "novelty": "   ",
             "artifact": "Subject: x\n\ny", "proposed_account_name": "A",
             "proposed_bank": "B", "reply_to_domain": "a.test"},
            {"name": "Argued", "technique": "t", "novelty": "Nothing in the library does this.",
             "artifact": "Subject: x\n\ny", "proposed_account_name": "A",
             "proposed_bank": "B", "reply_to_domain": "a.test"},
        ]}

    state.agents["redteam"].infer = invent  # type: ignore[method-assign]
    ctx = state.agent_ctx_for_request(None, case_id="RT-GEN")
    variants = await state.agents["redteam"].invent(ctx, [], 2)

    assert [v.name for v in variants] == ["Argued"]


def test_a_variant_the_fleet_would_already_recognise_is_a_rerun():
    """Judged by `score_match`, the function recall actually uses. If the library would catch it
    on arrival, running it measures the library rather than the fleet."""
    library = [{
        "designation": "Phantom Charter",
        "sightings": [{"fingerprint": {
            "technique": "m->rn", "beneficiary_name": "NW Holdings Group",
            "bank_name": "Cascade Union Trust", "domain_age_bucket": "<14d",
            "supplied_own_contact": True, "channel": "email",
        }}],
    }]

    replay = _variant(proposed_account_name="NW Holdings Group",
                      proposed_bank="Cascade Union Trust")
    assert is_rerun(replay, library) is True
    assert is_rerun(_variant(), library) is False


def test_a_generated_domain_can_never_resolve():
    """The corpus rule is RFC 2606: every synthetic domain sits under .test. A generated domain
    is the one place a model could put a live one in front of an operator."""
    from app.agents.redteam import _reserved_domain, _reserved_phone

    assert _reserved_domain("merrivale-treasury.com") == "merrivale-treasury.test"
    assert _reserved_domain("merrivale-treasury.test") == "merrivale-treasury.test"
    assert _reserved_phone("+1-415-224-9931") == "+1-702-555-0199"
    assert _reserved_phone(None) is None


async def test_the_attack_is_addressed_to_the_sandbox_and_nobody_else():
    """An attacker researches their mark, so the generator is briefed on the target — but the
    target is a vendor of the simulation tenant, freshly minted per trial."""
    state = await _world()
    trial = await run_variant(state, _variant())

    case = await state.repo.get_case(trial.simulated_case_id)
    vendor = await state.repo.get_vendor(case.vendor_id)
    assert vendor.tenant_id == SIMULATION_TENANT_ID
    assert vendor.contact_email_of_record.endswith(TARGET_DOMAIN)
    assert vendor.vendor_id not in [
        v.vendor_id for v in await state.repo.list_vendors(DEFAULT_TENANT_ID)
    ]
