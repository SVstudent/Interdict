"""Audit routes — the hash-chained Nacha Phase 2 record for a case.

The record is a first-class downloadable artifact rather than a log line, because the person who
needs it is the one who will be asked for it. Each record carries `prev_record_hash`, so the
chain is verifiable end to end.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..audit.nacha import AuditChain
from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def chain(state: AppState = Depends(get_state)) -> dict[str, Any]:
    records = await state.repo.list_audit_records()
    verification = await AuditChain(state.repo, state.clock).verify()
    return {"records": records, "verification": verification}


@router.get("/{case_id}")
async def record_for_case(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    record = await AuditChain(state.repo, state.clock).for_case(case_id)
    if record is None:
        raise HTTPException(404, f"no audit record for case {case_id}")
    return record


@router.get("/{case_id}/download")
async def download(case_id: str, state: AppState = Depends(get_state)) -> JSONResponse:
    record = await AuditChain(state.repo, state.clock).for_case(case_id)
    if record is None:
        raise HTTPException(404, f"no audit record for case {case_id}")
    return JSONResponse(
        record,
        headers={"Content-Disposition": f'attachment; filename="{case_id}-nacha-record.json"'},
    )
