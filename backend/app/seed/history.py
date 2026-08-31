"""Historical case file.

Cases the fleet adjudicated before this session. Every deployed system has a case history, and
without one the Docket and Ledger open empty on camera.

These are **seeded corpus, not live agent output**. They are written directly to the store with
their findings and decisions already attached; nothing here claims to have just been reasoned.
A new case injected from the demo control plane runs through the real fleet.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ..audit.nacha import AuditChain
from ..config import Clock
from ..models.domain import (
    Case,
    CaseState,
    ChallengeResult,
    ChangeRequest,
    Decision,
    EvidenceRef,
    Finding,
    Payment,
    PaymentStatus,
    Rebuttal,
)
from ..store.base import Repository
from .generate import _banking  # noqa: F401  (kept for signature parity)
from .scenarios import _banking as scenario_banking


def _finding(agent: str, version: str, signal: str, verdict: str, conf: float,
             reasoning: str, evidence: list[tuple[str, str, str]], latency: int) -> Finding:
    return Finding(
        finding_id=f"F-{agent}-{signal[:6]}",
        agent=agent, agent_version=version, signal=signal, verdict=verdict,
        confidence=conf, reasoning=reasoning, latency_ms=latency,
        evidence=[EvidenceRef(source=src, locator=loc, excerpt=x) for src, loc, x in evidence],
    )


async def seed_history(repo: Repository, clock: Clock) -> int:
    now = clock.now()
    chain = AuditChain(repo, clock)
    written = 0

    # --- 1. A blocked case: lookalike domain, entity mismatch, vendor denied -------
    opened = now - timedelta(days=9)
    vendor_id = "V-0007"
    vendor = await repo.get_vendor(vendor_id)
    if vendor is None:
        return 0

    for pid, amount in (("PAY-7001", "84000.00"), ("PAY-7002", "61500.00")):
        await repo.save_payment(Payment(
            payment_id=pid, vendor_id=vendor_id, invoice_id="INV-4032",
            amount=Decimal(amount), scheduled_for=opened + timedelta(days=3),
            status=PaymentStatus.BLOCKED, held_by_case_id="CASE-7F2A10",
        ))

    await repo.save_request(ChangeRequest(
        request_id="REQ-HIST-01", vendor_id=vendor_id, channel="email",
        received_at=opened,
        raw_artifact="Please redirect remittance for INV-4032 to our new banking partner.",
        artifact_metadata={"from": f"billing@{vendor.contact_email_of_record.split('@')[-1]}",
                           "reply_to": "billing@nnorthwind-supply.test",
                           "referenced_invoice": "INV-4032"},
        proposed_banking=scenario_banking("Atlas Receivables Group", "8820", "4410",
                                          "Granite Fidelity", opened),
        claimed_reason="New banking partner",
    ))

    blocked = Case(
        case_id="CASE-7F2A10", request_id="REQ-HIST-01", vendor_id=vendor_id,
        state=CaseState.BLOCKED, exposure_amount=Decimal("145500.00"),
        held_payment_ids=["PAY-7001", "PAY-7002"],
        opened_at=opened, deadline_at=opened + timedelta(days=7),
        session_id="sess-9c1d4e77a02b",
        findings=[
            _finding("provenance", "1.1.0", "lookalike_reply_to_domain", "contradicts", 0.93,
                     "The reply-to address sits on a domain registered eight days before the "
                     "request and differing from the vendor domain by one doubled character.",
                     [("email_headers", "Reply-To", "billing@nnorthwind-supply.test"),
                      ("whois", "nnorthwind-supply.test", "registered 8 days ago")], 2140),
            _finding("registry-check", "1.0.2", "account_holder_name_mismatch", "contradicts", 0.91,
                     "The proposed beneficiary does not correspond to the registered legal "
                     "entity and no factoring relationship is recorded.",
                     [("entity_registry", vendor.legal_name,
                       f"proposed 'Atlas Receivables Group' vs registered '{vendor.legal_name}'")], 1890),
            _finding("ledger", "1.3.0", "relationship_baseline", "inconclusive", 0.42,
                     "The cited invoice is genuinely open, which is consistent with both a real "
                     "request and an attacker working from a stolen invoice.",
                     [], 1310),
            _finding("callback", "1.2.1", "out_of_band_confirmation", "contradicts", 0.97,
                     "The vendor's accounts receivable lead, reached on the number of record, "
                     "confirmed no change had been requested.",
                     [("vendor_master", "contact_phone_of_record", vendor.contact_phone_of_record),
                      ("callback_log", vendor.contact_phone_of_record,
                       "vendor denied the change on the number of record")], 3420),
        ],
        challenge=ChallengeResult(
            strongest_legitimate_explanation=(
                "Mid-market suppliers do sell receivables. If this vendor had entered a "
                "factoring arrangement, remittance would legitimately move to the factor's "
                "account under a different name, and the reply-to could plausibly belong to "
                "the factor's billing desk."
            ),
            rebuttals=[
                Rebuttal(finding_id="F-provenance-lookal",
                         argument="A factor's domain would predate the arrangement; eight days "
                                  "does not survive contact with the timeline.", succeeds=False),
                Rebuttal(finding_id="F-registry-account",
                         argument="A factoring assignment would appear in the vendor master as "
                                  "an assignment of proceeds. None is recorded.", succeeds=False),
                Rebuttal(finding_id="F-callback-out_of",
                         argument="Cannot be rebutted. The vendor denied the request on the "
                                  "number held in the system of record.", succeeds=False),
            ],
            survived=False,
            reasoning="The factoring reading is coherent but cannot survive the domain age or "
                      "the vendor's own denial.",
        ),
        decision=Decision(
            outcome="BLOCK", confidence=0.97,
            rationale="Three unrebutted contradictions, including a direct denial from the "
                      "vendor on the contact number of record. Payments remain with the "
                      "originator pending vendor re-verification.",
            dissenting_findings=["relationship_baseline"],
            decided_at=opened + timedelta(hours=2), decided_by="fleet",
        ),
    )
    await repo.save_case(blocked)
    await chain.emit(blocked, blocked.decision)
    written += 1

    # --- 2. An escalated case: plausible, but nobody could confirm it --------------
    opened2 = now - timedelta(days=4)
    vendor2_id = "V-0019"
    vendor2 = await repo.get_vendor(vendor2_id)
    if vendor2:
        await repo.save_payment(Payment(
            payment_id="PAY-7010", vendor_id=vendor2_id, invoice_id="INV-4102",
            amount=Decimal("268000.00"), scheduled_for=opened2 + timedelta(days=5),
            status=PaymentStatus.HELD, held_by_case_id="CASE-3B84C2",
        ))
        await repo.save_request(ChangeRequest(
            request_id="REQ-HIST-02", vendor_id=vendor2_id, channel="portal",
            received_at=opened2,
            raw_artifact="Banking update submitted through the supplier portal following "
                         "group restructuring.",
            artifact_metadata={"from": f"treasury@{vendor2.contact_email_of_record.split('@')[-1]}",
                               "reply_to": f"treasury@{vendor2.contact_email_of_record.split('@')[-1]}",
                               "referenced_invoice": "INV-4102"},
            proposed_banking=scenario_banking(vendor2.legal_name, "6612", "9903",
                                              "Lakeshore National", opened2),
            claimed_reason="Group restructuring",
        ))
        escalated = Case(
            case_id="CASE-3B84C2", request_id="REQ-HIST-02", vendor_id=vendor2_id,
            state=CaseState.ESCALATED, exposure_amount=Decimal("268000.00"),
            held_payment_ids=["PAY-7010"],
            opened_at=opened2, deadline_at=opened2 + timedelta(days=7),
            session_id="sess-41ba07d3e918",
            findings=[
                _finding("provenance", "1.1.0", "artifact_forensics", "supports", 0.88,
                         "Submitted through the authenticated supplier portal from the domain "
                         "of record. No header or metadata anomalies.",
                         [("portal_audit", "submission", "authenticated session, domain of record")], 1620),
                _finding("registry-check", "1.0.2", "entity_attestation", "supports", 0.81,
                         "The account is held in the vendor's registered legal name and the "
                         "bank operates in the vendor's jurisdiction.",
                         [("entity_registry", vendor2.legal_name,
                           f"account holder matches '{vendor2.legal_name}'")], 1450),
                _finding("callback", "1.2.1", "out_of_band_confirmation", "inconclusive", 0.0,
                         "Three attempts on the number of record over two business days. No "
                         "answer and no returned call. Silence is not confirmation.",
                         [], 4100),
            ],
            challenge=ChallengeResult(
                strongest_legitimate_explanation=(
                    "Group restructuring genuinely moves receiving accounts, and everything "
                    "observable here is consistent with a real change: authenticated channel, "
                    "correct legal entity, domestic bank."
                ),
                rebuttals=[
                    Rebuttal(finding_id="F-callback-out_of",
                             argument="An unanswered phone proves nothing either way; it is "
                                      "absence of evidence, not evidence of fraud.", succeeds=True),
                ],
                survived=True,
                reasoning="The legitimate reading is at least as plausible as the fraud reading. "
                          "Nothing contradicts it — but nothing independently confirms it either.",
            ),
            decision=Decision(
                outcome="ESCALATE", confidence=0.74,
                rationale="No contradicting evidence, and the adversarial review survived. But "
                          "$268,000 exceeds the auto-release ceiling and the out-of-band "
                          "callback is unresolved. A human authorises this one.\n\n"
                          "Safety rail applied: $268,000 exceeds the $250,000 auto-release "
                          "ceiling. A human authorises this one.",
                dissenting_findings=[],
                decided_at=opened2 + timedelta(hours=51), decided_by="fleet",
            ),
        )
        await repo.save_case(escalated)
        await chain.emit(escalated, escalated.decision)
        written += 1

    # --- 3. A released case: verified, and let through -----------------------------
    opened3 = now - timedelta(days=16)
    vendor3_id = "V-0028"
    vendor3 = await repo.get_vendor(vendor3_id)
    if vendor3:
        await repo.save_payment(Payment(
            payment_id="PAY-7020", vendor_id=vendor3_id, invoice_id="INV-4140",
            amount=Decimal("47250.00"), scheduled_for=opened3 + timedelta(days=4),
            status=PaymentStatus.RELEASED, held_by_case_id="CASE-15D9E4",
        ))
        await repo.save_request(ChangeRequest(
            request_id="REQ-HIST-03", vendor_id=vendor3_id, channel="email",
            received_at=opened3,
            raw_artifact="Our bank has migrated us to a new sort code following its merger.",
            artifact_metadata={"from": f"ap@{vendor3.contact_email_of_record.split('@')[-1]}",
                               "reply_to": f"ap@{vendor3.contact_email_of_record.split('@')[-1]}",
                               "referenced_invoice": "INV-4140"},
            proposed_banking=scenario_banking(vendor3.legal_name, "3390", "7001",
                                              "Stonebridge Commercial", opened3),
            claimed_reason="Bank merger migration",
        ))
        released = Case(
            case_id="CASE-15D9E4", request_id="REQ-HIST-03", vendor_id=vendor3_id,
            state=CaseState.RELEASED, exposure_amount=Decimal("47250.00"),
            held_payment_ids=["PAY-7020"],
            opened_at=opened3, deadline_at=opened3 + timedelta(days=7),
            session_id="sess-77e2c0b41d55",
            findings=[
                _finding("provenance", "1.1.0", "artifact_forensics", "supports", 0.9,
                         "Sent from the domain of record with no reply-to divergence and a "
                         "document producer matching prior invoices.",
                         [("email_headers", "From", f"ap@{vendor3.contact_email_of_record.split('@')[-1]}")], 1510),
                _finding("registry-check", "1.0.2", "entity_attestation", "supports", 0.87,
                         "Account holder matches the registered legal entity; receiving bank "
                         "publicly announced the merger cited.",
                         [("entity_registry", vendor3.legal_name, "account holder matches")], 1380),
                _finding("callback", "1.2.1", "out_of_band_confirmation", "supports", 0.95,
                         "The vendor's controller, reached on the number of record, confirmed "
                         "the migration and quoted the new account fragment unprompted.",
                         [("callback_log", vendor3.contact_phone_of_record,
                           "vendor confirmed the change on the number of record")], 2980),
            ],
            challenge=ChallengeResult(
                strongest_legitimate_explanation="A publicly announced bank merger forcing a "
                                                 "receiving-account migration.",
                rebuttals=[],
                survived=True,
                reasoning="Independently confirmed out of band by a person reached on the "
                          "number held in the system of record.",
            ),
            decision=Decision(
                outcome="RELEASE", confidence=0.94,
                rationale="Confirmed by three independent agents including a positive "
                          "out-of-band callback. Exposure is below the auto-release ceiling. "
                          "Hold released.",
                dissenting_findings=[],
                decided_at=opened3 + timedelta(hours=6), decided_by="fleet",
            ),
        )
        await repo.save_case(released)
        await chain.emit(released, released.decision)
        written += 1

    return written
