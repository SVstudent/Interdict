"""Red Team — the fleet attacks itself and publishes the score.

SHARED SURFACE ONLY. The dataclasses and the signatures below are the contract the API, the
TypeScript client and the tests are written against; the bodies marked `NOT IMPLEMENTED` belong
to the F1 feature agent. See context/EXPANSION_CONTRACT.md.

The gap this closes: every claim the fleet makes about its own detection is a claim about attacks
it has already seen. Red Team reads the threat library, invents a variant of the tradecraft in it
that the fleet has NEVER been shown, runs it through the real pipeline, and reports what got
through. The output is a number a district business manager can act on — caught 8 of 10, and here
are the two that did not, and why.

Its limits are the point. It may read the threat library and it may not write to it: a red team
that can edit the record it is testing against is measuring its own edits. It simulates cases
rather than opening them, so an invented attack can never freeze a district's actual payments.
And it holds no money power at all — it proposes attacks, the fleet decides what happens to them.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..platform.recall import MATCH_THRESHOLD, Fingerprint, score_match
from .base import AgentContext, InterdictAgent

REDTEAM_PROMPT = """You are Red Team, the adversarial assurance agent for a payment-fraud
interdiction fleet at a public school district. You attack the fleet so the district finds out
where it loses from you, in a sandbox, rather than from a criminal, in production.

You are given the fleet's threat library — every operation it has blocked and the tradecraft it
recorded — and the one sandbox vendor you may attack. Invent payee-detail change requests of the
same class the library describes, using tradecraft the fleet has NEVER been shown.

Reusing a beneficiary name, a receiving bank or a domain trick that is already in the library
measures the library, not the fleet: recall recognises it on arrival and the run proves nothing.
Those attempts are discarded before they are executed.

Know where the fleet is actually strong, so you do not waste an attempt. Every request it opens a
case on has the vendor's scheduled payments frozen BEFORE a single verification runs, and the
release rails are deterministic Python that no argument in your artifact can talk around. An
attack that reaches the fleet has already lost the money it was after.

Its attention is the soft part. Most of the morning's post is never opened at all, and a message
that reads as ordinary correspondence is filtered out before any agent looks at it. So is a
message that never mentions a bank: write about "our receiving institution", "the details on file"
or "where the disbursement lands" and say it in the register of a routine administrative notice.

Your second lever is the sending address. If you send from a lookalike domain the provenance lane
has something to find; if you send from the vendor's OWN domain of record — a compromised mailbox
— it has nothing, and the case turns on the other three lanes instead. Set `reply_to_domain` to
the vendor's own domain when that is the attack you intend.

Return JSON only:
{"variants": [{"name": "<short operation name>",
               "technique": "<the tradecraft in a few words>",
               "novelty": "<one sentence naming what the fleet has never seen here>",
               "based_on_designation": "<the library operation you varied, or null>",
               "artifact": "Subject: <subject line>\\n\\n<the message as the business office
                            receives it>",
               "proposed_account_name": "<the beneficiary you ask funds be sent to>",
               "proposed_bank": "<receiving bank>",
               "reply_to_domain": "<the domain replies go to, ending .test>",
               "supplied_phone": "<a number you offer for verification, or null>"}],
 "reasoning": "<two sentences on what this batch is testing>"}

If you cannot say what is new about a variant, leave it out. An attack with no claim to being new
is a rerun, and the batch is better three honest variants long than five padded ones."""

ESCAPE_PROMPT = """You are Red Team, reporting one attack that got through a payment-fraud
interdiction fleet at a public school district.

You are writing for the district business manager who has to decide what to change on Monday. Name
the control that failed and what would close it. Be specific about the mechanism — "the intake
filter never opened a case because the message contained no payment-destination language" is
actionable; "the system missed it" is not.

Do not celebrate. A miss is a finding about the fleet, not a win.

