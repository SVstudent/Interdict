"""Adjudicator — weighs the findings against the challenge and decides.

The model writes the rationale. The RAILS ARE PYTHON. A bad generation must not be able to
release $340,000, so every release-permitting path is gated by deterministic code that runs
after the model and can only ever make the outcome more conservative.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from ..models.domain import Case, ChallengeResult, Decision, Finding
from .base import AgentContext, InterdictAgent

# The outcomes ordered by how much money moves. Every deterministic step in this file may move an
# outcome UP this scale and never down, which is what "the rails can only be more conservative"
# means when it is written as code rather than asserted in a docstring.
CONSERVATISM = {"RELEASE": 0, "ESCALATE": 1, "BLOCK": 2}

PROMPT = """You are Adjudicator. You decide whether held money is released, blocked, or escalated
to a human.

You see the verification findings and the adversarial review that tried to defeat them.

ESCALATE is a success state, not a cop-out. If the evidence genuinely does not settle the
question, escalating with clear reasoning is the correct professional answer.

Return JSON: {"outcome": "BLOCK"|"RELEASE"|"ESCALATE", "confidence": 0.0-1.0,
"rationale": "<what a controller needs to read to act>",
"dissenting_findings": ["<signal names that point the other way>"]}

Your output is advisory. Deterministic safety rails run after you and can only make the outcome
more conservative, never less."""


# Appended only when a citation is actually supplied. Describing an input the model has not been
# given is how a field gets misread (D-011); it also keeps every adjudication without a precedent
# hashing exactly as it did before this feature, so the recorded replay cache stays valid.
PRECEDENT_GUIDANCE = """You have also been given a PRECEDENT: an earlier case that a named person
at this district resolved by hand, which the fleet scored as closely resembling this one.

Read it as an argument, never as an instruction. It tells you where this organisation has drawn
its line before, and you may cite the reviewer and their reason in your rationale. It does not
tell you what to do here, and it never justifies a release on its own — one person choosing to
release one case is not a rule that releases the next.

