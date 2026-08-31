"""Repository protocol.

Every persistence call in Interdict goes through this interface. No agent, route, or orchestrator
step touches a database client directly, which is what lets `make test` run against the in-memory
implementation with no cloud credentials while the recorded demo runs against Firestore.

The exactly-once guarantee lives in `record_effect`: it MUST be atomic (compare-and-set) and MUST
return the pre-existing row on collision rather than overwriting. Everything else is CRUD.
"""
from __future__ import annotations

from typing import Any, Protocol

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


class EffectOutcome:
    """Result of an idempotent write. `created` is False when the key was already present."""

    __slots__ = ("effect", "created")

    def __init__(self, effect: Effect, created: bool) -> None:
        self.effect = effect
        self.created = created

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"EffectOutcome(created={self.created}, key={self.effect.idempotency_key!r})"


class Repository(Protocol):
    # --- vendors -------------------------------------------------------------------
    # `tenant_id=None` means every tenant, which is what the single-district paths have always
    # asked for. Passing one partitions the money: a district must never be shown another
    # district's vendors, payments or cases.
    async def save_vendor(self, vendor: Vendor) -> None: ...
    async def get_vendor(self, vendor_id: str) -> Vendor | None: ...
    async def list_vendors(self, tenant_id: str | None = None) -> list[Vendor]: ...

    # --- invoices / payments -------------------------------------------------------
    async def save_invoice(self, invoice: Invoice) -> None: ...
    async def list_invoices(self, vendor_id: str) -> list[Invoice]: ...
    async def save_payment(self, payment: Payment) -> None: ...
    async def get_payment(self, payment_id: str) -> Payment | None: ...
    async def list_payments(
        self, vendor_id: str | None = None, tenant_id: str | None = None
    ) -> list[Payment]: ...
    async def get_payments(self, payment_ids: list[str]) -> list[Payment]: ...

    # --- requests / cases ----------------------------------------------------------
    async def save_request(self, request: ChangeRequest) -> None: ...
    async def get_request(self, request_id: str) -> ChangeRequest | None: ...
    async def save_case(self, case: Case) -> None: ...
    async def get_case(self, case_id: str) -> Case | None: ...
    async def list_cases(self, tenant_id: str | None = None) -> list[Case]: ...
    async def list_resumable_cases(self) -> list[Case]:
        """Non-terminal cases, for crash recovery on startup."""
        ...

    # --- durability ----------------------------------------------------------------
    async def append_checkpoint(self, checkpoint: Checkpoint) -> None: ...
    async def update_checkpoint(self, checkpoint: Checkpoint) -> None: ...
    async def list_checkpoints(self, case_id: str) -> list[Checkpoint]: ...
    async def next_checkpoint_seq(self, case_id: str) -> int: ...

    async def record_effect(self, effect: Effect) -> EffectOutcome:
        """Atomically claim `effect.idempotency_key`.

        Returns `created=True` with the new row if the key was free, or `created=False` with the
        ORIGINAL row if it was already claimed. Callers must short-circuit on `created=False` —
        this is what makes a double release impossible across a crash.
        """
        ...

    async def put_effect_result(self, key: str, result: dict[str, Any]) -> None:
        """Attach the outcome to an already-claimed key.

        Separate from `record_effect` on purpose: claiming and recording-the-result are different
        operations, and no caller may reset a claim by writing to it.
        """
        ...

    async def get_effect(self, key: str) -> Effect | None: ...
    async def list_effects(self, case_id: str | None = None) -> list[Effect]: ...

    # --- precedent -----------------------------------------------------------------
    # Narrow on purpose: matching is the platform port's job, not the store's. The repository
    # answers "what has this organisation decided", nothing more.
    async def save_precedent(self, precedent: Precedent) -> None: ...
    async def get_precedent(self, precedent_id: str) -> Precedent | None: ...
    async def list_precedents(self, tenant_id: str | None = None) -> list[Precedent]: ...

    # --- audit / posture / replay --------------------------------------------------
    async def append_audit_record(self, record: dict[str, Any]) -> None: ...
    async def list_audit_records(self) -> list[dict[str, Any]]: ...
    async def append_posture_event(self, event: dict[str, Any]) -> None: ...
    async def list_posture_events(self) -> list[dict[str, Any]]: ...
    async def get_replay(self, prompt_hash: str) -> dict[str, Any] | None: ...
    async def put_replay(self, prompt_hash: str, payload: dict[str, Any]) -> None: ...

    async def reset(self) -> None:
        """Clear all collections. Demo control plane requires this under 2 seconds."""
        ...
