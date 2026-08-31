"""Sentry — detects the change, freezes the money, opens the case. Judges nothing."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from ..models.domain import DEFAULT_TENANT_ID, Case, CaseState, ChangeRequest, Vendor
from ..store.base import Repository
from .base import AgentContext, InterdictAgent

HOLD_WINDOW_DAYS = 7

# Words that mean money is being moved, and words that mean something is being changed. Neither
# alone is interesting: "statement of account" is routine, and "updated delivery window" is
# routine. Together they are the shape of a payee-detail change.
# Enumerated word forms, not stems. Stemming was too blunt in both directions: appending \w*
# made "wire" match "wireless" and "account" match "accounting", while matching bare stems missed
# "updated". Multi-word phrases are matched as substrings because they are unambiguous on their own.
MONEY_TERMS = (
    "bank", "banks", "banking",
    "account", "accounts",
    "routing", "remittance", "remittances", "remit", "remitted",
    "ach", "eft", "iban", "wire", "wires", "beneficiary",
    "direct deposit", "sort code", "payment details", "bank details", "banking details",
)
CHANGE_TERMS = (
    "update", "updates", "updated", "updating",
    "change", "changes", "changed", "changing",
    "new", "revised", "switch", "switched", "switching",
    "migrate", "migrated", "migrating", "migration", "transition",
    "effective immediately", "going forward", "from now on",
)

TRIAGE_PROMPT = """You are Sentry, the intake filter for a payment-fraud interdiction fleet at a
public school district business office.

You are reading one piece of ordinary vendor correspondence. Decide ONE thing: is this message
asking the district to change where a vendor's money is sent?

Only that. Not whether it looks suspicious — a later fleet of specialists decides that, expensively.
Your job is to protect their attention.

Investigate if the message asks to add, change, or redirect bank details, remittance information,
or a payment destination. Ignore invoices, delivery notes, quotes, scheduling, statements of
account, and every other routine matter, even when they discuss money.

Return JSON only:
{"action": "investigate"|"ignore", "confidence": 0.0-1.0, "reason": "<one short sentence>"}"""


@dataclass(frozen=True)
class TriageVerdict:
    """One intake decision. `used_model` is reported because the point of triage is that most
    messages are settled without spending a model call on them."""

    message_id: str
    action: str          # "investigate" | "ignore"
    confidence: float
    reason: str
    used_model: bool

    @property
    def investigate(self) -> bool:
        return self.action == "investigate"

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "action": self.action,
            "confidence": self.confidence,
            "reason": self.reason,
            "used_model": self.used_model,
        }


class SentryAgent(InterdictAgent):
    name = "sentry"
    version = "1.5.0"
    signal = "payee_change_detected"

    # --- intake triage ----------------------------------------------------------

    @staticmethod
    def _scan(text: str) -> tuple[bool, bool]:
        """Match on word boundaries, never substrings.

        Substring matching flagged an ordinary custodial invoice: "ach" appears inside
        "attaching", and "change" inside "no change to the hours". That opened a case on a
        routine message, which costs six model calls and puts a phantom interdiction in front of
        the operator. Terms ending in a letter get a trailing \\w* so "update" still catches
        "updated" and "migrat" still catches "migrating".
        """
        low = text.lower()

        def hit(term: str) -> bool:
            if " " in term:
                return term in low          # phrases are unambiguous on their own
            return re.search(rf"\b{re.escape(term)}\b", low) is not None

        return (
            any(hit(t) for t in MONEY_TERMS),
            any(hit(t) for t in CHANGE_TERMS),
        )

    async def triage(self, ctx: AgentContext, message: Any) -> TriageVerdict:
        """Decide whether one message deserves the fleet's attention.

        Three outcomes, and only one of them costs a model call:

          no money language at all      -> ignore, free. Most of the morning's post.
          money AND change language     -> investigate, free. The shape is unambiguous.
          money without change language -> ask the model. This is the genuinely ambiguous
                                           middle — a statement of account and a request to
                                           change an account read alike to a keyword filter.

        The fleet costs six model calls and roughly forty seconds per case. Spending that on a
        delivery-window notice is not thoroughness, it is waste — and at scale it is the
        difference between a system an office can run and one it cannot.
        """
        text = f"{getattr(message, 'subject', '')}\n{getattr(message, 'body', '')}"
        money, change = self._scan(text)
        mid = getattr(message, "message_id", "?")

        if not money:
            return TriageVerdict(mid, "ignore", 0.95,
                                 "No payment-destination language.", used_model=False)

        if money and change:
            return TriageVerdict(mid, "investigate", 0.92,
                                 "Asks to change where money is sent.", used_model=False)

        result = await self.infer(ctx, TRIAGE_PROMPT, {
            "subject": getattr(message, "subject", ""),
            "body": (getattr(message, "body", "") or "")[:1500],
            "sender": getattr(message, "sender_email", ""),
            "has_attachment": getattr(message, "has_attachment", False),
        })
        action = result.get("action", "ignore")
        return TriageVerdict(
            mid,
            "investigate" if action == "investigate" else "ignore",
            float(result.get("confidence", 0.5)),
            str(result.get("reason", "")),
            used_model=True,
        )

    async def resolve_vendor(self, repo: Repository, request: ChangeRequest) -> Vendor | None:
        if request.vendor_id:
            vendor = await repo.get_vendor(request.vendor_id)
            if vendor:
                return vendor
        # An unresolvable request is itself a strong signal; we still open a case for it.
        sender = str(request.artifact_metadata.get("from", ""))
        domain = sender.rsplit("@", 1)[-1].lower() if "@" in sender else ""
        if not domain:
            return None
        # Deliberately unscoped. Intake is fleet-wide — a message arrives before anyone knows
        # whose supplier it names — and it is the resolved vendor that DECIDES the case's tenant
        # below. Scoping this to one district would misfile the other district's mail.
        for candidate in await repo.list_vendors():
            if candidate.contact_email_of_record.rsplit("@", 1)[-1].lower() == domain:
                return candidate
        return None

    async def open_case(self, ctx: AgentContext, request: ChangeRequest) -> Case:
        """Create the case in OPENED. The pipeline's hold step does the freezing, so the money
        movement stays inside the idempotency-guarded PaymentService rather than in an agent."""
        vendor = await self.resolve_vendor(ctx.repo, request)
        now = ctx.clock.now()
        case = Case(
            # Derived from the request rather than random. A case id is not merely a label:
            # it is embedded in the attribution finding's id, in its evidence locator, and in the
            # excerpt naming the prior case an operation was recognised from. A uuid4 here meant
            # every one of those strings changed on every run, so the Challenger and Adjudicator
            # — which reason over those findings — could never hit the replay cache, and offline
            # rehearsal died on a 503 that pointed at the Challenger rather than at the cause.
            case_id=f"CASE-{hashlib.sha256(request.request_id.encode()).hexdigest()[:6].upper()}",
            request_id=request.request_id,
            vendor_id=vendor.vendor_id if vendor else None,
            # The targeted vendor's district owns the case. An unresolvable request has no
            # district to belong to, so it falls to the first — which is also the only tenant
            # whose operator is looking at an unattributed artifact.
            tenant_id=vendor.tenant_id if vendor else DEFAULT_TENANT_ID,
            state=CaseState.OPENED,
            exposure_amount=Decimal("0"),
            opened_at=now,
            deadline_at=now + timedelta(days=HOLD_WINDOW_DAYS),
        )
        await ctx.repo.save_case(case)
        return case