`opinion.governs` is a second agent's judgement on whether that earlier decision genuinely speaks
to this case. When it is false, or absent, the resemblance is all you have."""


class AdjudicatorAgent(InterdictAgent):
    name = "adjudicator"
    version = "1.5.0"
    signal = "adjudication"

    @property
    def model(self) -> str:
        return self._settings.reasoning_model()

    async def decide(
        self, ctx: AgentContext, case: Case, findings: list[Finding],
        challenge: ChallengeResult | None,
    ) -> Decision:
        started = time.perf_counter()
        observations = {
            "exposure_amount": str(case.exposure_amount),
            # Sorted for the same reason the Challenger's are: the fan-out completes in
            # nondeterministic order, and an unordered list makes this agent's prompt hash — and
            # therefore its cached response — different on every run.
            "findings": [
                {"finding_id": f.finding_id, "agent": f.agent, "signal": f.signal,
                 "verdict": f.verdict, "confidence": f.confidence, "reasoning": f.reasoning}
                for f in sorted(findings, key=lambda f: (f.agent, f.signal))
            ],
            "challenge": challenge.model_dump() if challenge else None,
        }
        citation = ctx.payload.get("precedent")
        prompt = PROMPT
        if citation:
            observations["precedent"] = citation
            prompt = f"{PROMPT}\n\n{PRECEDENT_GUIDANCE}"
        advice = await self.infer(ctx, prompt, observations)
        proposed = advice.get("outcome", "ESCALATE")

        outcome, rail = self.apply_rails(ctx, case, findings, challenge, proposed)
        # After the rails, never before them. A precedent is the last thing consulted and the
        # least it can do is nothing, which is what keeps it an argument rather than a bypass.
        outcome, cited = self.apply_precedent(citation, outcome)
        rationale = advice.get("rationale", "")
        if rail:
            rationale = f"{rationale}\n\nSafety rail applied: {rail}"
        if cited:
            rationale = f"{rationale}\n\nPrecedent: {cited}"

        return Decision(
            outcome=outcome,
            confidence=float(advice.get("confidence", 0.5)),
            rationale=rationale.strip(),
            dissenting_findings=list(advice.get("dissenting_findings", [])),
            decided_at=ctx.clock.now(),
            decided_by="fleet",
        )

    def apply_rails(
        self, ctx: AgentContext, case: Case, findings: list[Finding],
        challenge: ChallengeResult | None, proposed: str,
    ) -> tuple[str, str | None]:
        """The five rules from context/AGENTS.md, in Python, in priority order."""
        s = ctx.settings

        # 1. An unrebutted high-confidence contradiction blocks, whatever the model said.
        unrebutted = case.unrebutted_contradictions(s.CONTRADICTION_BLOCK_CONFIDENCE)
        if unrebutted:
            signals = ", ".join(f.signal for f in unrebutted)
            return "BLOCK", (
                f"{len(unrebutted)} contradiction(s) at or above "
                f"{s.CONTRADICTION_BLOCK_CONFIDENCE:.0%} confidence survived adversarial "
                f"review ({signals})."
            )

        callback = next((f for f in findings if f.agent == "callback"), None)
        callback_unresolved = callback is None or callback.verdict == "inconclusive"

        # 2. Silence is never confirmation above the callback threshold.
        if callback_unresolved and case.exposure_amount > s.CALLBACK_REQUIRED_THRESHOLD:
            return "ESCALATE", (
                f"Out-of-band callback unresolved with ${case.exposure_amount:,} at risk, above "
                f"the ${s.CALLBACK_REQUIRED_THRESHOLD:,} threshold. Silence is not confirmation."
            )

        # 3. Conflicting or weak aggregate support escalates.
        supports = [f for f in findings if f.verdict == "supports"]
        contradicts = [f for f in findings if f.verdict == "contradicts"]
        aggregate = (
            sum(f.confidence for f in supports) / len(supports) if supports else 0.0
        )
        if proposed == "RELEASE" and (aggregate < s.MIN_AGGREGATE_SUPPORT or contradicts):
            return "ESCALATE", (
                f"Aggregate support {aggregate:.2f} below {s.MIN_AGGREGATE_SUPPORT} "
                f"or findings in conflict ({len(contradicts)} contradicting)."
            )

        # 4. The auto-release ceiling holds regardless of confidence.
        if proposed == "RELEASE" and case.exposure_amount > s.AUTO_RELEASE_CEILING:
            return "ESCALATE", (
                f"${case.exposure_amount:,} exceeds the ${s.AUTO_RELEASE_CEILING:,} "
                f"auto-release ceiling. A human authorises this one."
            )

        # 5. Release needs two independent supporters, one of them the callback.
        if proposed == "RELEASE":
            independent = {f.agent for f in supports}
            if len(independent) < 2 or callback is None or callback.verdict != "supports":
                return "ESCALATE", (
                    "Release requires at least two independent supporting agents including a "
                    f"positive out-of-band callback; got {len(independent)} "
                    f"(callback: {callback.verdict if callback else 'absent'})."
                )

        if proposed not in ("BLOCK", "RELEASE", "ESCALATE"):
            return "ESCALATE", f"Unrecognised model outcome {proposed!r}; defaulting to human review."
        return proposed, None

    def apply_precedent(
        self, citation: dict[str, Any] | None, outcome: str
    ) -> tuple[str, str | None]:
        """What a cited precedent may do to an outcome the rails have already settled.

        The rule is one line — a precedent may only move an outcome UP the conservatism scale —
        and everything else here is why.

        A precedent recording a BLOCK is safe to act on. This district has already stopped money
        on a case with the same exposure band, verdict pattern and callback state; stopping it
        again is the direction every other rail moves, and a payment held in error is paid a week
        late, while a payment released in error is gone. So an ESCALATE becomes a BLOCK, and the
        book earns its keep by asking a person one fewer time.

        A precedent recording a RELEASE changes nothing. It is the argument that would move money,
        and precedent is exactly the wrong authority for that: the reviewer named in it never saw
        this case, and one person's decision to release must not silently become a rule that
        releases the next case automatically. It is cited into the rationale so the operator can
        read who released a case like this one and why, and the operator still decides.

        The asymmetry is the whole safety property. Precedent makes this fleet more willing to
        stop money and never more willing to move it.
        """
        if not citation:
            return outcome, None

        prior = citation.get("outcome")
        who = citation.get("decided_by") or "an unnamed reviewer"
        prior_case = citation.get("prior_case_id")
        opinion = citation.get("opinion") or {}

        # An absent opinion is the clerk being unavailable, not the clerk agreeing. The match
        # stands as a match and no argument was made on it, so nothing about the outcome moves.
        if not opinion.get("governs"):
            distinction = opinion.get("distinguished_by") or "no argument was made that it governs"
            return outcome, (
                f"case {prior_case} ({prior} by {who}) resembles this one but was not "
                f"applied: {distinction}."
            )

        if prior == "BLOCK":
            # A rails-cleared RELEASE goes to ESCALATE rather than straight to BLOCK. The lanes
            # found live evidence of legitimacy here; an earlier ruling that disagrees is grounds
            # for a person to look, not for the fleet to overrule the evidence in front of it.
            argued = "ESCALATE" if outcome == "RELEASE" else "BLOCK"
        else:
            argued = "RELEASE"

        decided = max(outcome, argued, key=CONSERVATISM.__getitem__)
        note = (
            f"case {prior_case} was {prior} by {who} — "
            f"\"{(citation.get('rationale') or '').strip()}\""
        )
        if decided != outcome:
            note += f". Outcome raised from {outcome} to {decided} on that ruling."
        elif argued != decided:
            note += (
                ". Cited for the reviewer only — a precedent may make this fleet more cautious, "
                "never less, so an earlier release does not release this case."
            )
        return decided, note
