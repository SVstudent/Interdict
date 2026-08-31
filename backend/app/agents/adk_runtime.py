"""The fleet's model runtime: real ADK agents, executed by a real ADK Runner.

Every reasoning step in Interdict runs as a `google.adk.agents.LlmAgent` driven by
`google.adk.Runner`. The agent is constructed with the tools its identity scope permits, declared
to the model as ADK `FunctionTool`s, so the model can ask for a fact instead of recalling one.

WHY THIS EXISTS AS A SEPARATE MODULE

`InterdictAgent.infer()` used to call `google-genai`'s `generate_content` directly with automatic
function calling switched off, which made the fleet a set of single-shot completions with a
hand-rolled tool registry beside them. `google-adk` was pinned in requirements and imported
nowhere — the same defect DECISIONS D-001 F1 records against the inherited scaffold, reproduced.
This module is the fix, and it is deliberately the ONLY place ADK is constructed so that the
claim "the fleet runs on ADK" is checkable by reading one file.

WHAT IS DELIBERATELY UNCHANGED

  * The prompt and the observations. `prompt_hash(agent, model, prompt, observations)` is computed
    from our own strings, not from the wire format, so moving the transport to ADK does not
    invalidate a single cached response. Replay-mode rehearsal and credential-free CI keep working
    without a re-record.
  * Deterministic evidence. Each agent still gathers its observations through `call_tool` before
    it reasons, and an `EvidenceRef` still carries a literal observed value. Tools declared to the
    model are for follow-up questions; they are not the source of the evidence chain. A model that
    declined to call anything would still produce a finding backed by real observations.
  * Scope enforcement. `before_tool_callback` runs the same `FLEET_SCOPES` check as `call_tool`,
    so a model-initiated call is refused by the same policy and writes the same posture event.
    This is what makes the identity-denial beat real rather than staged: the Callback agent is
    denied `vendor:banking:read` even when the *model* is the one asking.
"""
from __future__ import annotations

import asyncio
import functools
import json
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from google import genai
from google.adk import Runner
from google.adk.agents import LlmAgent, RunConfig
from google.adk.agents.invocation_context import LlmCallsLimitExceededError
from google.adk.models.google_llm import Gemini
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.genai import types as genai_types

from ..config import Settings
from ..llm.provider import Provider, with_retry
from .scopes import FLEET_SCOPES, ScopeViolation
from .tools import TOOL_SPECS

if TYPE_CHECKING:  # pragma: no cover - import cycle; AgentContext lives in base.py
    from .base import AgentContext

APP_NAME = "interdict"

# The model's budget for ONE reasoning step: the opening call plus up to three tool round-trips.
#
# ADK defaults `max_llm_calls` to 500. That is a runaway guard for a long-lived assistant, not a
# budget for a step that already has its observations in front of it, and it is not survivable
# here: a model that keeps reaching for tools loops for as long as it likes while the case sits
# in `verifying` and the console shows a lane that never lands. A full run-through stalled for
# twenty-nine minutes on exactly this before the cap existed.
#
# Four is deliberate rather than tight. The observations are gathered deterministically before the
# model is asked anything, so the expected number of tool calls is zero; three is headroom for an
# agent that genuinely wants to confirm something, and hitting the ceiling means the model is
# looping rather than working.
MAX_LLM_CALLS_PER_STEP = 4

# Hard wall-clock ceiling on one step, independent of the call budget.
#
# The fan-out already wraps each lane in `asyncio.wait_for`, but the Challenger and the Adjudicator
# run as their own pipeline steps with nothing above them — so before this, a single hung request
# there could stall a case indefinitely with no lane to blame and no timeout to fire. A ceiling
# here covers every step by construction rather than covering the four we remembered to wrap.
STEP_TIMEOUT_SECONDS = 90.0


class AdkStepTimeout(RuntimeError):
    """One reasoning step exceeded its wall-clock ceiling."""


class AdkUnavailable(RuntimeError):
    """ADK cannot serve this provider. Raised rather than silently falling back to a raw call."""


