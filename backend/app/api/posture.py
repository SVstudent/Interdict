"""Posture routes — the security-posture feed.

Every guardrail screening with the literal removed content, every scope decision including the
model-initiated ones, and the fields the cross-district exchange withholds. An enforcement you
cannot show is one a reviewer assumes you did not build.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/posture", tags=["posture"])


@router.get("")
async def posture_feed(state: AppState = Depends(get_state)) -> dict[str, Any]:
    events = await state.repo.list_posture_events()
    gateway = getattr(state.platform.gateway, "decisions", [])
    return {
        "events": list(reversed(events)),
        "gateway_decisions": [d.as_dict() for d in reversed(list(gateway))],
        "scope_manifest": _manifest(),
    }


def _manifest() -> list[dict[str, Any]]:
    from ..agents.scopes import FLEET_SCOPES

    return [
        {
            "agent": name,
            "granted": sorted(grant.granted),
            "denied": sorted(grant.denied),
            "policy_id": grant.policy_id,
        }
        for name, grant in sorted(FLEET_SCOPES.items())
    ]
