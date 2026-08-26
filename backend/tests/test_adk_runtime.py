"""The ADK runtime: tool declaration and the scope gate, without a model call.

These test the parts of `adk_runtime` that are policy rather than inference, so they run offline
with no credentials like the rest of the suite. What a model *chooses* to do with a declared tool
is verified live; what it is *permitted* to do is decided here, and that is the half that must
never regress silently.

The scope gate is the reason this file exists. Enforcing scope in `call_tool` only covers calls
the code initiates. Once the model can call tools, there is a second path into the same data, and
an enforcement that covers one path and not the other is not an enforcement.
"""
from __future__ import annotations

import pytest

from app.agents.adk_runtime import AdkUnavailable, _model_for, _scope_gate, _tools_for
from app.agents.base import AgentContext
from app.agents.scopes import FLEET_SCOPES, Scope
from app.agents.tools import TOOL_SPECS
from app.config import Settings
from app.llm.provider import Provider


class _Tool:
    """Stands in for an ADK BaseTool: the gate only reads `.name`."""

    def __init__(self, name: str) -> None:
        self.name = name


def _ctx(repo, clock) -> AgentContext:
    return AgentContext(case_id="CASE-TEST", repo=repo, clock=clock, settings=Settings(),
                        replay=None, telemetry=None, llm=None,
                        payload={"request_id": "REQ-1001", "vendor_id": "V-NORTHWIND"})


# --- the scope gate -------------------------------------------------------------------------


def test_the_gate_refuses_a_model_initiated_call_outside_the_grant(repo, clock):
    """Callback may phone the number of record. It may never read banking details."""
    ctx = _ctx(repo, clock)
    gate = _scope_gate("callback", ctx)

    result = gate(_Tool("read_vendor_banking"), {}, None)

    assert result is not None, (
        "the model reached for vendor banking as the Callback agent and the gate let it through"
    )
    assert result["error"] == "scope_denied"
    assert result["scope"] == Scope.VENDOR_BANKING_READ
    assert result["policy_id"] == FLEET_SCOPES["callback"].policy_id


def test_a_denial_is_reported_to_the_model_not_merely_swallowed(repo, clock):
    """Returning the refusal as the tool result is what lets the agent reason about it.

    A gate that returned nothing would leave the model to interpret an empty result, and the most
    likely interpretation is "no banking change on file" — the opposite of the truth.
    """
    ctx = _ctx(repo, clock)
    result = _scope_gate("callback", ctx)(_Tool("read_vendor_banking"), {}, None)
    assert "detail" in result and "denies" in result["detail"]


def test_a_denial_queues_a_posture_event_marked_model_initiated(repo, clock):
    ctx = _ctx(repo, clock)
    _scope_gate("callback", ctx)(_Tool("read_vendor_banking"), {}, None)

    assert len(ctx.pending_denials) == 1
    event = ctx.pending_denials[0]
    assert event["kind"] == "identity_denial"
    assert event["decision"] == "DENY"
    assert event["agent"] == "callback"
    assert event["initiated_by"] == "model", (
        "a model-initiated denial must be distinguishable from a code-initiated one"
    )


def test_the_gate_permits_a_granted_call(repo, clock):
    """Returning None is ADK's 'proceed'. A gate that denied everything would prove nothing."""
    ctx = _ctx(repo, clock)
    assert _scope_gate("callback", ctx)(_Tool("contact_of_record"), {}, None) is None
    assert ctx.pending_denials == []


def test_an_unknown_tool_is_not_silently_authorised(repo, clock):
    """`None` here means proceed, and ADK will then fail on a tool it cannot resolve.

    Asserted so the behaviour is deliberate: the gate's job is scope, not tool resolution, and a
    name with no spec cannot be scope-checked against anything.
    """
    ctx = _ctx(repo, clock)
    assert _scope_gate("callback", ctx)(_Tool("not_a_real_tool"), {}, None) is None


# --- what gets declared ---------------------------------------------------------------------


@pytest.mark.parametrize("agent_name", sorted(FLEET_SCOPES))
def test_no_agent_is_declared_a_tool_its_identity_denies(agent_name, repo, clock):
    """The manifest on the Registry surface must match what the model can actually see."""
    ctx = _ctx(repo, clock)
    grant = FLEET_SCOPES[agent_name]
    for tool in _tools_for(agent_name, ctx, {"request": None, "vendor": None}):
        spec = TOOL_SPECS[tool.name]
        assert grant.permits(spec.scope), (
            f"{agent_name} was declared {tool.name}, which needs {spec.scope} — a scope its "
            f"identity does not grant"
        )


def test_callback_is_declared_its_own_tool_and_not_the_banking_one(repo, clock):
    ctx = _ctx(repo, clock)
    declared = {t.name for t in _tools_for("callback", ctx, {"request": None, "vendor": None})}
    assert "contact_of_record" in declared
    assert "read_vendor_banking" not in declared


def test_the_challenger_is_declared_no_tools(repo, clock):
    """It argues from the findings in front of it; `findings:read` matches no tool spec."""
    ctx = _ctx(repo, clock)
    assert _tools_for("challenger", ctx, {"request": None, "vendor": None}) == []


# --- provider compliance --------------------------------------------------------------------


def test_an_unsanctioned_provider_is_refused_rather_than_routed():
    """The judged artifact must not come from a third-party aggregator (D-008)."""
    with pytest.raises(AdkUnavailable):
        _model_for(Settings(LLM_PROVIDER=Provider.TOKENROUTER), "gemini-3.6-flash")


def test_vertex_binds_our_project_and_location_explicitly():
    """Not the ambient GOOGLE_* environment: the location must be `global` for Gemini 3.x."""
    settings = Settings(LLM_PROVIDER=Provider.VERTEX, GCP_PROJECT_ID="p", VERTEX_LOCATION="global")
    model = _model_for(settings, "gemini-3.6-flash")
    assert model.model == "gemini-3.6-flash"
    assert hasattr(model, "api_client"), "the Vertex client binding was dropped"
