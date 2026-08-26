"""Precedent — where a human's resolution of an escalation stops being a conversation.

Today an ESCALATE dead-ends: someone decides, the money moves or does not, and their reasoning
leaves the building with them. `POST /api/cases/{id}/resolve` is the point at which it stops
doing that. The rest of these routes are how the book is read back.

No prefix: two of these routes hang off /api/cases, the same way api/callback.py extends the case
surface rather than inventing a parallel one.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..models.domain import Case, CaseState, Decision, Precedent, PrecedentKey
from ..platform.precedent import key_from_case
from ..state import AppState
from .deps import get_state

router = APIRouter(tags=["precedent"])


class Resolution(BaseModel):
    outcome: Literal["RELEASE", "BLOCK"]
    # A resolution with no reasoning teaches the fleet nothing and cannot be argued with later
    # (INV-8). Enforced here so the caller gets a 422 rather than a 500 out of the model.
    rationale: str = Field(min_length=1, max_length=2000)
    decided_by: str = Field(min_length=1, max_length=120, description="the human, named")


async def _key_for(state: AppState, case: Case) -> PrecedentKey:
    vendor = await state.repo.get_vendor(case.vendor_id) if case.vendor_id else None
    return key_from_case(
        case, vendor, now=state.clock.now(),
        callback_threshold=state.settings.CALLBACK_REQUIRED_THRESHOLD,
        release_ceiling=state.settings.AUTO_RELEASE_CEILING,
    )


@router.get("/api/precedent")
async def list_precedents(
    tenant_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    """The book, newest decision first. Omitting tenant_id returns every district's."""
    book = await state.platform.precedent.book(tenant_id)
    return {"precedents": book, "count": len(book)}


@router.get("/api/precedent/{precedent_id}")
async def get_precedent(
    precedent_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    precedent = await state.repo.get_precedent(precedent_id)
    if precedent is None:
        raise HTTPException(404, f"precedent {precedent_id} not found")
    return precedent.model_dump(mode="json")


@router.get("/api/cases/{case_id}/precedent")
async def precedent_for_case(
    case_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Which precedent this case matched, and why it scored where it did.

    Deterministic only. The clerk's opinion on whether the match GOVERNS costs a model call and
    is formed once, during adjudication; a GET the console polls must never spend money, and it
    must return the same answer every time an operator refreshes it.
    """
    case = await state.repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")

    key = await _key_for(state, case)
    matches = await state.platform.precedent.match(key, case.tenant_id)
    considered = await state.repo.list_precedents(case.tenant_id)
    return {
        "case_id": case_id,
        "cited": matches[0].as_dict() if matches else None,
        "candidates_considered": len(considered),
    }


@router.post("/api/cases/{case_id}/resolve")
async def resolve_case(
    case_id: str, resolution: Resolution, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Record how a named person resolved an escalation, and finalise the money on their word."""
    case = await state.repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    if case.state is not CaseState.ESCALATED:
        raise HTTPException(409, f"case {case_id} is {case.state.value}, not escalated")
    rationale = resolution.rationale.strip()
    if not rationale:
        raise HTTPException(422, "a resolution must carry a rationale")

    # Stored verbatim. The clerk can summarise a resolution for a reader, but nothing generated
    # goes into the book: a citation months from now must quote what the reviewer actually wrote,
    # not a paraphrase that drifted.
    precedent = Precedent(
        precedent_id=f"PR-{uuid.uuid4().hex[:10].upper()}",
        case_id=case_id,
        tenant_id=case.tenant_id,
        outcome=resolution.outcome,
        rationale=rationale,
        decided_by=resolution.decided_by,
        decided_at=state.clock.now(),
        key=await _key_for(state, case),
        vendor_id=case.vendor_id,
        exposure_amount=case.exposure_amount,
    )
    await state.platform.precedent.record(precedent)

    result = await state.payments.finalize(case, resolution.outcome)
    # ESCALATED is terminal in LEGAL_TRANSITIONS because the FLEET has no move left from it.
    # This one is the human's, made from outside the state machine, so it is applied directly
    # rather than pushed through assert_transition — which would, correctly, refuse it.
    case.state = CaseState.RELEASED if resolution.outcome == "RELEASE" else CaseState.BLOCKED
    case.decision = Decision(
        outcome=resolution.outcome,
        confidence=1.0,
        rationale=rationale,
        decided_at=state.clock.now(),
        decided_by="human",
        human_reviewer=resolution.decided_by,
    )
    await state.repo.save_case(case)

    await state.repo.append_posture_event({
        "event_id": precedent.precedent_id,
        "kind": "precedent_recorded",
        "occurred_at": state.clock.now().isoformat(),
        "case_id": case_id,
        "precedent_id": precedent.precedent_id,
        "outcome": resolution.outcome,
        "decided_by": resolution.decided_by,
        "rationale": rationale,
        "exposure_amount": str(case.exposure_amount),
        "total": str(result.total),
        "key": precedent.key.model_dump(mode="json"),
    })
    await state.emit("precedent_recorded", {
        "case_id": case_id,
        "precedent_id": precedent.precedent_id,
        "outcome": resolution.outcome,
        "decided_by": resolution.decided_by,
    })
    if case.session_id:
        try:
            await state.platform.memory.append_event(
                case.session_id, "precedent_recorded",
                {"precedent_id": precedent.precedent_id, "outcome": resolution.outcome,
                 "decided_by": resolution.decided_by},
                state.clock.now().isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            # The money has already moved and the case is already terminal. Journalling is the
            # last thing this handler does precisely because it is enrichment — raising here
            # would report a failed resolution to the reviewer that in fact succeeded, and
            # invite them to press the button a second time. The audit chain and the posture
            # event above are the record; this is working memory.
            await state.emit("precedent_unavailable", {
                "case_id": case_id, "error": repr(exc)[:200],
            })

    return {
        "ok": True,
        "case_id": case_id,
        "precedent_id": precedent.precedent_id,
        "outcome": resolution.outcome,
        "state": case.state.value,
    }
