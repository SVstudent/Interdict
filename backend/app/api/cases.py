from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..models.domain import SIMULATION_TENANT_ID, CaseState
from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api", tags=["cases"])


def _summary(case) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "tenant_id": case.tenant_id,
        "vendor_id": case.vendor_id,
        "state": case.state.value,
        "exposure_amount": str(case.exposure_amount),
        "opened_at": case.opened_at.isoformat(),
        "deadline_at": case.deadline_at.isoformat(),
        "finding_count": len(case.findings),
        "outcome": case.decision.outcome if case.decision else None,
        "session_id": case.session_id,
    }


def _is_district(row_tenant_id: str) -> bool:
    """The red team's sandbox is a tenant for partitioning, not a district with money.

    Its cases are fictional and its vendors are minted per trial, so an unscoped listing that
    included them would put an invented interdiction in an operator's docket.
    """
    return row_tenant_id != SIMULATION_TENANT_ID


@router.get("/cases")
async def list_cases(
    tenant_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
) -> list[dict[str, Any]]:
    # Omitting tenant_id returns every district, which is what the single-district surfaces have
    # always asked for. Passing one partitions the docket.
    cases = [c for c in await state.repo.list_cases(tenant_id) if _is_district(c.tenant_id)]
    # Scoped to the same district as the cases, so one district's queue can never render another
    # district's supplier name through the join.
    vendors = {v.vendor_id: v for v in await state.repo.list_vendors(tenant_id)}
    rows = []
    for case in cases:
        row = _summary(case)
        vendor = vendors.get(case.vendor_id) if case.vendor_id else None
        row["vendor_name"] = vendor.legal_name if vendor else "Unresolved vendor"
        row["hold_remaining_hours"] = max(
            0, int((case.deadline_at - state.clock.now()).total_seconds() // 3600)
        )
        rows.append(row)
    # Exposure descending so the largest case sits at the top of the docket queue.
    return sorted(rows, key=lambda r: Decimal(r["exposure_amount"]), reverse=True)


@router.get("/cases/{case_id}")
async def get_case(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    case = await state.repo.get_case(case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    vendor = await state.repo.get_vendor(case.vendor_id) if case.vendor_id else None
    request = await state.repo.get_request(case.request_id)
    payments = await state.repo.get_payments(case.held_payment_ids)
    return {
        **_summary(case),
        "vendor": vendor.model_dump(mode="json") if vendor else None,
        "request": request.model_dump(mode="json") if request else None,
        "held_payments": [p.model_dump(mode="json") for p in payments],
        "findings": [f.model_dump(mode="json") for f in case.findings],
        "challenge": case.challenge.model_dump(mode="json") if case.challenge else None,
        "decision": case.decision.model_dump(mode="json") if case.decision else None,
    }


@router.get("/cases/{case_id}/trace")
async def get_trace(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {"case_id": case_id, "spans": state.platform.telemetry.tree(case_id)}


@router.get("/cases/{case_id}/checkpoints")
async def get_checkpoints(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    checkpoints = await state.repo.list_checkpoints(case_id)
    effects = await state.repo.list_effects(case_id)
    return {
        "case_id": case_id,
        "checkpoints": [c.model_dump(mode="json") for c in checkpoints],
        "effects": [e.model_dump(mode="json") for e in effects],
    }


@router.get("/cases/{case_id}/memory")
async def get_memory(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    case = await state.repo.get_case(case_id)
    if case is None or not case.session_id:
        return {"case_id": case_id, "session_id": None, "events": [], "age_days": None}
    events = await state.platform.memory.rehydrate(case.session_id)
    age = (state.clock.now() - case.opened_at).days
    return {
        "case_id": case_id,
        "session_id": case.session_id,
        "age_days": age,
        "events": [
            {"event_id": e.event_id, "kind": e.kind, "occurred_at": e.occurred_at,
             "payload": e.payload}
            for e in events
        ],
    }


@router.get("/threat-library")
async def threat_library(
    tenant_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    """The fleet's accumulated threat intelligence: named operations, newest first.

    Each entry is a dossier Scribe wrote after an interdiction — designation, assessment,
    tradecraft, indicators and a predicted next target — paired with the structured fingerprint
    used to retrieve it.
    """
    return {
        "known_operations": await state.platform.recall.known_count(tenant_id),
        "operations": await state.platform.recall.library(tenant_id),
    }


@router.get("/impact")
async def impact(
    tenant_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    """The counterfactual: money that would have left had nobody intervened.

    Blocked exposure is loss the organisation did not take. Escalated exposure is loss still
    pending a human decision. Reported separately because conflating them would overclaim.
    """
    prevented = Decimal("0")
    pending = Decimal("0")
    released = Decimal("0")
    blocked_cases = 0
    for case in await state.repo.list_cases(tenant_id):
        if not _is_district(case.tenant_id):
            continue
        if case.state is CaseState.BLOCKED:
            prevented += case.exposure_amount
            blocked_cases += 1
        elif case.state is CaseState.ESCALATED:
            pending += case.exposure_amount
        elif case.state is CaseState.RELEASED:
            released += case.exposure_amount

    # Sized against the published per-incident average so the figure has a referent.
    IC3_AVERAGE_LOSS = Decimal("122000")
    return {
        "prevented_loss": str(prevented),
        "pending_human_decision": str(pending),
        "released_after_verification": str(released),
        "interdictions": blocked_cases,
        "equivalent_average_incidents": float(
            (prevented / IC3_AVERAGE_LOSS).quantize(Decimal("0.1"))
        ) if prevented else 0.0,
        "benchmark": {
            "source": "FBI IC3 2025",
            "average_bec_loss_per_complaint": str(IC3_AVERAGE_LOSS),
        },
        "known_attacker_operations": await state.platform.recall.known_count(tenant_id),
        "as_of": state.clock.now().isoformat(),
    }


@router.get("/sweeps")
async def sweeps(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Proactive holds: payments the fleet froze on its own initiative after identifying an
    operation, before any fraudulent request arrived for them."""
    events = [e for e in await state.repo.list_posture_events()
              if e.get("kind") == "proactive_sweep"]
    total = sum((Decimal(str(e.get("frozen_total", "0"))) for e in events), Decimal("0"))
    return {
        "sweeps": list(reversed(events)),
        "payments_frozen": sum(len(e.get("frozen", [])) for e in events),
        "value_frozen": str(total),
    }


@router.get("/vendors")
async def list_vendors(
    tenant_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
) -> list[dict[str, Any]]:
    return [v.model_dump(mode="json") for v in await state.repo.list_vendors(tenant_id)
            if _is_district(v.tenant_id)]


@router.get("/ledger")
async def ledger_totals(
    tenant_id: str | None = Query(default=None),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    buckets = {"held": Decimal("0"), "released": Decimal("0"),
               "blocked": Decimal("0"), "escalated": Decimal("0")}
    counts = dict.fromkeys(buckets, 0)
    for case in await state.repo.list_cases(tenant_id):
        if not _is_district(case.tenant_id):
            continue
        key = {
            CaseState.RELEASED: "released", CaseState.BLOCKED: "blocked",
            CaseState.ESCALATED: "escalated",
        }.get(case.state, "held")
        buckets[key] += case.exposure_amount
        counts[key] += 1
    return {
        "totals": {k: str(v) for k, v in buckets.items()},
        "counts": counts,
        "as_of": state.clock.now().isoformat(),
    }
