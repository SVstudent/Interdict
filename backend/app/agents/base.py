"""Base class for every agent in the fleet.

Responsibilities, in the order they matter:
  1. Enforce identity scopes before a tool body runs, and emit a posture event on denial.
  2. Emit an OpenTelemetry span per step carrying the full attribute set from PLATFORM.md.
  3. Route model calls through the replay cache so rehearsal and CI are deterministic and offline.
  4. Return a validated Finding — a hallucinated verdict with no evidence cannot survive
     construction, which is the fleet's answer to "how do you recover from a hallucination?"
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..config import Clock, Settings
from ..demo.replay import ReplayCache, prompt_hash
from ..llm.provider import Completion, LLMProvider
from ..models.domain import EvidenceRef, Finding
from ..platform.telemetry import Telemetry
from ..store.base import Repository
from .adk_runtime import infer_via_adk
from .scopes import FLEET_SCOPES, ScopeViolation
from .tools import TOOL_SPECS


# The single definition of what a verdict MEANS.
#
# Empirically necessary. With the earlier prompts, which named the enum values without defining
# them, Gemini 3.6 and 3.7 both returned "supports" for blatant fraud evidence AND for clean
# evidence — reading "supports" as "supports my analysis" rather than "supports the legitimacy of
# the request". Since the Adjudicator counts `supports` toward RELEASE, an inverted verdict
# releases money to an attacker. Never paraphrase this block per-agent; import it.
VERDICT_RUBRIC = """
YOUR VERDICT ANSWERS EXACTLY ONE QUESTION:
Does the evidence support the LEGITIMACY of this payee-detail change request?

  "supports"      the evidence indicates the request is GENUINE. Money may move.
  "contradicts"   the evidence indicates the request is FRAUDULENT. Money must be stopped.
  "inconclusive"  the evidence does not settle the question either way.

The verdict is about the REQUEST, never about your confidence in your own analysis.
If you found fraud indicators, the verdict is "contradicts" — not "supports".
If you found nothing either way, "inconclusive" is the correct and expected answer;
abstaining is a success state, not a failure.

`confidence` is how sure you are OF YOUR VERDICT, from 0.0 to 1.0.

Return JSON only:
{"verdict": "supports"|"contradicts"|"inconclusive",
 "confidence": 0.0-1.0,
 "reasoning": "<two sentences a payments controller can act on>"}
"""


# How every agent is told to treat the tools its identity grants it.
#
# The tools are declared to the model for a reason: an agent that cannot ask a question can only
# recall one. But the fan-out already gathers each agent's observations deterministically before
# it reasons, so the common case is that the answer is already on the page. Without this block the
# models re-fetched what they had just been handed, and each redundant call is a full extra
# round-trip: it pushed beat 2 from ~50s to over 80s and blew the runbook's 70s budget.
#
# It is appended to the agent's own prompt and hashed with it, so a cached response can never be
# served for an instruction the model did not actually receive.
TOOL_PROTOCOL = """
TOOLS
The observations below were already gathered for you by the fleet, deterministically, before you
were asked anything. They are the evidence of record. In almost every case they are sufficient
and you should answer directly from them.

You also hold tools your identity permits. Call one ONLY to resolve a specific question the
observations genuinely leave open. Do not call a tool to re-fetch or re-confirm a value that
already appears in the observations.

If a tool returns {"error": "scope_denied"}, your identity is forbidden that data by policy.
That is a correct and expected outcome, not a failure to work around. Record what you could not
see and reason from what you have.
"""


# Appended to the instruction on ONE repair attempt when the model's reply will not parse.
#
# These are thinking models with tools: a step can end having spent its output on reasoning and a
# tool call and emitted no final text at all, or emitted a sentence of prose around the JSON. That
# is a formatting miss, not a failure of judgment, and re-asking costs a few seconds where giving
# up costs the case. One attempt only — a model that cannot produce JSON twice is not going to on
# the third try, and a demo that silently loops is worse than one that fails loudly.
REPAIR_SUFFIX = """

