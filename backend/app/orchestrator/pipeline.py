"""The case pipeline: the ordered steps a case moves through.

Agent work is injected as callables. In Phase 1 the tests supply deterministic ones; in Phase 2 the
ADK fleet is supplied instead, with no change to the state machine. That separation is deliberate —
the state machine is the piece §15 says must never be parallelised or improvised.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..models.domain import (
    Case,
    EvidenceRef,
    CaseState,
    ChallengeResult,
    Decision,
    Finding,
)
from ..services.payments import PaymentService
from .runner import StepContext, StepOutcome

# Injected agent work.
FanoutFn = Callable[[StepContext], Awaitable[list[Finding]]]
ChallengeFn = Callable[[StepContext, list[Finding]], Awaitable[ChallengeResult]]
AdjudicateFn = Callable[
    [StepContext, list[Finding], ChallengeResult | None], Awaitable[Decision]
]
# Returns the precedent this case may cite, already scored, or None. Built where the
# adjudication thresholds live, because the exposure bands a precedent keys on ARE those
# thresholds — see models/domain.py::exposure_band.
PrecedentFn = Callable[[StepContext, Case], Awaitable[dict[str, Any] | None]]

CALLBACK_AGENT = "callback"


@dataclass
class HoldStep:
    """Sentry's side effect: freeze the vendor's scheduled payments and fix exposure."""

    payments: PaymentService
    name: str = "hold_payments"

    def applies_to(self, state: CaseState) -> bool:
        return state is CaseState.OPENED

    def input_for(self, ctx: StepContext) -> Any:
        return {"case_id": ctx.case.case_id, "vendor_id": ctx.case.vendor_id}

    async def run(self, ctx: StepContext) -> StepOutcome:
        case = ctx.case
        if case.vendor_id is None:
            # An unresolvable vendor is a signal, not an error. Hold nothing, carry on; the
            # fleet will weigh the fact that the request matched no known vendor.
            return StepOutcome(CaseState.HELD, {"held": [], "exposure": "0"})
        result = await self.payments.hold_scheduled_payments(case, case.vendor_id)
        await ctx.emit(
            "payments_held",
            {
                "case_id": case.case_id,
                "count": len(result.payment_ids),
                "exposure": str(case.exposure_amount),
                "replayed": result.replayed,
            },
        )
        return StepOutcome(
            CaseState.HELD,
            {"held": result.payment_ids, "exposure": str(case.exposure_amount)},
        )


@dataclass
class BeginVerificationStep:
    name: str = "begin_verification"

    def applies_to(self, state: CaseState) -> bool:
        return state in (CaseState.HELD, CaseState.AWAITING_CALLBACK)

    def input_for(self, ctx: StepContext) -> Any:
        # State is part of the input so waking a dormant case is genuinely different work
        # from opening it, and is not skipped as already-done.
        return {"case_id": ctx.case.case_id, "from": ctx.case.state.value}

    async def run(self, ctx: StepContext) -> StepOutcome:
        return StepOutcome(CaseState.VERIFYING, {"entered": "verifying"})


@dataclass
class RecallStep:
    """Check the incoming request against the fleet's accumulated threat memory.

    Runs BEFORE the verification lanes, for two reasons. First, a recognised repeat attacker is
    the single highest-value signal available and the operator should see it immediately rather
    than after four lanes finish. Second, the result shapes delegation: a recognised fingerprint
    marks the case for the full lane set and raises its priority, while a clean recall leaves the
    normal path untouched.

    Deterministic by design. This is a database match over structured tradecraft, not a judgement,
    so it costs no tokens and cannot hallucinate a prior case that does not exist.
    """

    recall: Any
    memory: Any
    # Injected so the state machine stays decoupled from the fleet, as with the other steps.
    attribute: Any = None
    # The cross-tenant threat exchange. Consulted only when the fleet's OWN memory has nothing,
    # because a district's own prior case is always the better citation: the operator can pull
    # the file, and it needs no explanation of where the intelligence came from.
    exchange: Any = None
    name: str = "recall_prior_art"

    def applies_to(self, state: CaseState) -> bool:
        return state is CaseState.VERIFYING

    def input_for(self, ctx: StepContext) -> Any:
        return {"case_id": ctx.case.case_id, "request_id": ctx.case.request_id}

    async def run(self, ctx: StepContext) -> StepOutcome:
        from ..platform.recall import fingerprint_from_request

        request = await ctx.repo.get_request(ctx.case.request_id)
        vendor = (
            await ctx.repo.get_vendor(ctx.case.vendor_id) if ctx.case.vendor_id else None
        )
        if request is None:
            return StepOutcome(CaseState.VERIFYING, {"skipped": "no request"})

        meta = request.artifact_metadata
        reply_to = str(meta.get("reply_to", "")).rsplit("@", 1)[-1]
        vendor_domain = (
            vendor.contact_email_of_record.rsplit("@", 1)[-1] if vendor else ""
        )
        age = meta.get("reply_to_domain_registered_at")
        age_days = (ctx.clock.now() - age).days if age is not None else None

        fp = fingerprint_from_request(
            proposed_account_name=request.proposed_banking.account_name,
            proposed_bank=request.proposed_banking.bank_name,
            reply_to_domain=reply_to,
            vendor_domain=vendor_domain,
            domain_age_days=age_days,
            supplied_phone=meta.get("supplied_phone"),
            channel=request.channel,
        )
        # Scoped to the district. An unscoped lookup would let Harborview satisfy its recall from
        # Riverbend's own memory, which both short-circuits the exchange branch below and renders
        # another district's case id and victim vendor on this district's screen.
        matches = await self.recall.recall(fp, ctx.case.tenant_id)

        # Nothing in our own memory. Ask the districts we share an exchange with — this is the
        # first-contact case the exchange exists for, where the operator has never met these
        # attackers and another district already has.
        exchange_hit = None
        if not matches and self.exchange is not None:
            from ..platform.recall import RecallMatch

            hits = await self.exchange.lookup(fp, ctx.case.tenant_id)
            if hits:
                exchange_hit = hits[0]
                matches = [RecallMatch(
                    prior_case_id=exchange_hit.prior_case_id,
                    # None on purpose. The exchange carries tradecraft, never the victim: a
                    # district sharing intelligence must not be publishing its supplier list.
                    prior_vendor_id=None,
                    prior_outcome="BLOCK",
                    score=exchange_hit.score,
                    matched_on=exchange_hit.matched_on,
                    fingerprint=exchange_hit.fingerprint,
                    dossier=exchange_hit.dossier,
                )]

        ctx.payload["recall_matches"] = [m.as_dict() for m in matches]
        ctx.payload["fingerprint"] = fp.as_dict()

        if matches:
            top = matches[0]

            # The retrieval above is deterministic. The JUDGEMENT is not: deciding that a new
            # request belongs to a named operation is attribution, and attribution is the kind of
            # call that needs reasoning and needs to be arguable. So an agent reads the dossier
            # Scribe wrote and argues for or against, sceptically.
            verdict = "contradicts"
            confidence = min(0.99, 0.60 + top.score * 0.35)
            reasoning = (
                f"This request reuses tradecraft the fleet blocked in case "
                f"{top.prior_case_id}, on a different vendor. Matched on: "
                f"{'; '.join(top.matched_on)}."
            )
            same_operator = True

            if self.attribute is not None:
                try:
                    call = await self.attribute(
                        ctx,
                        top.dossier,
                        top.as_dict(),
                        {
                            "vendor_id": ctx.case.vendor_id,
                            "exposure_amount": str(ctx.case.exposure_amount),
                            "proposed_account_name":
                                request.proposed_banking.account_name,
                            "proposed_bank": request.proposed_banking.bank_name,
                            "reply_to_domain": reply_to,
                            "vendor_domain_of_record": vendor_domain,
                            "domain_age_days": age_days,
                            "channel": request.channel,
                            "claimed_reason": request.claimed_reason,
                        },
                    )
                    verdict = call.get("verdict", verdict)
                    confidence = float(call.get("confidence", confidence))
                    reasoning = call.get("reasoning") or reasoning
                    same_operator = bool(call.get("same_operator", same_operator))
                except Exception as exc:  # noqa: BLE001
                    # Attribution is an enrichment, not a gate. If the model is unavailable the
                    # deterministic match still stands on its own and the case proceeds.
                    await ctx.emit("attribution_unavailable", {
                        "case_id": ctx.case.case_id, "error": repr(exc)[:200],
                    })

            designation = top.designation
            source = "shared_threat_exchange" if exchange_hit else "fleet_threat_library"
            evidence = [
                EvidenceRef(
                    source=source,
                    locator=f"{designation} ({top.prior_case_id})",
                    excerpt="; ".join(top.matched_on),
                ),
                EvidenceRef(
                    source=source,
                    locator="prior outcome",
                    excerpt=(
                        f"case {top.prior_case_id}, contributed to the exchange by "
                        f"{exchange_hit.contributed_by_tenant_id}, was BLOCK"
                        if exchange_hit else
                        f"case {top.prior_case_id} on vendor "
                        f"{top.prior_vendor_id} was {top.prior_outcome}"
                    ),
                ),
            ]
            predicted = (top.dossier or {}).get("likely_next_target")
            if predicted:
                # If the dossier predicted this, say so. It is the strongest possible
                # demonstration that the memory is doing work.
                evidence.append(EvidenceRef(
                    source=source,
                    locator=f"{designation} — predicted next target",
                    excerpt=predicted,
                ))

            finding = Finding(
                finding_id="F-attribution",
                agent="attribution",
                agent_version="1.0.0",
                signal="known_operation_recognised" if same_operator
                       else "resemblance_not_attributed",
                verdict=verdict,
                confidence=confidence,
                evidence=evidence if verdict != "inconclusive" else [],
                reasoning=reasoning,
                latency_ms=0,
            )
            existing = {f.finding_id for f in ctx.case.findings}
            if finding.finding_id not in existing:
                ctx.case.findings.append(finding)
                await ctx.repo.save_case(ctx.case)
            await ctx.emit("finding_added", {
                "case_id": ctx.case.case_id, **finding.model_dump(mode="json")
            })
            await ctx.emit("recall_hit", {
                "case_id": ctx.case.case_id,
                "designation": designation,
                "same_operator": same_operator,
                "score": top.score,
                "matched_on": top.matched_on,
                "prior_case_id": top.prior_case_id,
                "dossier": top.dossier,
                "matches": ctx.payload["recall_matches"],
            })
            if exchange_hit is not None:
                await self.exchange.note_recognition(
                    ctx.case.tenant_id, ctx.case.case_id, exchange_hit,
                    ctx.clock.now().isoformat(),
                )
                await ctx.emit("exchange_recognised", {
                    "case_id": ctx.case.case_id,
                    "tenant_id": ctx.case.tenant_id,
                    **exchange_hit.as_dict(),
                })

            if ctx.case.session_id:
                await self.memory.append_event(
                    ctx.case.session_id, "recall_hit",
                    {"matches": ctx.payload["recall_matches"]},
                    ctx.clock.now().isoformat(),
                )

        return StepOutcome(
            CaseState.VERIFYING,
            {"match_count": len(matches), "fingerprint": fp.as_dict()},
        )


@dataclass
class FanoutStep:
    """The four verification lanes, run concurrently and tolerant of partial failure."""

    fanout: FanoutFn
    name: str = "fanout_verification"

    def applies_to(self, state: CaseState) -> bool:
        return state is CaseState.VERIFYING

    def input_for(self, ctx: StepContext) -> Any:
        return {
            "case_id": ctx.case.case_id,
            "request_id": ctx.case.request_id,
            # A returned callback makes this a different fan-out, so the dormant case that wakes
            # in beat 5 re-runs verification instead of replaying the unanswered result.
            "callback_response": ctx.payload.get("callback_response"),
            # So is a lapsed grace period. Without this in the checkpoint input, a case woken by
            # the scheduler hashes identically to the run that put it to sleep and is skipped as
            # already-done, so it can never leave AWAITING_CALLBACK.
            "callback_window_expired": bool(ctx.payload.get("callback_window_expired")),
        }

    async def run(self, ctx: StepContext) -> StepOutcome:
        findings = await self.fanout(ctx)

        # A re-run SUPERSEDES the previous finding from the same agent; it does not sit beside
        # it. Deduping by finding_id was wrong because every run mints a fresh id, so a woken
        # case kept its stale "callback: inconclusive" alongside the new "callback: supports".
        # `finding_by_agent` returns the first match, so the adjudicator read the stale one and
        # escalated a case the vendor had just confirmed. The superseded versions remain in the
        # checkpoint log and the audit record; the case carries each agent's current position.
        replaced = {f.agent for f in findings}
        ctx.case.findings = [
            f for f in ctx.case.findings if f.agent not in replaced
        ] + list(findings)
        await ctx.repo.save_case(ctx.case)

        callback = ctx.case.finding_by_agent(CALLBACK_AGENT)
        unresolved = callback is None or callback.verdict == "inconclusive"
        expired = bool(ctx.payload.get("callback_window_expired"))
        if unresolved and not ctx.payload.get("callback_response") and not expired:
            # Silence is never confirmation. The case goes dormant rather than proceeding.
            return StepOutcome(
                CaseState.AWAITING_CALLBACK,
                {"findings": [f.finding_id for f in findings], "awaiting_callback": True},
                suspend=True,
            )
        # Either the callback resolved, or its grace period lapsed and nobody called back. Both
        # proceed. A case that waited out the window carries an unresolved callback into
        # adjudication, which is what makes it ESCALATE rather than release — waiting forever is
        # not abstention, it is a stall.
        result: dict[str, Any] = {"findings": [f.finding_id for f in findings]}
        if expired:
            result["callback_window_expired"] = True
        return StepOutcome(CaseState.CHALLENGING, result)


@dataclass
class ChallengeStep:
    challenge: ChallengeFn
    name: str = "adversarial_challenge"

    def applies_to(self, state: CaseState) -> bool:
        return state is CaseState.CHALLENGING

    def input_for(self, ctx: StepContext) -> Any:
        return {
            "case_id": ctx.case.case_id,
            "findings": sorted(f.finding_id for f in ctx.case.findings),
        }

    async def run(self, ctx: StepContext) -> StepOutcome:
        result = await self.challenge(ctx, ctx.case.findings)
        ctx.case.challenge = result
        await ctx.repo.save_case(ctx.case)
        await ctx.emit(
            "challenge_completed",
            {"case_id": ctx.case.case_id, "survived": result.survived},
        )
        return StepOutcome(CaseState.ADJUDICATING, {"survived": result.survived})


@dataclass
class AdjudicateStep:
    adjudicate: AdjudicateFn
    payments: PaymentService
    recall: Any = None
    scribe: Any = None
    hunt: Any = None
    precedent: PrecedentFn | None = None
    exchange: Any = None
    name: str = "adjudication"

    def applies_to(self, state: CaseState) -> bool:
        return state is CaseState.ADJUDICATING

    def input_for(self, ctx: StepContext) -> Any:
        return {
            "case_id": ctx.case.case_id,
            "findings": sorted(f.finding_id for f in ctx.case.findings),
            "challenge": ctx.case.challenge.survived if ctx.case.challenge else None,
        }

    async def run(self, ctx: StepContext) -> StepOutcome:
        case = ctx.case

        # Ask the precedent book BEFORE adjudicating, so the adjudicator can read the citation
        # out of the payload. A precedent is an argument put to the adjudicator, never an
        # instruction: it lands next to the findings and the rails still run on top of it.
        if self.precedent is not None:
            try:
                citation = await self.precedent(ctx, case)
                if citation:
                    ctx.payload["precedent"] = citation
                    await ctx.emit("precedent_cited", {
                        "case_id": case.case_id, **citation,
                    })
            except Exception as exc:  # noqa: BLE001
                # Enrichment, not a gate. An empty book and a broken book must both leave the
                # case deciding exactly as it did before precedent existed.
                await ctx.emit("precedent_unavailable", {
                    "case_id": case.case_id, "error": repr(exc)[:200],
                })

        decision = await self.adjudicate(ctx, case.findings, case.challenge)
        case.decision = decision

        if decision.outcome in ("RELEASE", "BLOCK"):
            result = await self.payments.finalize(case, decision.outcome)
            await ctx.emit(
                "payments_finalized",
                {
                    "case_id": case.case_id,
                    "action": decision.outcome,
                    "total": str(result.total),
                    "replayed": result.replayed,
                },
            )

        # Learn from it. A blocked attempt is the only outcome worth remembering as tradecraft:
        # remembering a release would teach the fleet to distrust legitimate behaviour.
        if self.recall is not None and decision.outcome == "BLOCK":
            fp_dict = ctx.payload.get("fingerprint")
            if fp_dict:
                from ..platform.recall import Fingerprint

                # Scribe turns the case into an intelligence product: a named operation with
                # tradecraft, indicators and a predicted next target. That dossier is what a
                # later case is attributed against, so the memory reasons rather than matches.
                # Ordering note: Scribe runs on the reasoning model and adds several seconds.
                # It executes AFTER the decision and the payment action are already committed, so
                # a slow or failed dossier cannot delay an interdiction or the verdict the
                # operator is waiting on.
                dossier: dict[str, Any] = {}
                if self.scribe is not None and not ctx.payload.get("recall_matches"):
                    try:
                        dossier = await self.scribe(ctx, case)
                        await ctx.emit("dossier_written", {
                            "case_id": case.case_id,
                            "designation": dossier.get("designation"),
                            "dossier": dossier,
                        })
                    except Exception as exc:  # noqa: BLE001
                        # A missing dossier degrades recall to structured matching. It must never
                        # prevent the block from being recorded.
                        await ctx.emit("scribe_unavailable", {
                            "case_id": case.case_id, "error": repr(exc)[:200],
                        })
                elif ctx.payload.get("recall_matches"):
                    # Already a known operation — inherit its dossier rather than renaming it.
                    dossier = (ctx.payload["recall_matches"][0] or {}).get("dossier") or {}

                await self.recall.remember(
                    case.case_id, case.vendor_id, "BLOCK",
                    Fingerprint(**fp_dict), dossier, case.tenant_id,
                )

                # Publish the tradecraft to the districts we share an exchange with. The
                # fingerprint already excludes the vendor and the domain, so what leaves this
                # tenant is the method and nothing about who it was used against.
                if self.exchange is not None:
                    entry_id = await self.exchange.publish(
                        case.tenant_id, case.case_id, Fingerprint(**fp_dict), dossier,
                        ctx.clock.now().isoformat(),
                    )
                    await ctx.emit("exchange_published", {
                        "case_id": case.case_id,
                        "tenant_id": case.tenant_id,
                        "entry_id": entry_id,
                        "designation": dossier.get("designation"),
                    })

                # Having named the operation, go looking for its other targets. This runs after
                # the interdiction is committed, so a slow or empty sweep never delays the
                # decision the operator is waiting on.
                if self.hunt is not None and dossier:
                    try:
                        sweep = await self.hunt(ctx, dossier, case)
                        if sweep and sweep.targets:
                            result = await self.payments.freeze_proactively(
                                [t.payment_id for t in sweep.targets],
                                case.case_id, sweep.designation,
                            )
                            payload = {
                                "event_id": f"SW-{case.case_id}",
                                "kind": "proactive_sweep",
                                "occurred_at": ctx.clock.now().isoformat(),
                                "case_id": case.case_id,
                                **sweep.as_dict(),
                                "frozen": result.payment_ids,
                                "frozen_total": str(result.total),
                            }
                            await ctx.repo.append_posture_event(payload)
                            await ctx.emit("sweep_completed", payload)
                        elif sweep:
                            await ctx.emit("sweep_completed", {
                                "case_id": case.case_id, **sweep.as_dict(),
                                "frozen": [], "frozen_total": "0",
                            })
                    except Exception as exc:  # noqa: BLE001
                        await ctx.emit("sweep_unavailable", {
                            "case_id": case.case_id, "error": repr(exc)[:200],
                        })
                await ctx.emit("fingerprint_recorded", {
                    "case_id": case.case_id,
                    "designation": dossier.get("designation"),
                    "fingerprint": fp_dict,
                })

        next_state = {
            "RELEASE": CaseState.RELEASED,
            "BLOCK": CaseState.BLOCKED,
            "ESCALATE": CaseState.ESCALATED,
        }[decision.outcome]
        await ctx.repo.save_case(case)
        await ctx.emit(
            "decision_rendered",
            {"case_id": case.case_id, "outcome": decision.outcome},
        )
        return StepOutcome(next_state, {"outcome": decision.outcome})


def build_pipeline(
    payments: PaymentService,
    fanout: FanoutFn,
    challenge: ChallengeFn,
    adjudicate: AdjudicateFn,
    recall: Any = None,
    memory: Any = None,
    attribute: Any = None,
    scribe: Any = None,
    hunt: Any = None,
    precedent: PrecedentFn | None = None,
    exchange: Any = None,
) -> list[Any]:
    steps: list[Any] = [
        HoldStep(payments=payments),
        BeginVerificationStep(),
    ]
    if recall is not None:
        # Before the lanes: a recognised attacker should be the first thing on screen.
        steps.append(RecallStep(recall=recall, memory=memory, attribute=attribute,
                                exchange=exchange))
    steps += [
        FanoutStep(fanout=fanout),
        ChallengeStep(challenge=challenge),
        AdjudicateStep(adjudicate=adjudicate, payments=payments, recall=recall,
                       scribe=scribe, hunt=hunt, precedent=precedent, exchange=exchange),
    ]
    return steps
