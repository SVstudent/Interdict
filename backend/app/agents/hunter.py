"""Hunter — proactive exposure sweep.

The gap this closes: until now the fleet was purely reactive. It stopped the email in front of it
and handed the operator a blocked case. Nobody asked the obvious next question — *what else is
this operation about to hit?* — so the answer arrived only when the next fraudulent email did.

After an interdiction, Hunter reads the dossier Scribe wrote, decides which of its indicators are
actually actionable against the payment book, and searches. Anything matching is frozen before the
attacker's next message arrives, and each freeze opens a normal case that goes through the whole
fleet. Hunter can interrupt; it cannot conclude.

That division is deliberate. An agent acting on its own initiative, against payments nobody
complained about, is the one place in this system where an overconfident model could do real
damage — so it gets the narrowest power that still removes the friction: freeze and escalate,
never release, never block, never write to the ERP.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..models.domain import DEFAULT_TENANT_ID, Payment, PaymentStatus, Vendor
from .base import AgentContext, InterdictAgent

HUNTER_PROMPT = """You are Hunter, the proactive exposure analyst for a payment-fraud interdiction
fleet at a public school district.

An operation has just been interdicted. You have its dossier and the district's book of scheduled
payments and vendors. Your job is to work out which OTHER payments this same operation is likely
to be positioned against, so they can be frozen before the next fraudulent request arrives.

You are choosing where to spend the district's attention, and a freeze is disruptive: a vendor who
does not get paid on time is a real cost, and the business office has to unwind it by hand. Do not
sweep the whole book. Select only where the dossier gives you a genuine reason.

Think about what this operator actually needs to succeed: a large enough payment to be worth the
effort, a vendor relationship they could plausibly impersonate, and timing they can predict.

Return JSON only:
{"targets": [{"payment_id": "...", "reason": "<one sentence naming the specific dossier indicator
that applies>", "risk": "high"|"medium"}],
 "reasoning": "<two sentences a district business manager can act on>",
 "swept_but_cleared": ["<payment_id you considered and deliberately left alone>"]}

An empty targets list is a valid and often correct answer. Say so plainly if the dossier gives you
nothing actionable — a sweep that freezes nothing is far better than one that freezes everything."""


@dataclass
class SweepTarget:
    """One scheduled payment the sweep believes belongs to the same operation."""
    payment_id: str
    vendor_id: str
    vendor_name: str
    amount: Decimal
    reason: str
    risk: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "vendor_id": self.vendor_id,
            "vendor_name": self.vendor_name,
            "amount": str(self.amount),
            "reason": self.reason,
            "risk": self.risk,
        }


@dataclass
class SweepResult:
    """What a proactive sweep found: what it froze, what it cleared, and why.

    `cleared` matters as much as `targets` — a sweep that reports only its hits gives the
    operator no way to judge whether it looked hard enough.
    """
    designation: str
    origin_case_id: str
    targets: list[SweepTarget] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    reasoning: str = ""
    considered: int = 0
    frozen_total: Decimal = Decimal("0")
    latency_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "designation": self.designation,
            "origin_case_id": self.origin_case_id,
            "targets": [t.as_dict() for t in self.targets],
            "cleared": self.cleared,
            "reasoning": self.reasoning,
            "considered": self.considered,
            "frozen_total": str(self.frozen_total),
            "latency_ms": self.latency_ms,
        }


class HunterAgent(InterdictAgent):
    name = "hunter"
    version = "1.0.0"
    signal = "proactive_exposure_sweep"

    @property
    def model(self) -> str:
        return self._settings.reasoning_model()

    async def sweep(
        self, ctx: AgentContext, dossier: dict[str, Any], origin_case_id: str,
        exclude_vendor_ids: set[str], tenant_id: str = DEFAULT_TENANT_ID,
    ) -> SweepResult:
        started = time.perf_counter()
        designation = str(dossier.get("designation") or "Unnamed Operation")

        # Scoped to the district that ran the interdiction. Tradecraft crosses a district
        # boundary through the exchange; a freeze never does. An unscoped sweep would let one
        # district's case stop another district's money on a suspicion its operator cannot see.
        payments: list[Payment] = [
            p for p in await ctx.repo.list_payments(tenant_id=tenant_id)
            if p.status is PaymentStatus.SCHEDULED
            and p.vendor_id not in exclude_vendor_ids
        ]
        if not payments:
            return SweepResult(designation, origin_case_id, reasoning="No scheduled payments to sweep.")

        vendors: dict[str, Vendor] = {
            v.vendor_id: v for v in await ctx.repo.list_vendors(tenant_id)
        }

        # Give the model the book, not the whole database. Largest first: the operator's own
        # economics push them toward the biggest predictable disbursements.
        book = sorted(payments, key=lambda p: p.amount, reverse=True)[:25]
        observations = {
            "operation": {
                "designation": designation,
                "assessment": dossier.get("assessment"),
                "tradecraft": dossier.get("tradecraft"),
                "indicators": dossier.get("indicators"),
                "likely_next_target": dossier.get("likely_next_target"),
            },
            "scheduled_payments": [
                {
                    "payment_id": p.payment_id,
                    "vendor_id": p.vendor_id,
                    "vendor_name": (vendors.get(p.vendor_id).legal_name
                                    if vendors.get(p.vendor_id) else "unknown"),
                    "amount": str(p.amount),
                    "scheduled_for": p.scheduled_for.isoformat(),
                    "vendor_tenure_days": (vendors[p.vendor_id].tenure_days(ctx.clock.now())
                                           if p.vendor_id in vendors else None),
                    "prior_banking_changes": (len(vendors[p.vendor_id].banking_change_history)
                                              if p.vendor_id in vendors else None),
                }
                for p in book
            ],
        }

        result = await self.infer(ctx, HUNTER_PROMPT, observations)

        by_id = {p.payment_id: p for p in payments}
        targets: list[SweepTarget] = []
        for raw in result.get("targets", []):
            pid = raw.get("payment_id")
            payment = by_id.get(pid)
            if payment is None:
                # The model named a payment that is not in the book. Drop it rather than
                # freezing something that does not exist or was never offered for review.
                continue
            vendor = vendors.get(payment.vendor_id)
            targets.append(SweepTarget(
                payment_id=payment.payment_id,
                vendor_id=payment.vendor_id,
                vendor_name=vendor.legal_name if vendor else "unknown",
                amount=payment.amount,
                reason=str(raw.get("reason", "")),
                risk=str(raw.get("risk", "medium")),
            ))

        return SweepResult(
            designation=designation,
            origin_case_id=origin_case_id,
            targets=targets,
            cleared=[str(c) for c in result.get("swept_but_cleared", [])][:12],
            reasoning=str(result.get("reasoning", "")),
            considered=len(book),
            frozen_total=sum((t.amount for t in targets), Decimal("0")),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