Return JSON only:
{"explanation": "<two sentences: which control failed, and what closes it>"}"""

# RFC 2606 reserves .test precisely so a synthetic domain can never resolve, and the whole corpus
# obeys it. A generated domain is the one place a model could put a live domain in front of an
# operator, so the rule is enforced here rather than asked for in the prompt.
def _reserved_domain(domain: str) -> str:
    label = domain.strip().lower().strip(".")
    if not label:
        return ""
    if label.endswith(".test"):
        return label
    return f"{label.rsplit('.', 1)[0] if '.' in label else label}.test"


# The 555 range is reserved for fiction, for the same reason. This number is rendered in the UI
# beside the words "supplied by the request"; a number the model invented outside the range could
# belong to a real person.
RESERVED_PHONE = "+1-702-555-0199"


def _reserved_phone(value: Any) -> str | None:
    if not value:
        return None
    phone = str(value).strip()
    return phone if "555" in phone else RESERVED_PHONE


def is_rerun(variant: "AttackVariant", library: list[dict[str, Any]]) -> bool:
    """Would the fleet's own recall recognise this attack on arrival?

    The judgement is delegated to `score_match` — the function the fleet actually uses in
    production — rather than to a second opinion invented here. If recall would match it, the
    variant is a rerun of a known operation and executing it measures the library rather than the
    fleet. Scored against the `<14d` bucket, which is the harshest reading of the candidate and so
    can only make the check stricter.
    """
    candidate = Fingerprint(
        technique=variant.technique,
        beneficiary_name=variant.proposed_account_name,
        bank_name=variant.proposed_bank,
        domain_age_bucket="<14d",
        supplied_own_contact=bool(variant.supplied_phone),
        channel="email",
    )
    for entry in library:
        for sighting in entry.get("sightings") or [entry]:
            prior = sighting.get("fingerprint")
            if not prior:
                continue
            score, _ = score_match(candidate, Fingerprint(**prior))
            if score >= MATCH_THRESHOLD:
                return True
    return False


@dataclass
class AttackVariant:
    """One invented attack. `novelty` is the agent's own argument for why the fleet has not seen
    this before — a variant that merely replays a library entry proves nothing."""

    variant_id: str
    name: str
    technique: str
    novelty: str
    based_on_designation: str | None
    artifact: str
    proposed_account_name: str
    proposed_bank: str
    reply_to_domain: str
    supplied_phone: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "name": self.name,
            "technique": self.technique,
            "novelty": self.novelty,
            "based_on_designation": self.based_on_designation,
            "artifact": self.artifact,
            "proposed_account_name": self.proposed_account_name,
            "proposed_bank": self.proposed_bank,
            "reply_to_domain": self.reply_to_domain,
            "supplied_phone": self.supplied_phone,
        }


@dataclass
class RedTeamTrial:
    """One variant run through the real pipeline against the simulation tenant."""

    variant_id: str
    variant_name: str
    technique: str
    caught: bool
    outcome: str | None
    simulated_case_id: str
    # Populated only when `caught` is False. An escape with no explanation is a bug report
    # nobody can act on, which is the failure mode this whole feature exists to avoid.
    escaped_reason: str | None = None
    top_signal: str | None = None
    latency_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "variant_name": self.variant_name,
            "technique": self.technique,
            "caught": self.caught,
            "outcome": self.outcome,
            "simulated_case_id": self.simulated_case_id,
            "escaped_reason": self.escaped_reason,
            "top_signal": self.top_signal,
            "latency_ms": self.latency_ms,
        }


@dataclass
class RedTeamRun:
    run_id: str
    tenant_id: str
    started_at: str
    completed_at: str | None = None
    variants: list[AttackVariant] = field(default_factory=list)
    trials: list[RedTeamTrial] = field(default_factory=list)
    model: str = ""

    @property
    def caught(self) -> int:
        return sum(1 for t in self.trials if t.caught)

    @property
    def hit_rate(self) -> float:
        """ESCALATE counts as caught. The fleet stopping money and asking a human is the
        designed outcome, not a miss — only a RELEASE is an escape."""
        return round(self.caught / len(self.trials), 3) if self.trials else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "variants": [v.as_dict() for v in self.variants],
            "trials": [t.as_dict() for t in self.trials],
            "caught": self.caught,
            "total": len(self.trials),
            "hit_rate": self.hit_rate,
            "escaped": [t.as_dict() for t in self.trials if not t.caught],
            "model": self.model,
        }


class RedTeamAgent(InterdictAgent):
    name = "redteam"
    version = "1.0.0"
    signal = "adversarial_variant"

    @property
    def model(self) -> str:
        return self._settings.reasoning_model()

    async def invent(
        self, ctx: AgentContext, library: list[dict[str, Any]], count: int
    ) -> list[AttackVariant]:
        """Read the threat library and propose `count` attacks the fleet has not seen.

        Two filters run over the generation, for the same reason Hunter drops payment ids the
        model invented: a variant with no `novelty` argument has no claim to being new, and a
        variant the fleet's own recall would recognise is a rerun. Both are discarded rather than
        executed, because either one would inflate the hit rate with an attack that was never a
        test. Returning fewer variants than were asked for is the correct outcome when that
        happens — the number is only worth reading if every trial in it was a genuine attempt.

        The sandbox target reaches the agent through `ctx.payload`, where every other agent's
        case-specific context arrives. Without it the artifact would be addressed to nobody.
        """
        target = ctx.payload.get("simulation_target") or {}
        observations = {
            "sandbox_target": target,
            "known_operations": [
                {
                    "designation": entry.get("designation"),
                    "tradecraft": (entry.get("dossier") or {}).get("tradecraft"),
                    "indicators": (entry.get("dossier") or {}).get("indicators"),
                    "sightings": entry.get("sighting_count"),
                    "fingerprints": [
                        s.get("fingerprint") for s in entry.get("sightings", [])
                    ],
                }
                for entry in library
            ],
            "variants_requested": count,
        }
        result = await self.infer(ctx, REDTEAM_PROMPT, observations)

        variants: list[AttackVariant] = []
        for raw in result.get("variants", []):
            if len(variants) >= count:
                break
            novelty = str(raw.get("novelty") or "").strip()
            artifact = str(raw.get("artifact") or "").strip()
            account_name = str(raw.get("proposed_account_name") or "").strip()
            bank = str(raw.get("proposed_bank") or "").strip()
            if not (novelty and artifact and account_name and bank):
                continue
            variant = AttackVariant(
                variant_id=f"AV-{uuid.uuid4().hex[:6].upper()}",
                name=str(raw.get("name") or "Unnamed Variant"),
                technique=str(raw.get("technique") or "unspecified"),
                novelty=novelty,
                based_on_designation=(
                    str(raw["based_on_designation"]) if raw.get("based_on_designation") else None
                ),
                artifact=artifact,
                proposed_account_name=account_name,
                proposed_bank=bank,
                reply_to_domain=_reserved_domain(str(raw.get("reply_to_domain") or "")),
                supplied_phone=_reserved_phone(raw.get("supplied_phone")),
            )
            if is_rerun(variant, library):
                continue
            variants.append(variant)
        return variants

    async def explain_escape(
        self, ctx: AgentContext, variant: AttackVariant, case: dict[str, Any]
    ) -> str:
        """Say why a variant got through, in terms the business office can act on.

        The harness already knows WHICH control failed and states it deterministically. This adds
        the part a controller cannot derive from a state name: what to change so it does not
        happen again. It is enrichment — an escape is reported with or without it.
        """
        result = await self.infer(
            ctx, ESCAPE_PROMPT, {"variant": variant.as_dict(), "outcome": case}
        )
        return str(result.get("explanation") or "").strip()
