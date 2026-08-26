"""Scribe — writes the fleet's threat intelligence.

The eighth agent, and the one that makes the fleet's memory an intelligence product rather than a
lookup table. When a case terminates in BLOCK, Scribe reads the whole case — findings, evidence,
the adversarial review, the decision — and writes a dossier on the operation behind it: a
designation, an assessment, the tradecraft, and a prediction of who gets hit next.

Two agents bracket a deterministic core, deliberately:

  Scribe (here)          synthesises tradecraft into a named dossier            -- reasoning model
  Recall (recall.py)     retrieves candidate matches by structured fingerprint  -- no model
  Attribution (below)    reads the dossier and argues same-actor or not         -- reasoning model

Retrieval stays deterministic so it is fast, free, and structurally incapable of inventing a prior
case that never happened. The judgement at either end is genuinely agentic, because naming an
adversary and attributing a new attack to it are judgement calls, not lookups.
"""
from __future__ import annotations

from typing import Any

from ..models.domain import Case
from .base import AgentContext, InterdictAgent

SCRIBE_PROMPT = """You are Scribe, the threat-intelligence analyst for a payment-fraud
interdiction fleet at a public school district.

A payment-diversion attempt has just been BLOCKED. Your job is to turn this single case into
durable intelligence the fleet can use months from now, against a different vendor, when the
operators come back.

You are writing for a district business manager, not a security researcher. No jargon they would
have to look up.

Write a dossier:

1. DESIGNATION — a two-word codename for this operation, in the form "Adjective Noun"
   (e.g. "Hollow Ledger", "Quiet Freight"). Evocative and memorable, never a real company,
   person, or place name. This is how humans will refer to the operation.

2. ASSESSMENT — two sentences on what this operation is doing and what makes it distinctive.

3. TRADECRAFT — the reusable techniques, as short phrases. What would this operator do again?

4. INDICATORS — concrete things a person could look for in a future request.

5. LIKELY NEXT TARGET — one sentence. Given what this operator chose this time, what kind of
   vendor and what kind of payment would they go after next? Be specific and justify it briefly.

6. CONFIDENCE — 0.0 to 1.0 in your own assessment. A single case is thin evidence for
   attribution; say so if it is.

Return JSON only:
{"designation": "...", "assessment": "...", "tradecraft": ["..."], "indicators": ["..."],
 "likely_next_target": "...", "confidence": 0.0}"""


ATTRIBUTION_PROMPT = """You are the attribution analyst for a payment-fraud interdiction fleet.

A new payment-detail change request has arrived. The fleet's structured matcher flagged it as
resembling an operation it blocked before, and you are given that operation's dossier plus the
matcher's reasons.

Your job is to decide whether this really is the same operator, or a coincidence.

Be genuinely sceptical. These signals recur for innocent reasons: many vendors bank with the same
regional banks, new domains get registered constantly, and factoring companies legitimately
receive payments under their own name. A wrong attribution tells the operator something false
about who is attacking them.

Return JSON only:
{"verdict": "supports"|"contradicts"|"inconclusive",
 "confidence": 0.0-1.0,
 "same_operator": true|false,
 "reasoning": "<two sentences a district business manager can act on>"}

Read the verdict field the same way the rest of the fleet does: it answers whether the evidence
supports the LEGITIMACY of the request. If you conclude this is the same operator that was
previously blocked, that CONTRADICTS legitimacy. If the resemblance is coincidental, this is
"inconclusive" — the absence of an attribution is not evidence the request is genuine."""


class ScribeAgent(InterdictAgent):
    name = "scribe"
    version = "1.0.0"
    signal = "threat_intelligence"

    @property
    def model(self) -> str:
        # Deliberately the routine tier, not the reasoning tier. Scribe runs AFTER the decision
        # and the payment action are committed, so its latency is off the critical path, and
        # keeping it off the reasoning model leaves that quota for Challenger, Adjudicator and
        # Attribution — the three calls an operator is actually waiting on.
        return self._settings.FLASH_MODEL

    async def write_dossier(self, ctx: AgentContext, case: Case) -> dict[str, Any]:
        observations = {
            "exposure_amount": str(case.exposure_amount),
            "vendor_id": case.vendor_id,
            "findings": [
                {
                    "agent": f.agent, "signal": f.signal, "verdict": f.verdict,
                    "confidence": f.confidence, "reasoning": f.reasoning,
                    "evidence": [e.model_dump() for e in f.evidence],
                }
                for f in case.findings
            ],
            "adversarial_review": (
                case.challenge.model_dump() if case.challenge else None
            ),
            "decision": case.decision.model_dump() if case.decision else None,
        }
        result = await self.infer(ctx, SCRIBE_PROMPT, observations)
        # Through the tool, not around it. Scribe is the one agent granted `threatintel:write`,
        # and a grant nothing exercises is indistinguishable from one nobody has.
        return await self.call_tool(
            ctx, "write_threat_library",
            designation=result.get("designation", ""),
            assessment=result.get("assessment", ""),
            tradecraft=list(result.get("tradecraft", [])),
            indicators=list(result.get("indicators", [])),
            likely_next_target=result.get("likely_next_target", ""),
            confidence=float(result.get("confidence", 0.5)),
            first_seen_case_id=case.case_id,
            authored_by=f"{self.name} v{self.version}",
            model=self.model,
        )


class AttributionAgent(InterdictAgent):
    """Reads a dossier and argues whether a new request belongs to that operation."""

    name = "attribution"
    version = "1.0.0"
    signal = "operation_attribution"

    @property
    def model(self) -> str:
        return self._settings.reasoning_model()

    async def attribute(
        self, ctx: AgentContext, dossier: dict[str, Any], match: dict[str, Any],
        request_summary: dict[str, Any],
    ) -> dict[str, Any]:
        observations = {
            "known_operation": {
                "designation": dossier.get("designation"),
                "assessment": dossier.get("assessment"),
                "tradecraft": dossier.get("tradecraft"),
                "indicators": dossier.get("indicators"),
                "likely_next_target": dossier.get("likely_next_target"),
                "first_seen_case_id": dossier.get("first_seen_case_id"),
            },
            "structured_matcher": {
                "score": match.get("score"),
                "matched_on": match.get("matched_on"),
            },
            "new_request": request_summary,
        }
        result = await self.infer(ctx, ATTRIBUTION_PROMPT, observations)
        return {
            "verdict": result.get("verdict", "inconclusive"),
            "confidence": float(result.get("confidence", 0.5)),
            "same_operator": bool(result.get("same_operator")),
            "reasoning": result.get("reasoning", ""),
            "designation": dossier.get("designation"),
        }
