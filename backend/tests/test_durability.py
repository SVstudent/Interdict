"""Durability tests — the most valuable tests in the repo.

Test 1 is the one that matters: a runner that dies after a payment side effect but before its
checkpoint completes must not, on resume, release or block the money a second time.

The inherited suite had a test with this name that ran a case to completion and then called
resume(), which returned immediately because the case was already terminal. It asserted nothing.
See DECISIONS D-001 F7.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.domain import CaseState, PaymentStatus
from app.orchestrator.runner import CaseRunner
from app.services.payments import terminal_key


class Boom(Exception):
    """Stands in for process death."""


async def test_exactly_once_block_when_runner_dies_after_the_effect(
    repo, clock, payments, world, stub_agents, make_runner
):
    """Test 1. Kill the runner *after* the money has moved but *before* the checkpoint completes,
    then resume with a brand-new runner over the same persisted state."""
    case_id = world["case"].case_id

    # Adjudication finalizes payments, then the process dies before the checkpoint is written.
    original = stub_agents["adjudicate"]
    crashed = {"done": False}

    async def adjudicate_then_die(ctx, findings, challenge):
        decision = await original(ctx, findings, challenge)
        ctx.case.decision = decision
        await payments.finalize(ctx.case, decision.outcome)  # the money moves
        if not crashed["done"]:
            crashed["done"] = True
            raise Boom("process died after the effect, before the checkpoint")
        return decision

    stub_agents["adjudicate"] = adjudicate_then_die
    runner = make_runner(stub_agents)

    with pytest.raises(Boom):
        await runner.advance(case_id, {"callback_response": "denied"})

    effects_after_crash = await repo.list_effects(case_id)
    assert terminal_key(case_id, "BLOCK") in {e.idempotency_key for e in effects_after_crash}

    # A completely fresh runner, as if the container had restarted.
    resumed: CaseRunner = make_runner(stub_agents)
    report = await resumed.advance(case_id, {"callback_response": "denied"})

    case = await repo.get_case(case_id)
    assert case.state is CaseState.BLOCKED

    block_effects = [
        e for e in await repo.list_effects(case_id) if e.action == "BLOCK"
    ]
    assert len(block_effects) == 1, f"expected exactly one BLOCK effect, got {len(block_effects)}"

    # And the earlier steps were not redone.
    assert "hold_payments" in report.skipped
    assert "fanout_verification" in report.skipped
    assert "adversarial_challenge" in report.skipped


async def test_crash_mid_fanout_does_not_re_execute_the_hold(
    repo, clock, payments, world, stub_agents, make_runner
):
    """Beat 6. Die during the fan-out; the hold must not run twice and exposure must not double."""
    case_id = world["case"].case_id
    original = stub_agents["fanout"]
    first = {"seen": False}

    async def fanout_then_die(ctx):
        if not first["seen"]:
            first["seen"] = True
            raise Boom("killed mid fan-out")
        return await original(ctx)

    stub_agents["fanout"] = fanout_then_die
    with pytest.raises(Boom):
        await make_runner(stub_agents).advance(case_id, {"callback_response": "denied"})

    case = await repo.get_case(case_id)
    assert case.exposure_amount == Decimal("340000.00")
    hold_effects = [e for e in await repo.list_effects(case_id) if e.action == "HOLD"]
    assert len(hold_effects) == 1

    report = await make_runner(stub_agents).advance(case_id, {"callback_response": "denied"})

    assert "hold_payments" in report.skipped, "the hold was re-executed after resume"
    assert "fanout_verification" in report.executed, "the interrupted fan-out did not re-run"
    case = await repo.get_case(case_id)
    assert case.state is CaseState.BLOCKED
    assert case.exposure_amount == Decimal("340000.00")
    assert len([e for e in await repo.list_effects(case_id) if e.action == "HOLD"]) == 1


async def test_double_finalize_with_same_key_produces_one_effect(
    repo, clock, payments, world
):
    """Test 2. Direct assault on the effects ledger, independent of the runner."""
    case = world["case"]
    await payments.hold_scheduled_payments(case, case.vendor_id)

    first = await payments.finalize(case, "RELEASE")
    second = await payments.finalize(case, "RELEASE")

    assert first.replayed is False
    assert second.replayed is True
    assert second.total == first.total
    assert len([e for e in await repo.list_effects(case.case_id) if e.action == "RELEASE"]) == 1
    assert all(
        p.status is PaymentStatus.RELEASED for p in await repo.list_payments(case.vendor_id)
    )


async def test_resume_all_picks_up_non_terminal_cases(
    repo, clock, payments, world, stub_agents, make_runner
):
    """Startup recovery: a dormant case is resumable, a finished one is left alone."""
    case_id = world["case"].case_id
    report = await make_runner(stub_agents).advance(case_id)  # no callback -> dormant
    assert report.suspended is True
    assert (await repo.get_case(case_id)).state is CaseState.AWAITING_CALLBACK

    reports = await make_runner(stub_agents).resume_all()
    assert [r.case_id for r in reports] == [case_id]

    # Once terminal it is no longer resumable.
    await make_runner(stub_agents).advance(case_id, {"callback_response": "denied"})
    assert (await repo.get_case(case_id)).state is CaseState.BLOCKED
    assert await make_runner(stub_agents).resume_all() == []
