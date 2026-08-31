"""Hunter — the proactive exposure sweep.

Hunter is the only agent that acts on payments nobody complained about, so its LIMITS matter more
than its reach. These tests pin the blast radius: it can interrupt, it cannot conclude.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.agents.hunter import HunterAgent
from app.agents.scopes import FLEET_SCOPES, Scope, ScopeViolation
from app.config import DEMO_EPOCH, FrozenClock, Settings
from app.models.domain import PaymentStatus
from app.seed.generate import seed_all
from app.services.payments import PaymentService
from app.store.memory import InMemoryRepository


def test_hunter_can_freeze_but_never_release_or_block():
    """A proactive agent gets the narrowest power that still removes the friction. Every hold it
    places still goes through the full fleet before anything is concluded."""
    grant = FLEET_SCOPES["hunter"]
    assert grant.permits(Scope.PAYMENTS_FREEZE)
    assert grant.permits(Scope.PAYMENTS_SCAN)
    assert not grant.permits(Scope.PAYMENTS_RELEASE)
    assert not grant.permits(Scope.PAYMENTS_BLOCK)
    assert not grant.permits(Scope.ERP_WRITE)
    assert not grant.permits(Scope.THREATINTEL_WRITE), (
        "Hunter reads the threat library; only Scribe writes it"
    )


async def test_hunter_cannot_read_banking_details():
    """It selects targets from amounts, tenure and timing — never from the account data."""
    from app.agents.base import AgentContext

    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    hunter = HunterAgent(Settings())
    ctx = AgentContext(case_id="C1", repo=repo, clock=clock, settings=Settings(),
                       replay=None, telemetry=None, llm=None)
    vendor = await repo.get_vendor("V-9001")
    with pytest.raises(ScopeViolation):
        await hunter.call_tool(ctx, "read_vendor_banking", vendor=vendor)


# --- the freeze itself --------------------------------------------------------

async def test_proactive_freeze_holds_scheduled_payments():
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    svc = PaymentService(repo, clock)

    scheduled = [p for p in await repo.list_payments()
                 if p.status is PaymentStatus.SCHEDULED][:3]
    ids = [p.payment_id for p in scheduled]
    expected = sum((p.amount for p in scheduled), Decimal("0"))

    result = await svc.freeze_proactively(ids, "CASE-ORIGIN", "Phantom Charter")
    assert result.replayed is False
    assert set(result.payment_ids) == set(ids)
    assert result.total == expected
    for pid in ids:
        p = await repo.get_payment(pid)
        assert p.status is PaymentStatus.HELD
        assert p.held_by_case_id == "CASE-ORIGIN"


async def test_proactive_freeze_is_idempotent():
    """A re-run of the sweep must not double-count exposure or re-freeze."""
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    svc = PaymentService(repo, clock)
    ids = [p.payment_id for p in await repo.list_payments()
           if p.status is PaymentStatus.SCHEDULED][:2]

    first = await svc.freeze_proactively(ids, "CASE-ORIGIN", "Phantom Charter")
    second = await svc.freeze_proactively(ids, "CASE-ORIGIN", "Phantom Charter")
    assert first.replayed is False
    assert second.replayed is True
    assert second.total == first.total
    effects = [e for e in await repo.list_effects("CASE-ORIGIN") if e.action == "SWEEP_FREEZE"]
    assert len(effects) == 1


async def test_proactive_freeze_never_reopens_a_settled_payment():
    """Freezing a released or blocked payment would rewrite a concluded decision."""
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    svc = PaymentService(repo, clock)

    target = next(p for p in await repo.list_payments() if p.status is PaymentStatus.SCHEDULED)
    target.status = PaymentStatus.RELEASED
    await repo.save_payment(target)

    result = await svc.freeze_proactively([target.payment_id], "CASE-ORIGIN", "Phantom Charter")
    assert result.payment_ids == []
    assert (await repo.get_payment(target.payment_id)).status is PaymentStatus.RELEASED


# --- guarding against a bad generation ---------------------------------------

async def test_hunter_drops_payments_the_model_invented():
    """The model returning an ID that is not in the book must never freeze anything. This is the
    one agent whose hallucination would stop money nobody asked it to touch."""
    from app.agents.base import AgentContext

    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    hunter = HunterAgent(Settings())

    real = next(p for p in await repo.list_payments() if p.status is PaymentStatus.SCHEDULED)

    async def fake_infer(_ctx, _prompt, _obs):
        return {
            "targets": [
                {"payment_id": real.payment_id, "reason": "matches indicator", "risk": "high"},
                {"payment_id": "PAY-DOES-NOT-EXIST", "reason": "invented", "risk": "high"},
            ],
            "reasoning": "test",
            "swept_but_cleared": [],
        }

    hunter.infer = fake_infer  # type: ignore[method-assign]
    ctx = AgentContext(case_id="C1", repo=repo, clock=clock, settings=Settings(),
                       replay=None, telemetry=None, llm=None)
    result = await hunter.sweep(ctx, {"designation": "Phantom Charter"}, "CASE-ORIGIN", set())

    ids = [t.payment_id for t in result.targets]
    assert real.payment_id in ids
    assert "PAY-DOES-NOT-EXIST" not in ids


async def test_hunter_excludes_the_vendor_already_interdicted():
    """Their payments are already held by the originating case; re-freezing double-counts."""
    from app.agents.base import AgentContext

    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    hunter = HunterAgent(Settings())
    seen: dict[str, object] = {}

    async def capture(_ctx, _prompt, obs):
        seen["payments"] = obs["scheduled_payments"]
        return {"targets": [], "reasoning": "none", "swept_but_cleared": []}

    hunter.infer = capture  # type: ignore[method-assign]
    ctx = AgentContext(case_id="C1", repo=repo, clock=clock, settings=Settings(),
                       replay=None, telemetry=None, llm=None)
    await hunter.sweep(ctx, {"designation": "X"}, "CASE-ORIGIN", {"V-9001"})

    offered = {p["vendor_id"] for p in seen["payments"]}  # type: ignore[index]
    assert "V-9001" not in offered


async def test_an_empty_sweep_is_a_valid_outcome():
    """A sweep that freezes nothing is far better than one that freezes everything. A vendor who
    is not paid on time is a real cost the business office unwinds by hand."""
    from app.agents.base import AgentContext

    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    await seed_all(repo, clock.now())
    hunter = HunterAgent(Settings())

    async def nothing(_ctx, _prompt, _obs):
        return {"targets": [], "reasoning": "The dossier gives nothing actionable.",
                "swept_but_cleared": []}

    hunter.infer = nothing  # type: ignore[method-assign]
    ctx = AgentContext(case_id="C1", repo=repo, clock=clock, settings=Settings(),
                       replay=None, telemetry=None, llm=None)
    result = await hunter.sweep(ctx, {"designation": "X"}, "CASE-ORIGIN", set())
    assert result.targets == []
    assert result.frozen_total == Decimal("0")