def _vertex_gemini(settings: Settings, model: str) -> Gemini:
    """ADK's Gemini bound to OUR Vertex configuration.

    ADK's default client reads ambient `GOOGLE_*` environment variables. We do not set those —
    the project and location are settings, and the location in particular is the one value this
    system gets wrong most easily (Gemini 3.x publisher models are served from `global`;
    `us-central1` 404s, D-010). Overriding `api_client` is the documented extension point and
    keeps one source of truth for where the models live.
    """
    project, location = settings.GCP_PROJECT_ID, settings.VERTEX_LOCATION

    class _BoundGemini(Gemini):
        """ADK's Gemini with our Vertex client bound explicitly.

        ADK otherwise resolves a client from ambient `GOOGLE_*` environment variables, which
        cannot express the location Gemini 3.x publisher models actually need: they are served
        from `global`, and `us-central1` returns 404. Binding the client here makes the project
        and location come from settings, so the process is not one stray env var from failing.
        """
        @functools.cached_property
        def api_client(self) -> genai.Client:
            return genai.Client(vertexai=True, project=project, location=location)

    return _BoundGemini(model=model)


def _model_for(settings: Settings, model: str) -> Any:
    """Resolve the model ADK should drive.

    Vertex is the sanctioned default and gets the bound client above. The Developer API is also
    sanctioned; ADK accepts a bare model string there and picks the key up from the environment.
    A third-party aggregator is neither, and is refused rather than quietly routed — the whole
    point of the compliance gate is that a judged artifact cannot come from an unsanctioned path.
    """
    if settings.LLM_PROVIDER is Provider.VERTEX:
        return _vertex_gemini(settings, model)
    if settings.LLM_PROVIDER is Provider.GEMINI:
        return model
    raise AdkUnavailable(
        f"LLM_PROVIDER={settings.LLM_PROVIDER.value} is not sanctioned for the ADK fleet; "
        "use vertex or gemini"
    )


# --------------------------------------------------------------------------------------------
# Tools, bound to the case in front of the agent.
#
# The underlying implementations in tools.py take domain objects (a Vendor, a list of Invoices).
# A model cannot supply those, and should not have to: it is reasoning about ONE case, so the
# question it wants to ask is "what is the relationship baseline?", not "here is a vendor record,
# compute a baseline". Each wrapper below therefore takes no arguments it cannot know, and reads
# the case from the repository itself.
# --------------------------------------------------------------------------------------------


async def _case_objects(ctx: AgentContext) -> dict[str, Any]:
    request = await ctx.repo.get_request(ctx.payload["request_id"]) \
        if ctx.payload.get("request_id") else None
    vendor = await ctx.repo.get_vendor(ctx.payload["vendor_id"]) \
        if ctx.payload.get("vendor_id") else None
    return {"request": request, "vendor": vendor}


