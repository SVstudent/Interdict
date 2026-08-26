"""Agent Gateway binding — routing and policy between the orchestrator and specialists."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class RouteDecision:
    request_id: str
    source: str
    target: str
    allowed: bool
    policy_id: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "source": self.source, "target": self.target,
            "allowed": self.allowed, "policy_id": self.policy_id, "reason": self.reason,
        }


class GatewayPort(Protocol):
    async def route(self, source: str, target: str, payload: dict[str, Any]) -> RouteDecision: ...


# The orchestrator may reach any specialist. Specialists may not reach each other: a compromised
# worker must not be able to instruct a peer, and the Challenger in particular must never be able
# to reach the Adjudicator directly.
ALLOWED_HOPS: dict[str, frozenset[str]] = {
    "orchestrator": frozenset({"sentry", "callback", "ledger", "provenance",
                               "registry-check", "challenger", "adjudicator"}),
}


class LocalGateway:
    def __init__(self) -> None:
        self.decisions: list[RouteDecision] = []

    async def route(self, source: str, target: str, payload: dict[str, Any]) -> RouteDecision:
        allowed = target in ALLOWED_HOPS.get(source, frozenset())
        decision = RouteDecision(
            request_id=f"rt-{uuid.uuid4().hex[:8]}",
            source=source,
            target=target,
            allowed=allowed,
            policy_id="interdict-gateway/hop-policy-v1",
            reason="orchestrator-to-specialist hop permitted" if allowed
            else f"'{source}' may not invoke '{target}'; specialists are leaves",
        )
        self.decisions.append(decision)
        return decision

    def reset(self) -> None:
        self.decisions.clear()


class GeapGateway(LocalGateway):
    """gcloud beta network-services agent-gateways. Policy is evaluated locally as well so a
    gateway outage cannot silently widen what an agent may reach."""

    def __init__(self, project_id: str, location: str, gateway_id: str) -> None:
        super().__init__()
        self._project_id = project_id
        self._location = location
        self._gateway_id = gateway_id
