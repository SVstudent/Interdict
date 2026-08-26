"""The red-team sandbox — the real pipeline, with the district's money unplugged.

A red team that tests a mock proves nothing about the product, so an invented attack is executed
as a genuine `ChangeRequest` through the same steps, the same four verification lanes, the same
adversarial challenge and the same adjudication rails that decide a district's cases. What the
sandbox changes is not the fleet, it is what the fleet is allowed to touch: the case belongs to
the simulation tenant, the vendor and the payments are freshly minted for the trial, and four
capabilities are withheld.

  Scribe        withheld — an invented operation must not be named into the threat library.
  the pen on
  the library   withheld — Red Team is denied `threatintel:write` for a reason: a red team that
                can edit the record it tests against measures its own edits. The library is still
                READ, so the fleet gets its recall lookup and a rerun is recognised as a rerun.
  Hunter        withheld — Hunter sweeps the whole payment book. A simulated block must never
                reach out and freeze a district's real scheduled payments.
  the exchange  withheld — a simulated block entering the shared exchange would tell another
                district it had been attacked by an operation that never existed.
  precedent     withheld — a fictional case must not accumulate citations in a real book.

Where an attack can actually win, stated plainly, because a red team that cannot say where it
might win is decoration. The hold goes on at case OPEN, before any verification runs, so once the
fleet is looking at a request the money has already stopped; and RELEASE is gated by deterministic
rails that no artifact can argue around. The reachable escape is INTAKE — the triage filter that
decides which of the morning's messages deserve a case at all, which exists because six model
calls per message is not affordable. That filter is the fleet's cost optimisation and its attack
surface, and it is the same trade every real detection system makes. The harness measures the
adjudication path too, so that the day someone loosens a rail, the number moves.

The callback is answered truthfully: the vendor did not ask for this change, so when the district
dials the number of record it hears a denial. Simulating a confirmation would be simulating the
attacker defeating a control they cannot reach, and the hit rate would be a lie.
"""
from __future__ import annotations

import time
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from ..agents.redteam import AttackVariant, RedTeamTrial
from ..models.domain import (
    DEFAULT_TENANT_ID,
    SIMULATION_TENANT_ID,
    BankingDetails,
    CaseState,
    ChangeRequest,
    Invoice,
    Payment,
    Vendor,
)
from ..orchestrator.fanout import VerificationFanout
from ..orchestrator.pipeline import build_pipeline
from ..orchestrator.runner import CaseRunner, StepContext
from ..seed.inbox import InboxMessage

# The sandbox target: one district supplier, seeded fresh for every trial so that no two variants
# compete for the same held payments — the D-012 failure, where consecutive scenarios sharing a
# vendor found nothing left to freeze and opened at $0 exposure.
#
# Its exposure sits between CALLBACK_REQUIRED_THRESHOLD and AUTO_RELEASE_CEILING on purpose. Below
# the callback threshold the rails barely engage; above the release ceiling rail 4 converts any
# proposed release into an escalation and the fleet wins on arithmetic rather than on evidence.
# In this band the case genuinely turns on what the lanes found.
TARGET_LEGAL_NAME = "Merrivale Instructional Systems LLC"
TARGET_DOMAIN = "merrivale-instructional.test"
TARGET_PHONE = "+1-503-555-0188"
TARGET_TENURE_DAYS = 5 * 365
TARGET_PAYMENTS = (Decimal("74500.00"), Decimal("61250.00"))

# What the attacker is told about the target. An attacker researches their mark, so withholding
# this would not make the fleet look better — it would make the attack incoherent.
def target_brief() -> dict[str, Any]:
    return {
        "legal_name": TARGET_LEGAL_NAME,
        "domain_of_record": TARGET_DOMAIN,
        "contact_email_of_record": f"ap@{TARGET_DOMAIN}",
        "relationship_years": round(TARGET_TENURE_DAYS / 365.25, 1),
        "scheduled_exposure": str(sum(TARGET_PAYMENTS, Decimal("0"))),
        "has_an_open_invoice": True,
        "sector": "instructional materials for a public school district",
    }