def _tool_wrappers(ctx: AgentContext, objects: dict[str, Any]) -> dict[str, Any]:
    """Model-facing callables. Names match TOOL_SPECS so the scope gate can find the spec."""
    request = objects.get("request")
    vendor = objects.get("vendor")
    meta: dict[str, Any] = request.artifact_metadata if request else {}

    def analyze_sender_domain() -> dict[str, Any]:
        """Compare the addresses on the inbound artifact against the vendor's domain of record.

        Reports whether the reply-to diverges from the sender, whether it is a lookalike of the
        vendor's real domain, and how many days ago that domain was registered.
        """
        return TOOL_SPECS["analyze_sender_domain"].fn(
            from_address=meta.get("from", ""),
            reply_to=meta.get("reply_to", ""),
            vendor_domain=(vendor.contact_email_of_record.split("@")[-1] if vendor else ""),
            domain_registered_at=meta.get("reply_to_domain_registered_at"),
            now=ctx.clock.now(),
        )

    def inspect_document_metadata() -> dict[str, Any]:
        """Inspect the attached document's metadata and compare its producer against the
        producer seen on this vendor's historical invoices."""
        return TOOL_SPECS["inspect_document_metadata"].fn(
            metadata=meta, baseline_producer=meta.get("baseline_producer"),
        )

    async def relationship_baseline() -> dict[str, Any]:
        """How long this vendor has been on the books, how much has been paid, and how many
        times their banking details have changed before."""
        return TOOL_SPECS["relationship_baseline"].fn(vendor=vendor, now=ctx.clock.now())

    async def correlate_open_invoice() -> dict[str, Any]:
        """Check whether the invoice the request references is a genuine open invoice."""
        invoices = await ctx.repo.list_invoices(vendor.vendor_id) if vendor else []
        return TOOL_SPECS["correlate_open_invoice"].fn(
            invoices=invoices,
            referenced_invoice_id=meta.get("referenced_invoice"),
            now=ctx.clock.now(),
        )

    def match_account_holder() -> dict[str, Any]:
        """Compare the name on the proposed bank account against the vendor's legal entity."""
        proposed = request.proposed_banking if request else None
        return TOOL_SPECS["match_account_holder"].fn(
            account_name=proposed.account_name if proposed else "",
            legal_name=vendor.legal_name if vendor else "",
            dba_name=vendor.dba_name if vendor else None,
        )

    def check_bank_jurisdiction() -> dict[str, Any]:
        """Compare the proposed receiving bank's country against where the vendor operates."""
        proposed = request.proposed_banking if request else None
        return TOOL_SPECS["check_bank_jurisdiction"].fn(
            bank_country=proposed.bank_country if proposed else "",
            operating_country=vendor.operating_country if vendor else "",
        )

    def contact_of_record() -> dict[str, Any]:
        """The vendor's phone number ON FILE, and whether the request supplied a different one.

        The number of record is the only number worth dialling. A number supplied by the request
        is a number supplied by whoever wrote the request.
        """
        return TOOL_SPECS["contact_of_record"].fn(
            vendor=vendor, supplied_phone=meta.get("supplied_phone"),
        )

    def read_vendor_banking() -> dict[str, Any]:
        """Read the vendor's stored banking details. Restricted by scope."""
        return TOOL_SPECS["read_vendor_banking"].fn(vendor=vendor)

    async def scheduled_exposure() -> dict[str, Any]:
        """Total value of this vendor's scheduled payments — the money at risk right now."""
        payments = await ctx.repo.list_payments(vendor.vendor_id) if vendor else []
        return TOOL_SPECS["scheduled_exposure"].fn(payments=payments)

    return {
        "analyze_sender_domain": analyze_sender_domain,
        "inspect_document_metadata": inspect_document_metadata,
        "relationship_baseline": relationship_baseline,
        "correlate_open_invoice": correlate_open_invoice,
        "match_account_holder": match_account_holder,
        "check_bank_jurisdiction": check_bank_jurisdiction,
        "contact_of_record": contact_of_record,
        "read_vendor_banking": read_vendor_banking,
        "scheduled_exposure": scheduled_exposure,
    }


def _scope_gate(agent_name: str, ctx: AgentContext) -> Callable[..., dict[str, Any] | None]:
    """`before_tool_callback`: refuse a model-initiated call outside the agent's grant.

    Returning a dict short-circuits the call in ADK and hands that dict back to the model as the
    tool result, so the model is TOLD it was denied and by which policy rather than silently
    receiving nothing. The posture event is written on the same path `call_tool` uses, which is
    why the denial that appears on the Posture surface is the same denial either way.
    """
    grant = FLEET_SCOPES[agent_name]

    def before_tool(tool, args, tool_context) -> dict[str, Any] | None:  # noqa: ANN001 - ADK callback signature
        spec = TOOL_SPECS.get(tool.name)
        if spec is None or grant.permits(spec.scope):
            return None
        violation = ScopeViolation(agent_name, spec.scope, grant.policy_id)
        ctx.pending_denials.append({
            "event_id": f"PE-{uuid.uuid4().hex[:10].upper()}",
            "kind": "identity_denial",
            "occurred_at": ctx.clock.now().isoformat(),
            "case_id": ctx.case_id,
            "agent": agent_name,
            "agent_version": getattr(ctx, "agent_version", ""),
            "tool": tool.name,
            "scope": spec.scope,
            "policy_id": grant.policy_id,
            "decision": "DENY",
            "message": str(violation),
            "initiated_by": "model",
        })
        return {
            "error": "scope_denied",
            "scope": spec.scope,
            "policy_id": grant.policy_id,
            "detail": str(violation),
        }

    return before_tool


