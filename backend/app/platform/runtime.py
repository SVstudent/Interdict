"""Agent Runtime binding — reasoningEngines, at `us-central1` (DECISIONS D-002a)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class EngineHandle:
    agent_id: str
    reasoning_engine_id: str
    revision: str
    location: str


class RuntimePort(Protocol):
    async def deploy(self, agent_id: str, spec: dict[str, Any]) -> EngineHandle: ...
    async def async_query(self, engine: EngineHandle, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def list_engines(self) -> list[EngineHandle]: ...


class LocalRuntime:
    """Runs agents in-process. Same interface, no cloud."""

    def __init__(self) -> None:
        self._engines: dict[str, EngineHandle] = {}

    async def deploy(self, agent_id: str, spec: dict[str, Any]) -> EngineHandle:
        handle = EngineHandle(agent_id, f"local-{agent_id}", "local-1", "in-process")
        self._engines[agent_id] = handle
        return handle

    async def async_query(self, engine: EngineHandle, payload: dict[str, Any]) -> dict[str, Any]:
        return {"engine": engine.reasoning_engine_id, "echo": payload}

    async def list_engines(self) -> list[EngineHandle]:
        return list(self._engines.values())


class GeapRuntime:
    def __init__(self, project_id: str, location: str = "us-central1") -> None:
        self._project_id = project_id
        self._location = location

    @property
    def _base(self) -> str:
        return (f"https://{self._location}-aiplatform.googleapis.com/v1beta1"
                f"/projects/{self._project_id}/locations/{self._location}/reasoningEngines")

    async def _headers(self) -> dict[str, str]:  # pragma: no cover
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {creds.token}"}

    async def deploy(self, agent_id: str, spec: dict[str, Any]) -> EngineHandle:  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(self._base, headers=await self._headers(), json=spec)
            resp.raise_for_status()
            name = resp.json().get("name", "")
        return EngineHandle(agent_id, name.rsplit("/", 1)[-1], "1", self._location)

    async def async_query(
        self, engine: EngineHandle, payload: dict[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{self._base}/{engine.reasoning_engine_id}:asyncQuery",
                headers=await self._headers(), json={"input": payload},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_engines(self) -> list[EngineHandle]:  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._base, headers=await self._headers())
            resp.raise_for_status()
            return [
                EngineHandle(
                    e.get("displayName", ""), e.get("name", "").rsplit("/", 1)[-1],
                    "1", self._location,
                )
                for e in resp.json().get("reasoningEngines", [])
            ]
