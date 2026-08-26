"""Sessions and cross-session memory (demo beat 5).

One session per case. `append_event` is the durable audit spine: it records what the fleet saw
and concluded so a case that lies dormant for days can rehydrate its prior findings instead of
starting over.

Memory Bank's top-level `memories` collection 404s on our project (DECISIONS D-002b), so this
targets `reasoningEngines.sessions` + `appendEvent`, which is documented and verified. If Memory
Bank becomes available it slots in behind this same Protocol.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SessionEvent:
    event_id: str
    session_id: str
    kind: str
    payload: dict[str, Any]
    occurred_at: str


@dataclass
class SessionRecord:
    session_id: str
    case_id: str
    created_at: str
    events: list[SessionEvent] = field(default_factory=list)


class MemoryPort(Protocol):
    async def open_session(self, case_id: str, now: str) -> str: ...
    async def append_event(self, session_id: str, kind: str, payload: dict[str, Any], now: str) -> None: ...
    async def rehydrate(self, session_id: str) -> list[SessionEvent]: ...
    async def get_session(self, session_id: str) -> SessionRecord | None: ...


class LocalMemory:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    async def open_session(self, case_id: str, now: str) -> str:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        self._sessions[session_id] = SessionRecord(session_id, case_id, now)
        return session_id

    async def append_event(
        self, session_id: str, kind: str, payload: dict[str, Any], now: str
    ) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            # The case owns the session id and outlives this process; these dicts do not.
            # A seeded case, or any case resumed after a restart, hands back an id opened by
            # someone else — refusing it turned crash-resume and human resolution into errors
            # while GeapMemory, whose sessions are genuinely durable, accepted both. Adopting
            # the id restores parity. The case metadata is unknown until rehydrate, exactly as
            # GeapMemory.get_session already reports it.
            session = SessionRecord(session_id, "", now)
            self._sessions[session_id] = session
        session.events.append(
            SessionEvent(f"ev-{uuid.uuid4().hex[:10]}", session_id, kind, payload, now)
        )

    async def rehydrate(self, session_id: str) -> list[SessionEvent]:
        session = self._sessions.get(session_id)
        return list(session.events) if session else []

    async def get_session(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def reset(self) -> None:
        self._sessions.clear()


class GeapMemory:
    """reasoningEngines.sessions + sessions.appendEvent, at the Agent Runtime location."""

    def __init__(self, project_id: str, location: str, reasoning_engine_id: str) -> None:
        self._project_id = project_id
        self._location = location
        self._engine = reasoning_engine_id

    @property
    def _base(self) -> str:
        return (f"https://{self._location}-aiplatform.googleapis.com/v1beta1"
                f"/projects/{self._project_id}/locations/{self._location}"
                f"/reasoningEngines/{self._engine}/sessions")

    async def _headers(self) -> dict[str, str]:  # pragma: no cover - requires credentials
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {creds.token}"}

    async def open_session(self, case_id: str, now: str) -> str:  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._base, headers=await self._headers(),
                json={"userId": case_id, "sessionState": {"case_id": case_id, "opened": now}},
            )
            resp.raise_for_status()
            return resp.json().get("name", "").rsplit("/", 1)[-1]

    async def append_event(
        self, session_id: str, kind: str, payload: dict[str, Any], now: str
    ) -> None:  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._base}/{session_id}:appendEvent",
                headers=await self._headers(),
                json={"author": "interdict", "invocationId": kind,
                      "timestamp": now, "content": {"parts": [{"text": str(payload)}]}},
            )
            resp.raise_for_status()

    async def rehydrate(self, session_id: str) -> list[SessionEvent]:  # pragma: no cover
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base}/{session_id}/events", headers=await self._headers()
            )
            resp.raise_for_status()
            return [
                SessionEvent(
                    e.get("name", "").rsplit("/", 1)[-1], session_id,
                    e.get("invocationId", "event"), e.get("content", {}), e.get("timestamp", ""),
                )
                for e in resp.json().get("sessionEvents", [])
            ]

    async def get_session(self, session_id: str) -> SessionRecord | None:  # pragma: no cover
        return SessionRecord(session_id, "", "", await self.rehydrate(session_id))
