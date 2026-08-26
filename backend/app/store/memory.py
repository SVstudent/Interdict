"""In-memory Repository.

Used by the whole test suite and by `DEMO_MODE=replay` rehearsals. It is not a toy: it enforces
the same atomicity contract as Firestore, because the durability tests are only meaningful if the
implementation they run against can actually fail the way the real one would.
"""
from __future__ import annotations

import asyncio
import copy
from typing import Any

from ..models.domain import (
    Case,
    ChangeRequest,
    Checkpoint,
    Effect,
    Invoice,
    Payment,
    Precedent,
    Vendor,
)
from .base import EffectOutcome


class InMemoryRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._vendors: dict[str, Vendor] = {}
        self._invoices: dict[str, Invoice] = {}
        self._payments: dict[str, Payment] = {}
        self._requests: dict[str, ChangeRequest] = {}
        self._cases: dict[str, Case] = {}
        self._checkpoints: dict[str, list[Checkpoint]] = {}
        self._effects: dict[str, Effect] = {}
        self._precedents: dict[str, Precedent] = {}
        self._audit: list[dict[str, Any]] = []
        self._posture: list[dict[str, Any]] = []
        self._replay: dict[str, dict[str, Any]] = {}

    # Stored objects are deep-copied on the way in and out. Without this, a caller mutating a
    # returned Case would silently edit "persisted" state and the crash-resume tests would pass
    # for the wrong reason.
    @staticmethod
    def _clone(obj):
        return copy.deepcopy(obj)

    # --- vendors -------------------------------------------------------------------
    async def save_vendor(self, vendor: Vendor) -> None:
        self._vendors[vendor.vendor_id] = self._clone(vendor)

    async def get_vendor(self, vendor_id: str) -> Vendor | None:
        v = self._vendors.get(vendor_id)
        return self._clone(v) if v else None

    async def list_vendors(self, tenant_id: str | None = None) -> list[Vendor]:
        return [self._clone(v) for v in self._vendors.values()
                if tenant_id is None or v.tenant_id == tenant_id]

    # --- invoices / payments -------------------------------------------------------
    async def save_invoice(self, invoice: Invoice) -> None:
        self._invoices[invoice.invoice_id] = self._clone(invoice)

    async def list_invoices(self, vendor_id: str) -> list[Invoice]:
        return [self._clone(i) for i in self._invoices.values() if i.vendor_id == vendor_id]

    async def save_payment(self, payment: Payment) -> None:
        self._payments[payment.payment_id] = self._clone(payment)

    async def get_payment(self, payment_id: str) -> Payment | None:
        p = self._payments.get(payment_id)
        return self._clone(p) if p else None

    async def list_payments(
        self, vendor_id: str | None = None, tenant_id: str | None = None
    ) -> list[Payment]:
        vals = self._payments.values()
        if vendor_id is not None:
            vals = [p for p in vals if p.vendor_id == vendor_id]
        if tenant_id is not None:
            vals = [p for p in vals if p.tenant_id == tenant_id]
        return [self._clone(p) for p in vals]

    async def get_payments(self, payment_ids: list[str]) -> list[Payment]:
        return [self._clone(self._payments[p]) for p in payment_ids if p in self._payments]

    # --- requests / cases ----------------------------------------------------------
    async def save_request(self, request: ChangeRequest) -> None:
        self._requests[request.request_id] = self._clone(request)

    async def get_request(self, request_id: str) -> ChangeRequest | None:
        r = self._requests.get(request_id)
        return self._clone(r) if r else None

    async def save_case(self, case: Case) -> None:
        self._cases[case.case_id] = self._clone(case)

    async def get_case(self, case_id: str) -> Case | None:
        c = self._cases.get(case_id)
        return self._clone(c) if c else None

    async def list_cases(self, tenant_id: str | None = None) -> list[Case]:
        return sorted(
            (self._clone(c) for c in self._cases.values()
             if tenant_id is None or c.tenant_id == tenant_id),
            key=lambda c: c.opened_at,
            reverse=True,
        )

    async def list_resumable_cases(self) -> list[Case]:
        return [self._clone(c) for c in self._cases.values() if not c.state.is_terminal]

    # --- durability ----------------------------------------------------------------
    async def append_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._checkpoints.setdefault(checkpoint.case_id, []).append(self._clone(checkpoint))

    async def update_checkpoint(self, checkpoint: Checkpoint) -> None:
        rows = self._checkpoints.setdefault(checkpoint.case_id, [])
        for i, existing in enumerate(rows):
            if existing.seq == checkpoint.seq:
                rows[i] = self._clone(checkpoint)
                return
        rows.append(self._clone(checkpoint))

    async def list_checkpoints(self, case_id: str) -> list[Checkpoint]:
        return [self._clone(c) for c in sorted(
            self._checkpoints.get(case_id, []), key=lambda c: c.seq
        )]

    async def next_checkpoint_seq(self, case_id: str) -> int:
        return len(self._checkpoints.get(case_id, [])) + 1

    async def record_effect(self, effect: Effect) -> EffectOutcome:
        # The lock is the in-memory stand-in for a Firestore transaction. Two concurrent
        # release attempts must not both observe an empty slot.
        async with self._lock:
            existing = self._effects.get(effect.idempotency_key)
            if existing is not None:
                return EffectOutcome(self._clone(existing), created=False)
            self._effects[effect.idempotency_key] = self._clone(effect)
            return EffectOutcome(self._clone(effect), created=True)

    async def put_effect_result(self, key: str, result: dict[str, Any]) -> None:
        async with self._lock:
            existing = self._effects.get(key)
            if existing is None:
                raise KeyError(f"cannot attach a result to unclaimed key {key!r}")
            existing.result = self._clone(result)

    async def get_effect(self, key: str) -> Effect | None:
        e = self._effects.get(key)
        return self._clone(e) if e else None

    async def list_effects(self, case_id: str | None = None) -> list[Effect]:
        vals = self._effects.values()
        if case_id is not None:
            vals = [e for e in vals if e.case_id == case_id]
        return [self._clone(e) for e in vals]

    # --- precedent -----------------------------------------------------------------
    async def save_precedent(self, precedent: Precedent) -> None:
        self._precedents[precedent.precedent_id] = self._clone(precedent)

    async def get_precedent(self, precedent_id: str) -> Precedent | None:
        p = self._precedents.get(precedent_id)
        return self._clone(p) if p else None

    async def list_precedents(self, tenant_id: str | None = None) -> list[Precedent]:
        return sorted(
            (self._clone(p) for p in self._precedents.values()
             if tenant_id is None or p.tenant_id == tenant_id),
            key=lambda p: p.decided_at,
            reverse=True,
        )

    # --- audit / posture / replay --------------------------------------------------
    async def append_audit_record(self, record: dict[str, Any]) -> None:
        self._audit.append(self._clone(record))

    async def list_audit_records(self) -> list[dict[str, Any]]:
        return [self._clone(r) for r in self._audit]

    async def append_posture_event(self, event: dict[str, Any]) -> None:
        self._posture.append(self._clone(event))

    async def list_posture_events(self) -> list[dict[str, Any]]:
        return [self._clone(e) for e in self._posture]

    async def get_replay(self, prompt_hash: str) -> dict[str, Any] | None:
        r = self._replay.get(prompt_hash)
        return self._clone(r) if r else None

    async def put_replay(self, prompt_hash: str, payload: dict[str, Any]) -> None:
        self._replay[prompt_hash] = self._clone(payload)

    async def reset(self) -> None:
        self._vendors.clear()
        self._invoices.clear()
        self._payments.clear()
        self._requests.clear()
        self._cases.clear()
        self._checkpoints.clear()
        self._effects.clear()
        self._precedents.clear()
        self._audit.clear()
        self._posture.clear()
        # replay cache deliberately survives reset: it is fixture data, not case state.
