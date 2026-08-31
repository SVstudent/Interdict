from __future__ import annotations

import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DEMO_EPOCH, FrozenClock  # noqa: E402
from app.models.domain import (  # noqa: E402
    BankingDetails,
    Case,
    ChallengeResult,
    ChangeRequest,
    Decision,
    EvidenceRef,
    Finding,
    Payment,
    Rebuttal,
    Vendor,
)
from app.orchestrator.pipeline import build_pipeline  # noqa: E402
from app.orchestrator.runner import CaseRunner, StepContext  # noqa: E402
from app.services.payments import PaymentService  # noqa: E402
from app.store.memory import InMemoryRepository  # noqa: E402


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(DEMO_EPOCH)


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def payments(repo, clock) -> PaymentService:
    return PaymentService(repo, clock)


def banking(name: str = "Northwind Components LLC", last4: str = "4417", country: str = "US"):
    return BankingDetails(
        account_name=name,
        account_last4=last4,
        routing_last4="0021",
        bank_name="First Meridian Bank",
        bank_country=country,
        effective_from=DEMO_EPOCH - timedelta(days=900),
    )


@pytest.fixture
async def world(repo, clock):
    """A vendor with two scheduled payments totalling $340,000 — the S1 exposure figure,
    derived by summing real payment documents rather than asserted as a literal."""
    vendor = Vendor(
        vendor_id="V-NORTHWIND",
        legal_name="Northwind Components LLC",
        onboarded_at=DEMO_EPOCH - timedelta(days=6 * 365),
        contact_email_of_record="ap@northwind-components.com",
        contact_phone_of_record="+1-503-555-0142",
        banking=banking(),
        total_paid_lifetime=Decimal("4820000.00"),
        invoice_count=212,
        operating_country="US",
    )
    await repo.save_vendor(vendor)
    for i, amt in enumerate(("150000.00", "190000.00")):
        await repo.save_payment(
            Payment(
                payment_id=f"PAY-88{i}",
                vendor_id=vendor.vendor_id,
                invoice_id="INV-4471",
                amount=Decimal(amt),
                scheduled_for=DEMO_EPOCH + timedelta(days=2),
            )
        )
    request = ChangeRequest(
        request_id="REQ-1001",
        vendor_id=vendor.vendor_id,
        channel="email",
        received_at=DEMO_EPOCH,
        raw_artifact="Please update our remittance details for invoice INV-4471.",
        artifact_metadata={"reply_to": "ap@northwind-cornponents.com",
                           "supplied_phone": "+1-702-555-0199"},
        proposed_banking=banking("NW Holdings Group", "9930"),
        claimed_reason="Treasury consolidation",
    )
    await repo.save_request(request)
    case = Case(
        case_id="CASE-A1B2C3",
        request_id=request.request_id,
        vendor_id=vendor.vendor_id,
        exposure_amount=Decimal("0"),
        opened_at=clock.now(),
        deadline_at=clock.now() + timedelta(days=7),
    )
    await repo.save_case(case)
    return {"vendor": vendor, "request": request, "case": case}


def make_finding(agent: str, verdict: str, confidence: float, fid: str | None = None) -> Finding:
    return Finding(
        finding_id=fid or f"F-{agent}",
        agent=agent,
        agent_version="1.0.0",
        signal=f"{agent}_signal",
        verdict=verdict,
        confidence=confidence,
        evidence=[
            EvidenceRef(source="test", locator=agent, excerpt="observed value")
        ]
        if verdict != "inconclusive"
        else [],
        reasoning=f"{agent} reasoning",
    )


@pytest.fixture
def stub_agents(clock):
    """Deterministic stand-ins for the Phase 2 fleet. They exercise the state machine without
    any model call, which is what Phase 1 is meant to prove out."""

    calls: dict[str, int] = {"fanout": 0, "challenge": 0, "adjudicate": 0}

    async def fanout(ctx: StepContext):
        calls["fanout"] += 1
        cb = ctx.payload.get("callback_response")
        return [
            make_finding("provenance", "contradicts", 0.94),
            make_finding("ledger", "contradicts", 0.88),
            make_finding("registry-check", "contradicts", 0.91),
            make_finding(
                "callback",
                "contradicts" if cb == "denied"
                else ("supports" if cb == "confirmed" else "inconclusive"),
                0.97 if cb else 0.0,
            ),
        ]

    async def challenge(ctx: StepContext, findings):
        calls["challenge"] += 1
        return ChallengeResult(
            strongest_legitimate_explanation="Treasury consolidation after a bank merger.",
            rebuttals=[
                Rebuttal(finding_id=f.finding_id, argument="considered", succeeds=False)
                for f in findings
            ],
            survived=False,
            reasoning="No rebuttal survives the lookalike domain and the name mismatch.",
        )

    async def adjudicate(ctx: StepContext, findings, challenge_result):
        calls["adjudicate"] += 1
        return Decision(
            outcome="BLOCK",
            confidence=0.97,
            rationale="Three unrebutted high-confidence contradictions.",
            decided_at=ctx.clock.now(),
        )

    return {"fanout": fanout, "challenge": challenge, "adjudicate": adjudicate, "calls": calls}


@pytest.fixture
def make_runner(repo, clock, payments):
    def _make(stub_agents, events: list | None = None):
        async def emit(event: str, data: dict) -> None:
            if events is not None:
                events.append((event, data))

        return CaseRunner(
            repo=repo,
            clock=clock,
            steps=build_pipeline(
                payments,
                stub_agents["fanout"],
                stub_agents["challenge"],
                stub_agents["adjudicate"],
            ),
            emit=emit,
        )

    return _make
