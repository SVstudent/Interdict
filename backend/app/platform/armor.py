"""Model Armor binding — inline guardrails on inbound artifacts.

The local implementation is our own screening engine (guardrails/injection.py). The GEAP
implementation additionally submits the artifact to Model Armor. Both return the same
ScreeningResult so the Posture surface renders identically either way — the parity test depends
on that.
"""
from __future__ import annotations

from typing import Any, Protocol

from ..guardrails.injection import ScreeningResult, guardrail


class ArmorPort(Protocol):
    async def screen(self, artifact: str, metadata: dict[str, Any]) -> ScreeningResult: ...


class LocalArmor:
    async def screen(self, artifact: str, metadata: dict[str, Any]) -> ScreeningResult:
        return guardrail.screen(artifact, metadata)


class GeapArmor:
    """Model Armor template applied ahead of our own screening.

    Ours runs regardless. Model Armor is a second opinion, not a replacement: if the managed
    service is unreachable we must still refuse to hand an unscreened artifact to an agent.
    """

    def __init__(self, project_id: str, location: str, template_id: str) -> None:
        self._project_id = project_id
        self._location = location
        self._template = template_id

    async def screen(self, artifact: str, metadata: dict[str, Any]) -> ScreeningResult:
        result = guardrail.screen(artifact, metadata)
        try:
            managed = await self._sanitize(artifact)
        except Exception:  # noqa: BLE001 - degraded, never bypassed
            result.metadata["model_armor"] = "unavailable"
            return result
        result.metadata["model_armor"] = managed
        return result

    async def _sanitize(self, artifact: str) -> dict[str, Any]:  # pragma: no cover
        import google.auth
        import google.auth.transport.requests
        import httpx

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        url = (f"https://modelarmor.{self._location}.rep.googleapis.com/v1"
               f"/projects/{self._project_id}/locations/{self._location}"
               f"/templates/{self._template}:sanitizeUserPrompt")
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {creds.token}"},
                json={"userPromptData": {"text": artifact}},
            )
            resp.raise_for_status()
            return resp.json()
