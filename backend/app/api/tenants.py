"""Tenants and the shared threat exchange — F3.

No prefix: /api/exchange is a peer surface to /api/tenants, not a child of it. The exchange
belongs to no single district, which is the whole point of it.

Every read here is partitioned by tenant except the exchange feed, which is partitioned by
nothing — that asymmetry is the feature, so the surfaces make it visible rather than implicit.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..models.domain import SHARED_EXCHANGE_ID, CaseState, Tenant
from ..seed.tenants import TENANTS
from ..state import AppState

# The docket's own row shape rather than a second derivation of it: a tenant's case list that
# drifted from /api/cases would be two contracts for one object, and the UI renders both with
# the same CaseSummary type.
from .cases import _summary
from .deps import get_state

router = APIRouter(tags=["tenants"])

# What a published exchange entry deliberately does not carry. Checked against the entries
# themselves rather than asserted, so the claim cannot rot: if `publish()` ever started carrying
# one of these, the field would drop out of this list and the UI would stop claiming it was
# withheld instead of quietly lying about it.
NEVER_PUBLISHED = (
    "vendor_id", "vendor_name", "legal_name", "amount", "exposure_amount",
    "invoice_id", "held_payment_ids", "contact_phone_of_record", "account_last4",
)


async def _summarise(state: AppState, spec: Tenant) -> dict[str, Any]:
    cases = await state.repo.list_cases(spec.tenant_id)
    vendors = await state.repo.list_vendors(spec.tenant_id)

    # Held and blocked are reported apart for the same reason /api/impact keeps them apart:
    # money still frozen pending a decision is not money the district has saved.
    held = sum((c.exposure_amount for c in cases if not c.state.is_terminal), Decimal("0"))
    blocked = sum((c.exposure_amount for c in cases if c.state is CaseState.BLOCKED),
                  Decimal("0"))

    entries = await state.platform.exchange.entries()
    recognitions = await state.platform.exchange.recognitions()
    return {
        **spec.model_dump(mode="json"),
        "vendor_count": len(vendors),
        "open_cases": sum(1 for c in cases if not c.state.is_terminal),
        "exposure_held": str(held),
        "blocked_total": str(blocked),
        "contributed": sum(1 for e in entries
                           if e["contributed_by_tenant_id"] == spec.tenant_id),
        "recognised_from_exchange": sum(1 for r in recognitions
                                        if r["tenant_id"] == spec.tenant_id),
    }


@router.get("/api/tenants")
async def list_tenants(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {
        "tenants": [await _summarise(state, spec) for spec in TENANTS.values()],
        "exchange_id": SHARED_EXCHANGE_ID,
    }


@router.get("/api/tenants/{tenant_id}")
async def get_tenant(tenant_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    spec = TENANTS.get(tenant_id)
    if spec is None:
        raise HTTPException(404, f"tenant {tenant_id} not found")

    cases = await state.repo.list_cases(tenant_id)
    vendors = await state.repo.list_vendors(tenant_id)
    # Resolved from this district's book alone. Reaching for the whole vendor table to put a name
    # on a row would mean one district's page could render another district's vendor name.
    by_id = {v.vendor_id: v for v in vendors}
    rows = []
    for case in cases:
        row = _summary(case)
        vendor = by_id.get(case.vendor_id) if case.vendor_id else None
        row["vendor_name"] = vendor.legal_name if vendor else "Unresolved vendor"
        row["hold_remaining_hours"] = max(
            0, int((case.deadline_at - state.clock.now()).total_seconds() // 3600)
        )
        rows.append(row)

    return {
        **await _summarise(state, spec),
        "vendors": [v.model_dump(mode="json") for v in vendors],
        "cases": rows,
    }


def _key_names(value: Any) -> set[str]:
    """Every key name appearing anywhere in a published entry, at any depth."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys |= _key_names(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _key_names(child)
    return keys


@router.get("/api/exchange")
async def exchange_feed(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """What crossed, when, and from which district to which — and what did not cross.

    Entries and recognitions are passed through exactly as the port returns them. Reshaping them
    here would let this surface claim something the exchange does not actually store.
    """
    entries = await state.platform.exchange.entries()
    published = set().union(*(_key_names(e) for e in entries)) if entries else set()
    return {
        "exchange_id": SHARED_EXCHANGE_ID,
        "members": [await _summarise(state, spec) for spec in TENANTS.values()],
        "entries": entries,
        "recognitions": await state.platform.exchange.recognitions(),
        "withheld": [f for f in NEVER_PUBLISHED if f not in published],
    }
