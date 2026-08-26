"""Precedent Clerk — argues whether a decided case governs a live one.

Same division of labour as recall: `platform/precedent.py` retrieves candidates by deterministic
weighted match over structured characteristics, and this agent makes the judgement call on top —
whether the earlier decision actually SPEAKS to this case, or whether the resemblance is
superficial and the human should be asked again.

Deliberately sceptical, for the same reason Attribution is. A precedent cited wrongly does not
merely mislead: it argues for releasing money, and it does so carrying the authority of a named
person who never looked at this case.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import AgentContext, InterdictAgent

OPINION_PROMPT = """You are the precedent clerk for a payment-fraud interdiction fleet at a public
school district.

A live case is heading for adjudication. The fleet's structured matcher found an earlier case that
a named person resolved by hand, and scored it as closely resembling this one. You decide whether
that ruling actually GOVERNS this case, or whether the resemblance is superficial and the question
should be put to a human again.

Be genuinely sceptical, and note which way the risk runs. Declining to apply a precedent costs one
person ten minutes. Applying one wrongly carries a named reviewer's authority onto a case they
never saw.

A precedent governs only when the facts the earlier decision actually turned on are present here
too. It does not govern merely because the amounts are close, the vendors look similar, or the
same number of lanes objected. Ask what the reviewer was deciding, and whether this case puts them
the same question.

When it does not govern, name the single fact that distinguishes it. An operator overruling you
needs to know what you thought was different, not just that you declined.

Return JSON only:
{"governs": true|false,
 "confidence": 0.0-1.0,
 "reasoning": "<two sentences a district business manager can act on>",
 "distinguished_by": "<the one distinguishing fact, or null when it governs>"}

Your opinion is advisory. Deterministic rails run after you and can only make the outcome more
conservative: no precedent, at any confidence, releases money on its own."""


SUMMARY_PROMPT = """You are the precedent clerk for a payment-fraud interdiction fleet at a public
school district.

A named reviewer has just resolved an escalated case and written why. Restate their reason as one
sentence the fleet can cite back months from now, when the reviewer is not in the room.

You are a stenographer here, not an analyst. Use only what they wrote. Do not add a justification
they did not give, do not soften a reason you disagree with, and do not resolve an ambiguity by
guessing which way they meant it. If their reason is thin, the citation should read as thin.

Return JSON only:
{"rationale": "<one sentence, in the reviewer's own terms>"}"""


@dataclass
class PrecedentOpinion:
    governs: bool
    confidence: float
    reasoning: str
    # The distinguishing fact, when it does NOT govern. An operator overruling the clerk needs to
    # know what the clerk thought was different, not just that it declined.
    distinguished_by: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "governs": self.governs,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "distinguished_by": self.distinguished_by,
        }


class PrecedentClerkAgent(InterdictAgent):
    name = "precedent-clerk"
    version = "1.0.0"
    signal = "precedent_citation"

    @property
    def model(self) -> str:
        return self._settings.reasoning_model()

    async def opine(
        self,
        ctx: AgentContext,
        candidate: dict[str, Any],
        case_summary: dict[str, Any],
    ) -> PrecedentOpinion:
        """Decide whether `candidate` (a PrecedentMatch.as_dict()) governs this case."""
        observations = {
            "prior_decision": {
                "case_id": candidate.get("prior_case_id"),
                "outcome": candidate.get("outcome"),
                "rationale": candidate.get("rationale"),
                "decided_by": candidate.get("decided_by"),
                "decided_at": candidate.get("decided_at"),
                "characteristics": candidate.get("key"),
            },
            "structured_matcher": {
                "score": candidate.get("score"),
                "matched_on": candidate.get("matched_on"),
            },
            "live_case": case_summary,
        }
        result = await self.infer(ctx, OPINION_PROMPT, observations)

        # Absence of an argument is not an argument. A malformed or evasive generation leaves
        # `governs` false, so the citation lands beside the findings as something the operator
        # can read rather than as a ruling the fleet acts on.
        governs = bool(result.get("governs"))
        return PrecedentOpinion(
            governs=governs,
            confidence=float(result.get("confidence", 0.5)),
            reasoning=str(result.get("reasoning", "")),
            # A precedent that governs has nothing distinguishing it; carrying one anyway would
            # put a self-contradicting citation in front of the operator.
            distinguished_by=None if governs else (result.get("distinguished_by") or None),
        )

    async def summarise_resolution(
        self, ctx: AgentContext, case: dict[str, Any], rationale: str
    ) -> str:
        """Normalise a human's free-text rationale into the sentence the book stores."""
        written = rationale.strip()
        if not written:
            # No model call, and nothing invented. A model asked to explain a blank resolution
            # supplies reasoning the reviewer never gave, and the fleet then cites a named person
            # for a position they never took. `Precedent` rejects the empty string instead.
            return ""

        result = await self.infer(ctx, SUMMARY_PROMPT, {"case": case, "resolution": written})
        # Their words are the fallback, never a generated stand-in for them.
        return str(result.get("rationale", "")).strip() or written
