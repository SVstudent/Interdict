"""Domain invariants. These are the rails that stop a bad generation from moving money."""
from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.domain import (
    LEGAL_TRANSITIONS,
    Case,
    CaseState,
    EvidenceRef,
    Finding,
    IllegalTransition,
    assert_transition,
)

# --- Test 3: state machine ---------------------------------------------------------

def _all_pairs():
    return [(a, b) for a in CaseState for b in CaseState if a != b]


def test_every_legal_transition_is_accepted():
    for src, targets in LEGAL_TRANSITIONS.items():
        for dst in targets:
            assert_transition("CASE-X", src, dst)  # must not raise


def test_every_illegal_transition_raises():
    illegal = [
        (a, b) for a, b in _all_pairs() if b not in LEGAL_TRANSITIONS[a]
    ]
    assert illegal, "sanity: there must be illegal transitions to test"
    for src, dst in illegal:
        with pytest.raises(IllegalTransition):
            assert_transition("CASE-X", src, dst)


@pytest.mark.parametrize("terminal", sorted(s.value for s in (
    CaseState.RELEASED, CaseState.BLOCKED, CaseState.ESCALATED)))
def test_terminal_states_have_no_exits(terminal):
    assert LEGAL_TRANSITIONS[CaseState(terminal)] == frozenset()


def test_the_dangerous_shortcut_is_illegal():
    """A held case must never jump straight to released without verification."""
    with pytest.raises(IllegalTransition):
        assert_transition("CASE-X", CaseState.HELD, CaseState.RELEASED)


# --- Test 4: findings must cite evidence -------------------------------------------

@pytest.mark.parametrize("verdict", ["supports", "contradicts"])
def test_committed_verdict_without_evidence_is_rejected(verdict):
    with pytest.raises(ValidationError):
        Finding(
            finding_id="F1",
            agent="provenance",
            agent_version="1.1.0",
            signal="domain_age",
            verdict=verdict,
            confidence=0.99,
            evidence=[],
            reasoning="trust me",
        )


def test_inconclusive_may_cite_nothing():
    f = Finding(
        finding_id="F1",
        agent="callback",
        agent_version="1.2.1",
        signal="callback_unanswered",
        verdict="inconclusive",
        confidence=0.0,
        evidence=[],
        reasoning="No answer on the number of record.",
    )
    assert f.is_committed is False


def test_evidence_excerpt_must_not_be_empty():
    """An EvidenceRef whose excerpt is blank cites nothing — it is a citation-shaped hole."""
    with pytest.raises(ValidationError):
        EvidenceRef(source="email_headers", locator="Reply-To", excerpt="")


# --- Test 13: exposure equals the sum of held payments -----------------------------

async def test_exposure_matches_sum_of_held_payments(repo, payments, world):
    case = world["case"]
    await payments.hold_scheduled_payments(case, case.vendor_id)
    assert case.exposure_amount == Decimal("340000.00")
    case.assert_exposure_matches(await repo.get_payments(case.held_payment_ids))


async def test_exposure_mismatch_is_detected(repo, payments, world):
    case = world["case"]
    await payments.hold_scheduled_payments(case, case.vendor_id)
    case.exposure_amount = Decimal("1.00")  # tamper
    with pytest.raises(ValueError, match="exposure"):
        case.assert_exposure_matches(await repo.get_payments(case.held_payment_ids))


async def test_holding_no_payments_yields_zero_exposure(repo, payments, world, clock):
    from datetime import timedelta

    case = Case(
        case_id="CASE-EMPTY",
        request_id="REQ-1001",
        vendor_id="V-UNKNOWN",
        exposure_amount=Decimal("0"),
        opened_at=clock.now(),
        deadline_at=clock.now() + timedelta(days=7),
    )
    await repo.save_case(case)
    result = await payments.hold_scheduled_payments(case, "V-UNKNOWN")
    assert result.payment_ids == []
    assert case.exposure_amount == Decimal("0")
