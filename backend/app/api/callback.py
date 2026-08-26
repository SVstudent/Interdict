"""Out-of-band callback resolution.

The whole product rests on one control: before money moves, a human speaks to the vendor on the
number the SYSTEM holds, never the number the request supplied. This endpoint is where that human
reports what they heard.

It exists so the verification in the recorded demo is real. The operator dials an actual phone,
has an actual conversation, and records the outcome here; the dormant case then wakes and the
fleet adjudicates on it. Nothing about that step is simulated.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..models.domain import CaseState
from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/cases", tags=["callback"])


class CallbackResult(BaseModel):
    outcome: Literal["confirmed", "denied", "no_answer"]
    verified_by: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)


@router.get("/{case_id}/callback")
async def callback_instructions(
    case_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """What the operator needs in order to make the call.

    Returns the number of record and, separately, any number the REQUEST supplied — shown so the
    operator can see the discrepancy, and explicitly flagged as the one not to dial.
    """
    case = await state.repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    vendor = await state.repo.get_vendor(case.vendor_id) if case.vendor_id else None
    request = await state.repo.get_request(case.request_id)
    supplied = (request.artifact_metadata.get("supplied_phone") if request else None)

    return {
        "case_id": case_id,
        "awaiting": case.state is CaseState.AWAITING_CALLBACK,
        "vendor_name": vendor.legal_name if vendor else None,
        "dial": vendor.contact_phone_of_record if vendor else None,
        "dial_source": "vendor master — the system of record",
        "request_supplied_number": supplied,
        "do_not_dial_reason": (
            "This number came from the change request itself. Dialling it would let whoever "
            "sent the request verify their own request."
        ) if supplied else None,
        "script": (
            f"Ask for someone in accounts receivable at {vendor.legal_name}. "
            "Ask whether they submitted a change to their remittance bank details this week. "
            "Do not read the new account details to them — ask them to state the change."
        ) if vendor else None,
    }


@router.post("/{case_id}/callback")
async def record_callback(
    case_id: str, result: CallbackResult, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Record what the vendor said, then wake the case and let the fleet decide."""
    case = await state.repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    if case.state.is_terminal:
        raise HTTPException(409, f"case {case_id} is already {case.state.value}")

    await state.repo.append_posture_event({
        "event_id": f"CB-{case_id}",
        "kind": "out_of_band_callback",
        "occurred_at": state.clock.now().isoformat(),
        "case_id": case_id,
        "outcome": result.outcome,
        "verified_by": result.verified_by or "operator",
        "notes": result.notes,
        "dialled": (await state.repo.get_vendor(case.vendor_id)).contact_phone_of_record
                   if case.vendor_id else None,
        "source": "vendor master — the system of record",
    })
    await state.emit("callback_recorded", {
        "case_id": case_id, "outcome": result.outcome,
        "verified_by": result.verified_by or "operator",
    })

    if case.session_id:
        await state.platform.memory.append_event(
            case.session_id, "callback_recorded",
            {"outcome": result.outcome, "verified_by": result.verified_by or "operator"},
            state.clock.now().isoformat(),
        )

    # "no_answer" is not a null result — it is the finding. Silence is never confirmation, so the
    # case proceeds to adjudication and the rails escalate it rather than releasing.
    from .demo import _drive

    payload = {"callback_response": None if result.outcome == "no_answer" else result.outcome}
    await _drive(state, case_id, payload)

    refreshed = await state.repo.get_case(case_id)
    return {
        "ok": True,
        "case_id": case_id,
        "recorded": result.outcome,
        "state": refreshed.state.value if refreshed else None,
        "outcome": refreshed.decision.outcome if refreshed and refreshed.decision else None,
    }
