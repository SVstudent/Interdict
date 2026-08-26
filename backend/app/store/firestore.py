"""Firestore-backed Repository.

Runs against the emulator locally (`FIRESTORE_EMULATOR_HOST`) with no credentials, and against
real Firestore on Cloud Run via ADC. The only subtle method is `record_effect`, which uses a
`create()` inside a transaction so that two concurrent releases cannot both observe an empty slot
— that is the exactly-once guarantee, and it must be enforced by the database, not by the caller.
"""
from __future__ import annotations

import asyncio
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore

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

VENDORS = "vendors"
INVOICES = "invoices"
PAYMENTS = "payments"
REQUESTS = "change_requests"
CASES = "cases"
CHECKPOINTS = "checkpoints"      # subcollection of a case
EFFECTS = "effects"
PRECEDENTS = "precedents"
AUDIT = "audit_records"
POSTURE = "posture_events"
REPLAY = "replay_cache"

ALL_COLLECTIONS = (VENDORS, INVOICES, PAYMENTS, REQUESTS, CASES, EFFECTS, PRECEDENTS,
                   AUDIT, POSTURE)


def _dump(model) -> dict[str, Any]:
    return model.model_dump(mode="json")


class FirestoreRepository:
    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._db = firestore.AsyncClient(project=project_id, database=database)

    # --- helpers ------------------------------------------------------------------
    async def _set(self, collection: str, doc_id: str, payload: dict[str, Any]) -> None:
        await self._db.collection(collection).document(doc_id).set(payload)

    async def _get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        snap = await self._db.collection(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    async def _all(self, collection: str) -> list[dict[str, Any]]:
        return [d.to_dict() async for d in self._db.collection(collection).stream()]

    # --- vendors ------------------------------------------------------------------
    async def save_vendor(self, vendor: Vendor) -> None:
        await self._set(VENDORS, vendor.vendor_id, _dump(vendor))

    async def get_vendor(self, vendor_id: str) -> Vendor | None:
        raw = await self._get(VENDORS, vendor_id)
        return Vendor(**raw) if raw else None

    async def list_vendors(self, tenant_id: str | None = None) -> list[Vendor]:
        col = self._db.collection(VENDORS)
        q = col.where("tenant_id", "==", tenant_id) if tenant_id else col
        return [Vendor(**d.to_dict()) async for d in q.stream()]

    # --- invoices / payments ------------------------------------------------------
    async def save_invoice(self, invoice: Invoice) -> None:
        await self._set(INVOICES, invoice.invoice_id, _dump(invoice))

    async def list_invoices(self, vendor_id: str) -> list[Invoice]:
        q = self._db.collection(INVOICES).where("vendor_id", "==", vendor_id)
        return [Invoice(**d.to_dict()) async for d in q.stream()]

    async def save_payment(self, payment: Payment) -> None:
        await self._set(PAYMENTS, payment.payment_id, _dump(payment))

    async def get_payment(self, payment_id: str) -> Payment | None:
        raw = await self._get(PAYMENTS, payment_id)
        return Payment(**raw) if raw else None

    async def list_payments(
        self, vendor_id: str | None = None, tenant_id: str | None = None
    ) -> list[Payment]:
        q = self._db.collection(PAYMENTS)
        if vendor_id:
            q = q.where("vendor_id", "==", vendor_id)
        if tenant_id:
            q = q.where("tenant_id", "==", tenant_id)
        return [Payment(**d.to_dict()) async for d in q.stream()]

    async def get_payments(self, payment_ids: list[str]) -> list[Payment]:
        if not payment_ids:
            return []
        docs = await asyncio.gather(*(self.get_payment(p) for p in payment_ids))
        return [d for d in docs if d is not None]

    # --- requests / cases ---------------------------------------------------------
    async def save_request(self, request: ChangeRequest) -> None:
        await self._set(REQUESTS, request.request_id, _dump(request))

    async def get_request(self, request_id: str) -> ChangeRequest | None:
        raw = await self._get(REQUESTS, request_id)
        return ChangeRequest(**raw) if raw else None

    async def save_case(self, case: Case) -> None:
        await self._set(CASES, case.case_id, _dump(case))

    async def get_case(self, case_id: str) -> Case | None:
        raw = await self._get(CASES, case_id)
        return Case(**raw) if raw else None

    async def list_cases(self, tenant_id: str | None = None) -> list[Case]:
        col = self._db.collection(CASES)
        q = col.where("tenant_id", "==", tenant_id) if tenant_id else col
        cases = [Case(**d.to_dict()) async for d in q.stream()]
        return sorted(cases, key=lambda c: c.opened_at, reverse=True)

    async def list_resumable_cases(self) -> list[Case]:
        return [c for c in await self.list_cases() if not c.state.is_terminal]

    # --- durability ---------------------------------------------------------------
    def _checkpoints(self, case_id: str):
        return self._db.collection(CASES).document(case_id).collection(CHECKPOINTS)

    async def append_checkpoint(self, checkpoint: Checkpoint) -> None:
        await self._checkpoints(checkpoint.case_id).document(
            str(checkpoint.seq)
        ).set(_dump(checkpoint))

    async def update_checkpoint(self, checkpoint: Checkpoint) -> None:
        await self.append_checkpoint(checkpoint)

    async def list_checkpoints(self, case_id: str) -> list[Checkpoint]:
        rows = [Checkpoint(**d.to_dict()) async for d in self._checkpoints(case_id).stream()]
        return sorted(rows, key=lambda c: c.seq)

    async def next_checkpoint_seq(self, case_id: str) -> int:
        return len(await self.list_checkpoints(case_id)) + 1

    async def record_effect(self, effect: Effect) -> EffectOutcome:
        """Atomic claim. `create()` fails if the document already exists, which is exactly the
        compare-and-set we need; the loser reads the winner's row and short-circuits."""
        ref = self._db.collection(EFFECTS).document(effect.idempotency_key)
        try:
            await ref.create(_dump(effect))
            return EffectOutcome(effect, created=True)
        except gexc.AlreadyExists:
            snap = await ref.get()
            return EffectOutcome(Effect(**snap.to_dict()), created=False)

    async def put_effect_result(self, key: str, result: dict[str, Any]) -> None:
        ref = self._db.collection(EFFECTS).document(key)
        snap = await ref.get()
        if not snap.exists:
            raise KeyError(f"cannot attach a result to unclaimed key {key!r}")
        await ref.update({"result": result})

    async def get_effect(self, key: str) -> Effect | None:
        raw = await self._get(EFFECTS, key)
        return Effect(**raw) if raw else None

    async def list_effects(self, case_id: str | None = None) -> list[Effect]:
        col = self._db.collection(EFFECTS)
        q = col.where("case_id", "==", case_id) if case_id else col
        return [Effect(**d.to_dict()) async for d in q.stream()]

    # --- precedent ----------------------------------------------------------------
    async def save_precedent(self, precedent: Precedent) -> None:
        await self._set(PRECEDENTS, precedent.precedent_id, _dump(precedent))

    async def get_precedent(self, precedent_id: str) -> Precedent | None:
        raw = await self._get(PRECEDENTS, precedent_id)
        return Precedent(**raw) if raw else None

    async def list_precedents(self, tenant_id: str | None = None) -> list[Precedent]:
        col = self._db.collection(PRECEDENTS)
        q = col.where("tenant_id", "==", tenant_id) if tenant_id else col
        rows = [Precedent(**d.to_dict()) async for d in q.stream()]
        return sorted(rows, key=lambda p: p.decided_at, reverse=True)

    # --- audit / posture / replay -------------------------------------------------
    async def append_audit_record(self, record: dict[str, Any]) -> None:
        await self._set(AUDIT, record["record_id"], record)

    async def list_audit_records(self) -> list[dict[str, Any]]:
        rows = await self._all(AUDIT)
        return sorted(rows, key=lambda r: r.get("record_id", ""))

    async def append_posture_event(self, event: dict[str, Any]) -> None:
        await self._set(POSTURE, event["event_id"], event)

    async def list_posture_events(self) -> list[dict[str, Any]]:
        rows = await self._all(POSTURE)
        return sorted(rows, key=lambda e: e.get("occurred_at", ""))

    async def get_replay(self, prompt_hash: str) -> dict[str, Any] | None:
        return await self._get(REPLAY, prompt_hash)

    async def put_replay(self, prompt_hash: str, payload: dict[str, Any]) -> None:
        await self._set(REPLAY, prompt_hash, payload)

    async def reset(self) -> None:
        """Wipe case state. The replay cache survives — it is fixture data, not state."""
        for collection in ALL_COLLECTIONS:
            docs = [d async for d in self._db.collection(collection).stream()]
            if collection == CASES:
                for doc in docs:
                    subs = [s async for s in doc.reference.collection(CHECKPOINTS).stream()]
                    await asyncio.gather(*(s.reference.delete() for s in subs))
            await asyncio.gather(*(d.reference.delete() for d in docs))
