from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/registry", tags=["registry"])


@router.get("")
async def list_agents(state: AppState = Depends(get_state)) -> dict[str, Any]:
    entries = await state.platform.registry.list_entries()
    engines = {e.agent_id: e for e in await state.platform.runtime.list_engines()}
    rows = []
    for entry in entries:
        row = entry.as_dict()
        handle = engines.get(entry.agent_id)
        row["reasoning_engine_id"] = handle.reasoning_engine_id if handle else None
        row["runtime_revision"] = handle.revision if handle else None
        row["fleet"] = entry.agent_id.split(".", 1)[0]
        rows.append(row)
    return {"entries": rows, "backend": state.platform.backend.value}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    entry = await state.platform.registry.get(agent_id)
    if entry is None:
        raise HTTPException(404, f"agent {agent_id} not registered")
    return entry.as_dict()
