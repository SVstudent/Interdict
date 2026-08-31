"""Ledger — relationship baseline, lane 2 of the verification fan-out.

Reads the vendor's ERP history: tenure, invoice volume, prior banking-change frequency, and
whether the invoice the request cites is genuinely open. Read-only by grant.

The asymmetry it exists to encode: a long clean relationship with no prior banking changes makes
a sudden change more notable, not less — and a correctly cited open invoice is weak evidence of
authenticity, because attackers read invoices too.
"""
from __future__ import annotations

import time

from ..models.domain import EvidenceRef, Finding
from .base import VERDICT_RUBRIC, AgentContext, InterdictAgent

PROMPT = """You are Ledger, the relationship-history analyst in a payment-fraud interdiction fleet.

You see the vendor's ERP baseline and whether the invoice the request cites is genuinely open.
A long clean relationship with no prior banking changes makes a sudden change more notable, not
less. A correctly cited open invoice is weak evidence of authenticity: attackers read invoices too.

""" + VERDICT_RUBRIC


class LedgerAgent(InterdictAgent):
    """Scores the change against the vendor's own payment and invoice history."""
    name = "ledger"
    version = "1.3.0"
    signal = "relationship_baseline"

    async def evaluate(self, ctx: AgentContext) -> Finding:
        started = time.perf_counter()
        vendor = await ctx.repo.get_vendor(ctx.payload["vendor_id"])
        request = await ctx.repo.get_request(ctx.payload["request_id"])
        invoices = await ctx.repo.list_invoices(vendor.vendor_id)

        baseline = await self.call_tool(ctx, "relationship_baseline", vendor=vendor, now=ctx.clock.now())
        correlation = await self.call_tool(
            ctx, "correlate_open_invoice", invoices=invoices,
            referenced_invoice_id=request.artifact_metadata.get("referenced_invoice"),
            now=ctx.clock.now(),
        )

        evidence = [
            EvidenceRef(source="erp:vendor", locator=vendor.vendor_id,
                        excerpt=f"{baseline['tenure_years']} years, {baseline['invoice_count']} invoices, "
                                f"{baseline['prior_banking_changes']} prior banking changes"),
        ]
        if correlation["exists"]:
            evidence.append(EvidenceRef(
                source="erp:invoices", locator=correlation["referenced_invoice_id"],
                excerpt=f"status={correlation['status']}, amount={correlation['amount']}"))
        elif correlation["referenced_invoice_id"]:
            evidence.append(EvidenceRef(
                source="erp:invoices", locator=correlation["referenced_invoice_id"],
                excerpt="referenced invoice not found in the ledger"))

        result = await self.infer(ctx, PROMPT, {"baseline": baseline, "invoice": correlation})
        return self.build_finding(
            verdict=result["verdict"], confidence=float(result["confidence"]),
            reasoning=result["reasoning"], evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
