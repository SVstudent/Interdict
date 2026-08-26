"""Agent Registry binding — discovery and versioning (demo beat 1).

GEAP's Agent Registry is served from the `global` location only; every regional endpoint returns
"AgentService not supported in this location". See DECISIONS D-002a — this is why each protocol
carries its own location rather than sharing one project-wide setting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class RegistryEntry:
    agent_id: str
    display_name: str
    version: str
    description: str
    owner: str
    department: str
    data_classification: str
    granted_scopes: list[str]
    denied_scopes: list[str]
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    changelog: list[dict[str, str]] = field(default_factory=list)
    used_by: list[str] = field(default_factory=list)
    reasoning_engine_id: str | None = None
    runtime_revision: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegistryPort(Protocol):
    async def publish(self, entry: RegistryEntry) -> RegistryEntry: ...
    async def list_entries(self) -> list[RegistryEntry]: ...
    async def get(self, agent_id: str) -> RegistryEntry | None: ...


class LocalRegistry:
    def __init__(self, seed: list[RegistryEntry] | None = None) -> None:
        self._entries: dict[str, RegistryEntry] = {e.agent_id: e for e in (seed or [])}

    async def publish(self, entry: RegistryEntry) -> RegistryEntry:
        self._entries[entry.agent_id] = entry
        return entry

    async def list_entries(self) -> list[RegistryEntry]:
        return sorted(self._entries.values(), key=lambda e: e.agent_id)

    async def get(self, agent_id: str) -> RegistryEntry | None:
        return self._entries.get(agent_id)


class GeapRegistry:
    """projects.locations.agents (v1beta1) at location `global`."""

    def __init__(self, project_id: str, location: str = "global") -> None:
        self._project_id = project_id
        self._location = location

    @property
    def _base(self) -> str:
        host = "aiplatform.googleapis.com" if self._location == "global" \
            else f"{self._location}-aiplatform.googleapis.com"
        return (f"https://{host}/v1beta1/projects/{self._project_id}"
                f"/locations/{self._location}/agents")

    async def _token(self) -> str:  # pragma: no cover - requires credentials
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    async def publish(self, entry: RegistryEntry) -> RegistryEntry:  # pragma: no cover
        import httpx

        headers = {"Authorization": f"Bearer {await self._token()}"}
        body = {
            "displayName": entry.display_name,
            "description": entry.description,
            "labels": {
                "owner": entry.owner.replace("@", "_at_"),
                "department": entry.department,
                "classification": entry.data_classification,
                "version": entry.version.replace(".", "-"),
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._base, headers=headers, params={"agentId": entry.agent_id}, json=body
            )
            resp.raise_for_status()
        return entry

    async def list_entries(self) -> list[RegistryEntry]:  # pragma: no cover
        import httpx

        headers = {"Authorization": f"Bearer {await self._token()}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._base, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        return [
            RegistryEntry(
                agent_id=a.get("name", "").rsplit("/", 1)[-1],
                display_name=a.get("displayName", ""),
                version=a.get("labels", {}).get("version", "").replace("-", "."),
                description=a.get("description", ""),
                owner=a.get("labels", {}).get("owner", ""),
                department=a.get("labels", {}).get("department", ""),
                data_classification=a.get("labels", {}).get("classification", ""),
                granted_scopes=[],
                denied_scopes=[],
            )
            for a in payload.get("agents", [])
        ]

    async def get(self, agent_id: str) -> RegistryEntry | None:  # pragma: no cover
        return next((e for e in await self.list_entries() if e.agent_id == agent_id), None)
