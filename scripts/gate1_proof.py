"""Gate 1 proof: kill a runner mid-flight, resume it, show nothing was re-executed.

Run: ./.venv/bin/python scripts/gate1_proof.py
"""
from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import DEMO_EPOCH, FrozenClock
from app.models.domain import (
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
from app.orchestrator.pipeline import build_pipeline
from app.orchestrator.runner import CaseRunner
from app.services.payments import PaymentService
from app.store.memory import InMemoryRepository


class Killed(Exception):
    """Stands in for the container dying."""


def bank(name, last4):
    return BankingDetails(account_name=name, account_last4=last4, routing_last4="0021",
                          bank_name="First Meridian Bank", bank_country="US",
                          effective_from=DEMO_EPOCH - timedelta(days=900))


def finding(agent, verdict, conf):
    return Finding(finding_id=f"F-{agent}", agent=agent, agent_version="1.0.0",
                   signal=f"{agent}_signal", verdict=verdict, confidence=conf,
                   evidence=[EvidenceRef(source="fixture", locator=agent, excerpt="observed")],
                   reasoning=f"{agent} reasoning")


async def main() -> int:
    repo, clock = InMemoryRepository(), FrozenClock(DEMO_EPOCH)
    pay = PaymentService(repo, clock)

    await repo.save_vendor(Vendor(
        vendor_id="V-NORTHWIND", legal_name="Northwind Components LLC",
        onboarded_at=DEMO_EPOCH - timedelta(days=6 * 365),
        contact_email_of_record="ap@northwind-components.com",
        contact_phone_of_record="+1-503-555-0142", banking=bank("Northwind Components LLC", "4417"),
        total_paid_lifetime=Decimal("4820000.00"), invoice_count=212, operating_country="US"))
    for i, amt in enumerate(("150000.00", "190000.00")):
        await repo.save_payment(Payment(payment_id=f"PAY-88{i}", vendor_id="V-NORTHWIND",
                                        invoice_id="INV-4471", amount=Decimal(amt),
                                        scheduled_for=DEMO_EPOCH + timedelta(days=2)))
    await repo.save_request(ChangeRequest(
        request_id="REQ-1001", vendor_id="V-NORTHWIND", channel="email", received_at=DEMO_EPOCH,
        raw_artifact="Please update our remittance details for invoice INV-4471.",
        artifact_metadata={"reply_to": "ap@northwind-cornponents.com"},
        proposed_banking=bank("NW Holdings Group", "9930"),
        claimed_reason="Treasury consolidation"))
    await repo.save_case(Case(case_id="CASE-A1B2C3", request_id="REQ-1001", vendor_id="V-NORTHWIND",
                              exposure_amount=Decimal("0"), opened_at=clock.now(),
                              deadline_at=clock.now() + timedelta(days=7)))

    die = {"armed": True}

    async def fanout(ctx):
        if die["armed"]:
            die["armed"] = False
            raise Killed("SIGKILL during fan-out")
        return [finding("provenance", "contradicts", 0.94), finding("ledger", "contradicts", 0.88),
                finding("registry-check", "contradicts", 0.91),
                finding("callback", "contradicts", 0.97)]

    async def challenge(ctx, findings):
        return ChallengeResult(
            strongest_legitimate_explanation="Treasury consolidation following a bank merger.",
            rebuttals=[
                Rebuttal(finding_id=f.finding_id, argument="considered", succeeds=False)
                for f in findings
            ],
            survived=False, reasoning="No rebuttal survives the lookalike domain.")

    async def adjudicate(ctx, findings, ch):
        return Decision(outcome="BLOCK", confidence=0.97,
                        rationale="Three unrebutted high-confidence contradictions.",
                        decided_at=ctx.clock.now())

    def runner():
        return CaseRunner(repo, clock, build_pipeline(pay, fanout, challenge, adjudicate))

    print("=" * 74)
    print("GATE 1 PROOF — durable case runner, kill and resume")
    print("=" * 74)

    print("\n[1] Start the case. The runner is killed mid fan-out.")
    try:
        await runner().advance("CASE-A1B2C3", {"callback_response": "denied"})
        print("    !! expected a crash and did not get one")
        return 1
    except Killed as exc:
        print(f"    runner died: {exc}")

    case = await repo.get_case("CASE-A1B2C3")
    print(f"    persisted state : {case.state.value}")
    print(f"    exposure        : ${case.exposure_amount}  "
          f"(sum of {len(case.held_payment_ids)} held payments)")
    print("\n    checkpoint log after the crash:")
    for cp in await repo.list_checkpoints("CASE-A1B2C3"):
        print(f"      seq {cp.seq}  {cp.step:<24} {cp.status.value:<10} attempt {cp.attempt}")
    print("\n    effects ledger after the crash:")
    for e in await repo.list_effects("CASE-A1B2C3"):
        print(f"      {e.idempotency_key:<28} {e.action:<8} {e.result}")

    print("\n[2] A brand-new runner resumes from persisted state (as after a restart).")
    report = await runner().advance("CASE-A1B2C3", {"callback_response": "denied"})
    print(f"    skipped  : {report.skipped}")
    print(f"    executed : {report.executed}")
    print(f"    final    : {report.final_state.value}")

    print("\n    checkpoint log after resume:")
    for cp in await repo.list_checkpoints("CASE-A1B2C3"):
        print(f"      seq {cp.seq}  {cp.step:<24} {cp.status.value:<10} attempt {cp.attempt}")

    print("\n[3] Assertions")
    case = await repo.get_case("CASE-A1B2C3")
    holds = [e for e in await repo.list_effects("CASE-A1B2C3") if e.action == "HOLD"]
    blocks = [e for e in await repo.list_effects("CASE-A1B2C3") if e.action == "BLOCK"]
    checks = [
        ("case reached BLOCKED", case.state.value == "blocked"),
        ("hold not re-executed (reported skipped)", "hold_payments" in report.skipped),
        ("exactly one HOLD effect", len(holds) == 1),
        ("exactly one BLOCK effect", len(blocks) == 1),
        ("exposure still $340,000.00", case.exposure_amount == Decimal("340000.00")),
        ("interrupted fan-out did re-run", "fanout_verification" in report.executed),
    ]
    ok = True
    for label, passed in checks:
        print(f"    [{'PASS' if passed else 'FAIL'}] {label}")
        ok &= passed
    print("\n" + "=" * 74)
    print("GATE 1 PROOF: " + ("PASS" if ok else "FAIL"))
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