FORMAT CORRECTION
Your previous reply could not be parsed as JSON. Reply again with the SAME judgment, as a single
raw JSON object and nothing else. No markdown fence, no commentary before or after, no trailing
text. Begin your reply with { and end it with }.
"""


class MalformedModelOutput(RuntimeError):
    """The model's reply could not be parsed as JSON, twice.

    Carries the raw text so a failure during a recording is diagnosable from the log rather than
    from a bare JSONDecodeError several frames later.
    """

    def __init__(self, agent: str, model: str, raw: str) -> None:
        super().__init__(
            f"{agent} on {model} returned unparseable output after a repair attempt. "
            f"Raw reply (truncated): {raw[:400]!r}"
        )
        self.agent, self.model, self.raw = agent, model, raw


class AgentTimeout(RuntimeError):
    """A step exceeded its wall-clock budget. Loop containment, not a generic error."""


@dataclass
class AgentContext:
    case_id: str
    repo: Repository
    clock: Clock
    settings: Settings
    replay: ReplayCache
    telemetry: Telemetry
    llm: LLMProvider
    payload: dict[str, Any] = field(default_factory=dict)
    # Scope denials provoked by the MODEL during an ADK run. ADK's before_tool_callback is
    # synchronous and a posture event is an async repository write, so the callback queues
    # them here and `InterdictAgent._flush_denials` drains the queue.
    pending_denials: list[dict[str, Any]] = field(default_factory=list)


class InterdictAgent:
    name: str = "agent"
    version: str = "0.0.0"
    signal: str = "unspecified"
    # Wall-clock ceiling per step. A worker that loops is cut off rather than allowed to
    # stall the fan-out — Architectural Discipline explicitly scores this (DECISIONS D-007c).
    timeout_seconds: float = 30.0

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.grant = FLEET_SCOPES[self.name]

    # --- model tier ----------------------------------------------------------------
    @property
    def model(self) -> str:
        return self._settings.FLASH_MODEL

    # --- scope enforcement ---------------------------------------------------------
    async def call_tool(self, ctx: AgentContext, tool_name: str, **kwargs: Any) -> Any:
        spec = TOOL_SPECS.get(tool_name)
        if spec is None:
            raise KeyError(f"unknown tool {tool_name!r}")

        if not self.grant.permits(spec.scope):
            violation = ScopeViolation(self.name, spec.scope, self.grant.policy_id)
            await self._emit_denial(ctx, tool_name, spec.scope, str(violation))
            raise violation

        ctx.telemetry.tool_call(
            case_id=ctx.case_id, agent=self.name, tool=tool_name, scope=spec.scope
        )
        return spec.fn(**kwargs)

    async def _emit_denial(
        self, ctx: AgentContext, tool: str, scope: str, message: str
    ) -> None:
        await ctx.repo.append_posture_event(
            {
                "event_id": f"PE-{uuid.uuid4().hex[:10].upper()}",
                "kind": "identity_denial",
                "occurred_at": ctx.clock.now().isoformat(),
                "case_id": ctx.case_id,
                "agent": self.name,
                "agent_version": self.version,
                "tool": tool,
                "scope": scope,
                "policy_id": self.grant.policy_id,
                "decision": "DENY",
                "message": message,
            }
        )

    # --- model call ----------------------------------------------------------------
    async def infer(self, ctx: AgentContext, prompt: str, observations: dict[str, Any]) -> dict[str, Any]:
        """Interpret tool observations as an ADK agent. Cached by prompt hash.

        The key is computed from OUR strings — agent, model tier, prompt, observations — and not
        from anything ADK puts on the wire. That is what let the fleet move onto ADK without
        invalidating a single cached response: replay-mode rehearsal and credential-free CI are
        unaffected by the transport underneath them.
        """
        instruction = f"{prompt}\n{TOOL_PROTOCOL}"
        key = prompt_hash(self.name, self.model, instruction, observations)

        async def live_call() -> dict[str, Any]:
            text, input_tokens, output_tokens = await infer_via_adk(
                self, ctx, instruction=instruction, observations=observations,
            )
            parsed, raw = self._parse(text, input_tokens, output_tokens, ctx)

            if parsed is None:
                # One repair attempt, then give up loudly. See REPAIR_SUFFIX.
                ctx.telemetry.tool_call(
                    case_id=ctx.case_id, agent=self.name,
                    tool="format_repair", scope="findings:read",
                )
                text, retry_in, retry_out = await infer_via_adk(
                    self, ctx, instruction=instruction + REPAIR_SUFFIX,
                    observations=observations,
                )
                input_tokens += retry_in
                output_tokens += retry_out
                parsed, raw = self._parse(text, input_tokens, output_tokens, ctx)
                if parsed is None:
                    raise MalformedModelOutput(self.name, self.model, raw)

            ctx.telemetry.record_tokens(
                case_id=ctx.case_id,
                agent=self.name,
                tokens=input_tokens + output_tokens,
            )
            # Any scope denial the MODEL provoked is written here rather than inside the ADK
            # callback: that callback is synchronous, and a posture event is a repository write.
            await self._flush_denials(ctx)
            return parsed

        return await ctx.replay.resolve(key, live_call, label=f"{self.name}:{self.signal}")

    def _parse(
        self, text: str, input_tokens: int, output_tokens: int, ctx: AgentContext,
    ) -> tuple[dict[str, Any] | None, str]:
        """Parse a reply, or report that it could not be parsed. Never raises.

        Returns `(None, raw)` rather than raising so the caller owns the repair decision — and so
        an empty reply, which is what a thinking model returns when it spends its whole output
        budget on reasoning, is handled by the same path as malformed text rather than by a
        different exception type several frames away.
        """
        completion = Completion(
            text=text, model=self.model, provider=getattr(ctx.llm, "name", None),
            input_tokens=input_tokens, output_tokens=output_tokens,
        )
        if not text.strip():
            return None, ""
        try:
            parsed = completion.json()
        except (json.JSONDecodeError, ValueError, IndexError):
            return None, text
        # A JSON scalar or list parses but is not a result object, and every caller indexes it.
        return (parsed, text) if isinstance(parsed, dict) else (None, text)

    async def _flush_denials(self, ctx: AgentContext) -> None:
        """Persist scope denials collected during an ADK run."""
        while ctx.pending_denials:
            event = ctx.pending_denials.pop(0)
            event.setdefault("agent_version", self.version)
            await ctx.repo.append_posture_event(event)

    # --- finding construction ------------------------------------------------------
    def build_finding(
        self,
        *,
        verdict: str,
        confidence: float,
        reasoning: str,
        evidence: list[EvidenceRef],
        latency_ms: int,
        signal: str | None = None,
    ) -> Finding:
        return Finding(
            # Deterministic, not a uuid4. A finding id is scoped to its case and an agent
            # contributes one finding per signal, so agent+signal identifies it — which is
            # already the pattern in seed/history.py and in the pipeline's attribution finding.
            #
            # The uuid4 that used to be here silently broke replay mode. The Challenger reasons
            # over the fan-out's findings, so its observations carry their ids; a fresh uuid on
            # every run meant the Challenger's prompt hash was different every run and could
            # never hit the cache. `make rehearse` and credential-free CI could not complete a
            # single scenario, and the miss surfaced as a 503 rather than as anything pointing
            # at the cause.
            finding_id=f"F-{self.name}-{(signal or self.signal)[:6]}",
            agent=self.name,
            agent_version=self.version,
            signal=signal or self.signal,
            verdict=verdict,
            confidence=confidence,
            evidence=evidence,
            reasoning=reasoning,
            latency_ms=latency_ms,
        )

    # --- step wrapper --------------------------------------------------------------
    async def run(self, ctx: AgentContext) -> Finding:
        started = time.perf_counter()
        with ctx.telemetry.agent_span(
            case_id=ctx.case_id,
            agent=self.name,
            agent_version=self.version,
            step=self.signal,
            model=self.model,
            identity=self.grant.policy_id,
        ) as span:
            finding = await self.evaluate(ctx)
            elapsed = int((time.perf_counter() - started) * 1000)
            if elapsed > self.timeout_seconds * 1000:
                raise AgentTimeout(f"{self.name} exceeded {self.timeout_seconds}s")
            span.set_verdict(finding.verdict, finding.confidence, len(finding.evidence))
            return finding

    async def evaluate(self, ctx: AgentContext) -> Finding:  # pragma: no cover - abstract
        raise NotImplementedError
