"""Challenger — argues FOR legitimacy, then rebuts each finding individually.

Must sometimes win. A challenger that never survives is decoration; the ESCALATE and RELEASE
outcomes depend on it being a real adversary. Read-only by construction: it holds no tools, so
it cannot act on its own argument.
"""
from __future__ import annotations

import time

from ..models.domain import ChallengeResult, Finding, Rebuttal
from .base import AgentContext, InterdictAgent

PROMPT = """You are Challenger. Your job is to STOP a wrongful block.

Banking details change for real reasons every day: acquisitions, bank mergers, factoring
arrangements, treasury consolidation, a vendor's own bank forcing a migration. A fleet that
blocks every change is useless.

Two tasks, in this order:

1. STEELMAN. Construct the strongest honest explanation under which this change is legitimate.
   Do not strawman it. If the evidence genuinely permits an innocent reading, say so forcefully.

2. REBUT. For EACH supporting finding below, argue specifically why it may not mean what the
   analyst thinks. Mark `succeeds` true only where your rebuttal genuinely defeats the finding —
   overclaiming here releases money to criminals.

Return JSON:
{"strongest_legitimate_explanation": "<paragraph>",
 "rebuttals": [{"finding_id": "...", "argument": "...", "succeeds": true|false}],
 "survived": true|false,
 "reasoning": "<two sentences on whether the legitimate reading holds>"}

`survived` is true only if the innocent explanation is at least as plausible as the fraud reading."""


class ChallengerAgent(InterdictAgent):
    name = "challenger"
    version = "2.0.0"
    signal = "adversarial_review"

    @property
    def model(self) -> str:
        return self._settings.reasoning_model()

    async def review(self, ctx: AgentContext, findings: list[Finding]) -> ChallengeResult:
        started = time.perf_counter()
        observations = {
            # Sorted by agent, not left in arrival order. The four lanes run concurrently and
            # finish in whatever order the models return, so arrival order is nondeterministic —
            # which made this agent's prompt hash different on every run and its response
            # permanently uncacheable. Sorting also gives the model a stable presentation of the
            # same evidence rather than one that reshuffles with network jitter.
            "findings": [
                {
                    "finding_id": f.finding_id, "agent": f.agent, "signal": f.signal,
                    "verdict": f.verdict, "confidence": f.confidence, "reasoning": f.reasoning,
                    "evidence": [e.model_dump() for e in f.evidence],
                }
                for f in sorted(findings, key=lambda f: (f.agent, f.signal))
            ],
            "claimed_reason": ctx.payload.get("claimed_reason"),
        }
        result = await self.infer(ctx, PROMPT, observations)

        valid_ids = {f.finding_id for f in findings}
        rebuttals = [
            Rebuttal(
                finding_id=r["finding_id"],
                argument=r["argument"],
                succeeds=bool(r.get("succeeds")),
            )
            for r in result.get("rebuttals", [])
            # A rebuttal against a finding that does not exist cannot defeat anything.
            if r.get("finding_id") in valid_ids
        ]
        ctx.telemetry.tool_call(
            case_id=ctx.case_id, agent=self.name, tool="rebut_findings", scope="findings:read"
        )
        return ChallengeResult(
            strongest_legitimate_explanation=result["strongest_legitimate_explanation"],
            rebuttals=rebuttals,
            survived=bool(result.get("survived")),
            reasoning=result["reasoning"],
        )
