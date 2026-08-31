"""Application state — one assembled object, injected everywhere.

Holds the repository, clock, platform bindings, agent fleet and the set of in-flight case tasks.
The in-flight registry is what makes `kill_runner` real: it cancels a running task mid-step
instead of broadcasting a message about a kill that never happened (DECISIONS D-001 F5).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .agents.adjudicator import AdjudicatorAgent
from .agents.base import AgentContext
from .agents.callback import CallbackAgent
from .agents.challenger import ChallengerAgent
from .agents.hunter import HunterAgent
from .agents.ledger import LedgerAgent
from .agents.precedent import PrecedentClerkAgent
from .agents.provenance import ProvenanceAgent
from .agents.redteam import RedTeamAgent
from .agents.registry_check import RegistryCheckAgent
from .agents.scribe import AttributionAgent, ScribeAgent
from .agents.sentry import SentryAgent
from .config import Clock, PlatformBackend, Settings, make_clock
from .demo.replay import ReplayCache
from .llm.provider import LLMProvider, build_provider
from .orchestrator.fanout import VerificationFanout
from .orchestrator.pipeline import build_pipeline
from .orchestrator.runner import CaseRunner, StepContext
from .platform.factory import Platform, build_platform
from .services.payments import PaymentService
from .store.base import Repository
from .store.memory import InMemoryRepository


@dataclass
class AppState:
    settings: Settings
    repo: Repository
    clock: Clock
    platform: Platform
    replay: ReplayCache
    payments: PaymentService
    llm: LLMProvider
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    inflight: dict[str, asyncio.Task] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    # Injections since the last reset. Makes request ids — and therefore case ids, finding
    # ids and every evidence locator built from them — repeat exactly across rehearsals of the
    # same beat order, which is what lets replay mode serve a whole case. Reset clears it.
    injection_seq: int = 0
    # Where the morning's post comes from. Built once at startup so a real mailbox
    # holds one connection policy rather than one per request.
    mailbox: Any = None
    agents: dict[str, Any] = field(default_factory=dict)

    # --- events ------------------------------------------------------------------
    async def emit(self, event: str, data: dict[str, Any]) -> None:
        payload = {"event": event, "data": data, "at": self.clock.now().isoformat()}
        for queue in list(self.subscribers):
            queue.put_nowait(payload)

    # --- agent wiring --------------------------------------------------------------
    def agent_ctx(self, ctx: StepContext, agent_name: str) -> AgentContext:
        request_id = ctx.case.request_id
        return AgentContext(
            case_id=ctx.case.case_id,
            repo=self.repo,
            clock=self.clock,
            settings=self.settings,
            replay=self.replay,
            telemetry=self.platform.telemetry,
            llm=self.llm,
            payload={
                "request_id": request_id,
                "vendor_id": ctx.case.vendor_id,
                **ctx.payload,
            },
        )

    def agent_ctx_for_request(self, request: Any, case_id: str = "") -> AgentContext:
        """Agent context outside a running case — used by Sentry at intake and by the
        scope-violation probe."""
        return AgentContext(
            case_id=case_id or (request.request_id if request is not None else "unassigned"),
            repo=self.repo,
            clock=self.clock,
            settings=self.settings,
            replay=self.replay,
            telemetry=self.platform.telemetry,
            llm=self.llm,
            payload={"request_id": request.request_id} if request is not None else {},
        )

    def build_runner(self) -> CaseRunner:
        verification = {
            name: self.agents[name]
            for name in ("callback", "ledger", "provenance", "registry-check")
        }
        fanout = VerificationFanout(verification, self.agent_ctx)

        async def challenge(ctx: StepContext, findings):
            await self.platform.gateway.route("orchestrator", "challenger", {})
            return await self.agents["challenger"].review(
                self.agent_ctx(ctx, "challenger"), findings
            )

        async def attribute(ctx: StepContext, dossier, match, request_summary):
            return await self.agents["attribution"].attribute(
                self.agent_ctx(ctx, "attribution"), dossier, match, request_summary
            )

        async def scribe(ctx: StepContext, case):
            return await self.agents["scribe"].write_dossier(
                self.agent_ctx(ctx, "scribe"), case
            )

        async def hunt(ctx: StepContext, dossier, case):
            # Exclude the vendor we just interdicted: their payments are already held by
            # this case, and re-freezing them would double-count the exposure.
            return await self.agents["hunter"].sweep(
                self.agent_ctx(ctx, "hunter"), dossier, case.case_id,
                {case.vendor_id} if case.vendor_id else set(), case.tenant_id,
            )

        async def cite_precedent(ctx: StepContext, case):
            """The deterministic half of precedent: reduce the case to its four
            characteristics and ask the book. Built here rather than in the pipeline because the
            exposure bands a precedent keys on ARE the adjudication thresholds."""
            from .platform.precedent import key_from_case

            vendor = await self.repo.get_vendor(case.vendor_id) if case.vendor_id else None
            key = key_from_case(
                case, vendor, now=self.clock.now(),
                callback_threshold=self.settings.CALLBACK_REQUIRED_THRESHOLD,
                release_ceiling=self.settings.AUTO_RELEASE_CEILING,
            )
            matches = await self.platform.precedent.match(key, case.tenant_id)
            if not matches:
                return None
            top = matches[0]
            citation = top.as_dict()

            # The retrieval is deterministic; whether the earlier decision actually SPEAKS to
            # this case is a judgement, so an agent argues it. If the model is unavailable the
            # match still stands as a match and the adjudicator weighs it unaided.
            try:
                opinion = await self.agents["precedent-clerk"].opine(
                    self.agent_ctx(ctx, "precedent-clerk"), citation,
                    {
                        "case_id": case.case_id,
                        "vendor_id": case.vendor_id,
                        "exposure_amount": str(case.exposure_amount),
                        "findings": [
                            {"agent": f.agent, "verdict": f.verdict,
                             "confidence": f.confidence, "reasoning": f.reasoning}
                            for f in case.findings
                        ],
                    },
                )
                citation["opinion"] = opinion.as_dict()
            except Exception as exc:  # noqa: BLE001
                await self.emit("precedent_unavailable", {
                    "case_id": case.case_id, "error": repr(exc)[:200],
                })
            # Absent opinion defaults to NOT governing, the same way the adjudicator reads it.
            # This defaulted the other way and the two halves of the feature disagreed: the
            # adjudicator correctly declined to apply a precedent the clerk never argued, while
            # the book recorded the case as having leaned on it anyway. `cited_by_case_ids` is
            # the audit answer to "which decisions did this ruling shape", so it may only carry
            # cases the ruling actually shaped.
            if citation.get("opinion", {}).get("governs"):
                await self.platform.precedent.cite(top.precedent_id, case.case_id)
            return citation

        async def adjudicate(ctx: StepContext, findings, challenge_result):
            await self.platform.gateway.route("orchestrator", "adjudicator", {})
            return await self.agents["adjudicator"].decide(
                self.agent_ctx(ctx, "adjudicator"), ctx.case, findings, challenge_result
            )

        return CaseRunner(
            repo=self.repo,
            clock=self.clock,
            steps=build_pipeline(
                self.payments, fanout, challenge, adjudicate,
                recall=self.platform.recall, memory=self.platform.memory,
                attribute=attribute, scribe=scribe, hunt=hunt,
                precedent=cite_precedent, exchange=self.platform.exchange,
            ),
            emit=self.emit,
        )

    # --- in-flight control ---------------------------------------------------------
    def track(self, case_id: str, task: asyncio.Task) -> None:
        self.inflight[case_id] = task
        task.add_done_callback(lambda _: self.inflight.pop(case_id, None))

    def kill(self, case_id: str | None = None) -> list[str]:
        """Cancel in-flight work. Genuinely cancels the task mid-step."""
        targets = [case_id] if case_id else list(self.inflight)
        killed: list[str] = []
        for cid in targets:
            task = self.inflight.get(cid)
            if task and not task.done():
                task.cancel()
                killed.append(cid)
        return killed


class _UnconfiguredProvider:
    """Stands in when no key is present. Raises only if something tries to call a model,
    so `DEMO_MODE=replay` still boots with no credentials at all."""

    from .llm.provider import Provider as _P

    name = _P.GEMINI

    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def complete(self, **_: object):
        raise RuntimeError(self._reason)


def _safe_provider(settings: Settings):
    try:
        return build_provider(settings)
    except RuntimeError as exc:
        return _UnconfiguredProvider(str(exc))


def _safe_mailbox(settings):
    """Never let mailbox configuration stop the service starting."""
    from .platform.mailbox import SeededMailbox, build_mailbox

    try:
        return build_mailbox(settings)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("interdict").warning(
            "inbox source %r unavailable (%s); using the seeded inbox",
            getattr(settings, "INBOX_SOURCE", "seed"), exc,
        )
        return SeededMailbox()


def build_state(settings: Settings | None = None, repo: Repository | None = None) -> AppState:
    settings = settings or Settings()
    if repo is None:
        if settings.PLATFORM_BACKEND is PlatformBackend.GEAP or settings.FIRESTORE_EMULATOR_HOST:
            from .store.firestore import FirestoreRepository

            repo = FirestoreRepository(
                settings.GCP_PROJECT_ID or "interdict-local", settings.FIRESTORE_DATABASE
            )
        else:
            repo = InMemoryRepository()

    clock = make_clock(settings)
    state = AppState(
        settings=settings,
        repo=repo,
        clock=clock,
        platform=build_platform(settings, repo),
        replay=ReplayCache(repo, settings),
        payments=PaymentService(repo, clock),
        # Constructed lazily-safe: replay mode never calls it, so a missing key is only an
        # error at the moment a real model call is actually attempted.
        llm=_safe_provider(settings),
        # `seed` unless INBOX_SOURCE says otherwise. A misconfigured real mailbox degrades to the
        # fixtures rather than raising, so a bad app password cannot stop the service booting.
        mailbox=_safe_mailbox(settings),
    )
    state.agents = {
        "sentry": SentryAgent(settings),
        "callback": CallbackAgent(settings),
        "ledger": LedgerAgent(settings),
        "provenance": ProvenanceAgent(settings),
        "registry-check": RegistryCheckAgent(settings),
        "challenger": ChallengerAgent(settings),
        "adjudicator": AdjudicatorAgent(settings),
        "scribe": ScribeAgent(settings),
        "attribution": AttributionAgent(settings),
        "hunter": HunterAgent(settings),
        "redteam": RedTeamAgent(settings),
        "precedent-clerk": PrecedentClerkAgent(settings),
    }
    return state