def _tools_for(agent_name: str, ctx: AgentContext, objects: dict[str, Any]) -> list[FunctionTool]:
    """Declare the tools this agent's identity permits.

    Only granted tools are declared. Denial is still enforced at the gate above rather than by
    hiding the tool — an agent that reaches for something outside its grant by any route is
    refused — but a capability the identity can never use is not worth the context, and it is not
    worth the latency either.

    An earlier version declared `read_vendor_banking` to the Callback agent on every run to
    provoke a denial on camera. It worked, and it cost roughly fifteen seconds per case: the
    model reached for the number on file, was refused, and re-reasoned. The demo already has a
    dedicated probe for that beat (`POST /api/demo/force_scope_violation`), so paying for the
    provocation on every case bought a second copy of something a single click produces.
    """
    grant = FLEET_SCOPES[agent_name]
    wrappers = _tool_wrappers(ctx, objects)
    declared: list[FunctionTool] = []
    for tool_name, fn in wrappers.items():
        spec = TOOL_SPECS.get(tool_name)
        if spec is not None and grant.permits(spec.scope):
            declared.append(FunctionTool(fn))
    return declared


async def infer_via_adk(
    agent, ctx: AgentContext, instruction: str, observations: dict[str, Any],
) -> tuple[str, int, int]:
    """Run one reasoning step as an ADK agent. Returns (text, input_tokens, output_tokens)."""
    objects = await _case_objects(ctx)

    llm_agent = LlmAgent(
        name=agent.name.replace("-", "_"),  # ADK agent names are identifiers
        description=agent.signal.replace("_", " "),
        model=_model_for(ctx.settings, agent.model),
        instruction=instruction,
        tools=_tools_for(agent.name, ctx, objects),
        before_tool_callback=_scope_gate(agent.name, ctx),
    )

    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=llm_agent, session_service=session_service)
    session_id = f"{ctx.case_id}-{agent.name}-{uuid.uuid4().hex[:8]}"
    await session_service.create_session(
        app_name=APP_NAME, user_id=ctx.case_id, session_id=session_id,
    )

    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(
            text="OBSERVATIONS:\n" + json.dumps(observations, indent=2, default=str),
        )],
    )

    # Retry wraps the WHOLE run, not a single HTTP call. Moving inference onto ADK moved it off
    # `LLMProvider.complete`, which was where the throttle backoff used to live — so for a window
    # a 429 mid-recording had no backoff at all and would have failed a take outright. ADK owns
    # the request now, so the retriable unit is the run: a throttled step replays its own tool
    # calls, which are deterministic reads over the case and safe to repeat.
    async def _run_once() -> tuple[list[str], int, int]:
        text_parts: list[str] = []
        input_tokens = output_tokens = 0
        # A model that spends the whole budget on tool calls is stopped, not failed. ADK raises
        # LlmCallsLimitExceededError out of the generator; letting it propagate would turn a
        # chatty step into a dead case, and the step usually has usable text by then anyway.
        # If it does not, the caller's repair attempt asks once more with a format correction.
        try:
            async for event in runner.run_async(
                user_id=ctx.case_id, session_id=session_id, new_message=message,
                run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS_PER_STEP),
            ):
                usage = getattr(event, "usage_metadata", None)
                if usage is not None:
                    # Thinking tokens are billed as output and must be counted as output, or the
                    # telemetry under-reports the cost of the models we chose for reasoning.
                    input_tokens += getattr(usage, "prompt_token_count", 0) or 0
                    output_tokens += (getattr(usage, "candidates_token_count", 0) or 0) + \
                                     (getattr(usage, "thoughts_token_count", 0) or 0)
                content = getattr(event, "content", None)
                for part in (getattr(content, "parts", None) or []) if content else []:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    if getattr(part, "function_call", None):
                        ctx.telemetry.tool_call(
                            case_id=ctx.case_id, agent=agent.name,
                            tool=part.function_call.name,
                            scope=(TOOL_SPECS[part.function_call.name].scope
                                   if part.function_call.name in TOOL_SPECS else "unknown"),
                        )
        except LlmCallsLimitExceededError:
            ctx.telemetry.tool_call(
                case_id=ctx.case_id, agent=agent.name,
                tool="llm_call_budget_exhausted", scope="findings:read",
            )
        return text_parts, input_tokens, output_tokens

    async def _run_bounded() -> tuple[list[str], int, int]:
        try:
            return await asyncio.wait_for(_run_once(), timeout=STEP_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise AdkStepTimeout(
                f"{agent.name} on {agent.model} exceeded {STEP_TIMEOUT_SECONDS:.0f}s"
            ) from exc

    try:
        text_parts, input_tokens, output_tokens = await with_retry(
            _run_bounded, label=f"adk:{agent.name}:{agent.model}",
        )
    finally:
        await runner.close()

    return "".join(text_parts), input_tokens, output_tokens