class _ReadOnlyRecall:
    """The threat library with the pen taken away.

    Enforced at the port rather than trusted to the pipeline: `AdjudicateStep` calls `remember`
    on every BLOCK, and a simulated block that grew the library would leave the fleet recognising
    an operation nobody has ever been attacked by.
    """

    def __init__(self, recall: Any) -> None:
        self._recall = recall

    async def recall(self, fp: Any, tenant_id: str = DEFAULT_TENANT_ID) -> Any:
        # Deliberately reads the district's book, not the simulation tenant's: the trial is only
        # a fair test of the fleet if the fleet gets the memory it would really have.
        return await self._recall.recall(fp, DEFAULT_TENANT_ID)

    async def remember(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def known_count(self, tenant_id: str | None = None) -> int:
        return await self._recall.known_count(tenant_id)

    async def library(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return await self._recall.library(tenant_id)


def build_sandbox_runner(state: Any) -> CaseRunner:
    """The fleet's own runner, differing only in what it withholds.

    Deliberately not `state.build_runner()`. That runner is wired for a district: it writes the
    threat library, publishes to the exchange, and turns Hunter loose on the payment book. The
    sandbox is defined by the four things it does not pass on, so they are absent here by
    omission and visible as such.
    """
    verification = {
        name: state.agents[name]
        for name in ("callback", "ledger", "provenance", "registry-check")
    }
    fanout = VerificationFanout(verification, state.agent_ctx)

    async def challenge(ctx: StepContext, findings):
        await state.platform.gateway.route("orchestrator", "challenger", {})
        return await state.agents["challenger"].review(
            state.agent_ctx(ctx, "challenger"), findings
        )

    async def attribute(ctx: StepContext, dossier, match, request_summary):
        return await state.agents["attribution"].attribute(
            state.agent_ctx(ctx, "attribution"), dossier, match, request_summary
        )

    async def adjudicate(ctx: StepContext, findings, challenge_result):
        await state.platform.gateway.route("orchestrator", "adjudicator", {})
        return await state.agents["adjudicator"].decide(
            state.agent_ctx(ctx, "adjudicator"), ctx.case, findings, challenge_result
        )

    return CaseRunner(
        repo=state.repo,
        clock=state.clock,
        steps=build_pipeline(
            state.payments, fanout, challenge, adjudicate,
            recall=_ReadOnlyRecall(state.platform.recall),
            memory=state.platform.memory,
            attribute=attribute,
        ),
        emit=state.emit,
    )


async def run_variant(state: Any, variant: AttackVariant) -> RedTeamTrial:
    """Run one invented attack through the real pipeline against the simulation tenant."""
    started = time.perf_counter()
    now = state.clock.now()
    vendor, request = await _seed_trial(state, variant, now)

    def trial(**fields: Any) -> RedTeamTrial:
        return RedTeamTrial(
            variant_id=variant.variant_id,
            variant_name=variant.name,
            technique=variant.technique,
            latency_ms=int((time.perf_counter() - started) * 1000),
            **fields,
        )

    sentry = state.agents["sentry"]
    verdict = await sentry.triage(
        state.agent_ctx_for_request(request), _as_message(variant, request, now)
    )
    if not verdict.investigate:
        # The money never stopped: the payments are still SCHEDULED and nothing froze them,
        # because no case was ever opened to freeze them.
        return trial(
            caught=False,
            outcome=None,
            simulated_case_id="",
            escaped_reason=await _escape_reason(
                state, variant,
                f"Intake triage ignored the message and no case was opened, so the "
                f"${sum(TARGET_PAYMENTS, Decimal('0')):,} stayed scheduled. Sentry's reason: "
                f"{verdict.reason}",
                {"control": "sentry:intake_triage", "case_state": "never opened",
                 "triage_reason": verdict.reason, "triage_confidence": verdict.confidence},
            ),
        )

    case = await sentry.open_case(state.agent_ctx_for_request(request), request)
    # Sentry stamps the default district on a case because that is all it has ever had to do. A
    # simulated case left in a district's tenant would sit in its docket beside real interdictions.
    case.tenant_id = SIMULATION_TENANT_ID
    await state.repo.save_case(case)

    try:
        await build_sandbox_runner(state).advance(
            case.case_id,
            {"callback_response": "denied", "claimed_reason": request.claimed_reason},
        )
    except Exception:  # noqa: BLE001 - a fallen-over pipeline is not an escape
        # The hold went on at OPEN, before any judgement ran, so the money is not moving. That is
        # not a pass either, which is why the trial carries no outcome to report.
        result = await state.repo.get_case(case.case_id)
        return trial(caught=True, outcome=None, simulated_case_id=case.case_id,
                     top_signal=_top_signal(result))

    result = await state.repo.get_case(case.case_id)
    outcome = result.decision.outcome if result and result.decision else None
    if outcome == "RELEASE" or (result and result.state is CaseState.RELEASED):
        return trial(
            caught=False,
            outcome=outcome,
            simulated_case_id=case.case_id,
            top_signal=_top_signal(result),
            escaped_reason=await _escape_reason(
                state, variant,
                f"The fleet adjudicated RELEASE on ${result.exposure_amount:,} after the "
                f"deterministic rails ran, so a safety rail no longer holds.",
                {"control": "adjudicator:apply_rails", "case_state": result.state.value,
                 "exposure": str(result.exposure_amount),
                 "findings": [{"agent": f.agent, "verdict": f.verdict,
                               "confidence": f.confidence} for f in result.findings]},
            ),
        )

    # BLOCK and ESCALATE are both catches. Stopping the money and asking a human is the designed
    # outcome of an ambiguous case, not a miss — and a case still in flight is a catch too,
    # because the hold is already on.
    return trial(caught=True, outcome=outcome, simulated_case_id=case.case_id,
                 top_signal=_top_signal(result))


async def _escape_reason(
    state: Any, variant: AttackVariant, control: str, facts: dict[str, Any]
) -> str:
    """Name the control that failed, then ask the agent what would close it.

    The deterministic half is written first and never discarded: an escape with no explanation is
    a bug report nobody can act on, and that must not depend on a model call succeeding.
    """
    try:
        explained = await state.agents["redteam"].explain_escape(
            state.agent_ctx_for_request(None, case_id=variant.variant_id), variant, facts
        )
    except Exception:  # noqa: BLE001 - enrichment, never a gate
        explained = ""
    return f"{control} {explained}".strip()


def _top_signal(case: Any) -> str | None:
    """The lane that carried the verdict — the highest-confidence finding arguing against the
    request. None when nothing objected, which on an escape is the whole story."""
    if case is None:
        return None
    objections = [f for f in case.findings if f.verdict == "contradicts"]
    return max(objections, key=lambda f: f.confidence).signal if objections else None


async def _seed_trial(
    state: Any, variant: AttackVariant, now: Any
) -> tuple[Vendor, ChangeRequest]:
    """A throwaway vendor, one open invoice and two scheduled payments, all in the simulation
    tenant, plus the change request the variant is asking for."""
    suffix = uuid.uuid4().hex[:6].upper()
    onboarded = now - timedelta(days=TARGET_TENURE_DAYS)
    vendor = Vendor(
        vendor_id=f"SIM-V-{suffix}",
        tenant_id=SIMULATION_TENANT_ID,
        legal_name=TARGET_LEGAL_NAME,
        onboarded_at=onboarded,
        contact_email_of_record=f"ap@{TARGET_DOMAIN}",
        contact_phone_of_record=TARGET_PHONE,
        banking=BankingDetails(
            account_name=TARGET_LEGAL_NAME, account_last4="4102", routing_last4="0338",
            bank_name="First Meridian Bank", bank_country="US", effective_from=onboarded,
        ),
        total_paid_lifetime=Decimal("2140000.00"),
        invoice_count=96,
        operating_country="US",
    )
    await state.repo.save_vendor(vendor)

    invoice = Invoice(
        invoice_id=f"SIM-INV-{suffix}", vendor_id=vendor.vendor_id,
        amount=TARGET_PAYMENTS[0], issued_at=now - timedelta(days=18),
        due_at=now + timedelta(days=12), status="open",
    )
    await state.repo.save_invoice(invoice)

    for slot, amount in enumerate(TARGET_PAYMENTS):
        await state.repo.save_payment(Payment(
            payment_id=f"SIM-PAY-{suffix}-{slot}",
            vendor_id=vendor.vendor_id,
            tenant_id=SIMULATION_TENANT_ID,
            invoice_id=invoice.invoice_id,
            amount=amount,
            scheduled_for=now + timedelta(days=3),
        ))

    # An attacker sending from the vendor's own domain of record has compromised a mailbox rather
    # than registered anything, so there is no new domain to date. Otherwise the domain is the
    # attacker's, and attacker domains are young — which is a signal the provenance lane earns
    # rather than one the harness hands it, since the variant chose to register one.
    from_own_domain = variant.reply_to_domain in ("", TARGET_DOMAIN)
    reply_to_domain = TARGET_DOMAIN if from_own_domain else variant.reply_to_domain
    registered_at = onboarded if from_own_domain else now - timedelta(days=9)

    subject, body = _split_subject(variant.artifact, variant.name)
    request = ChangeRequest(
        request_id=f"SIM-REQ-{suffix}",
        vendor_id=vendor.vendor_id,
        channel="email",
        received_at=now,
        raw_artifact=body,
        artifact_metadata={
            "from": f"ap@{TARGET_DOMAIN}",
            "reply_to": f"ap@{reply_to_domain}",
            "reply_to_domain_registered_at": registered_at,
            "referenced_invoice": invoice.invoice_id,
            "supplied_phone": variant.supplied_phone,
            "baseline_producer": "Sage Intacct PDF Writer 9.2",
            "subject": subject,
        },
        proposed_banking=BankingDetails(
            account_name=variant.proposed_account_name, account_last4="9930",
            routing_last4="7714", bank_name=variant.proposed_bank, bank_country="US",
            effective_from=now,
        ),
        claimed_reason=variant.technique,
    )
    await state.repo.save_request(request)
    return vendor, request


def _split_subject(artifact: str, fallback: str) -> tuple[str, str]:
    """Take the subject line off the front of the artifact.

    Triage reads the subject and the body together, so a variant that cannot write its own subject
    line is not being tested honestly — the operation's internal name would never appear in a real
    inbox, and it is only used when the generation supplied nothing better.
    """
    head, _, rest = artifact.partition("\n")
    if head.lower().startswith("subject:"):
        return head.split(":", 1)[1].strip(), rest.lstrip("\n")
    return fallback, artifact


def _as_message(variant: AttackVariant, request: ChangeRequest, now: Any) -> InboxMessage:
    """The attack as it lands in the business office inbox — the same object triage reads every
    morning, so the intake filter is being tested rather than approximated."""
    meta = request.artifact_metadata
    return InboxMessage(
        message_id=f"SIM-MSG-{variant.variant_id}",
        received_at=now,
        sender_name="Accounts Receivable",
        sender_email=str(meta.get("from", "")),
        subject=str(meta.get("subject", variant.name)),
        body=request.raw_artifact,
        metadata={"reply_to": str(meta.get("reply_to", ""))},
    )
