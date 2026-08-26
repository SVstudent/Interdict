"""Payment holds, releases and blocks — the only code allowed to move money.

Every mutating call takes an idempotency_key and claims it through `Repository.record_effect`
BEFORE acting. On a claim collision the call short-circuits and returns the original result. This
is the property beat 6 demonstrates and test 1 proves: a crash between the effect write and the
process exiting cannot produce a second release.

The inherited implementation recorded the key, logged a warning, and then carried on anyway —
guarding a no-op, since it had no payment documents at all (DECISIONS D-001 F8).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config import Clock
from ..models.domain import Case, Effect, Payment, PaymentStatus
from ..store.base import Repository


@dataclass(frozen=True)
class PaymentActionResult:
    action: str
    payment_ids: list[str]
    total: Decimal
    replayed: bool  # True when the idempotency key was already claimed


def hold_key(case_id: str) -> str:
    return f"{case_id}:hold"


def terminal_key(case_id: str, action: str) -> str:
    return f"{case_id}:{action.lower()}"


class PaymentService:
    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def _claim(
        self, key: str, case_id: str, action: str, payload: dict
    ) -> tuple[bool, dict]:
        outcome = await self._repo.record_effect(
            Effect(
                idempotency_key=key,
                case_id=case_id,
                action=action,
                payload=payload,
                recorded_at=self._clock.now(),
            )
        )
        return outcome.created, outcome.effect.result

    async def hold_scheduled_payments(self, case: Case, vendor_id: str) -> PaymentActionResult:
        """Freeze every scheduled payment for the vendor and set exposure to their exact sum."""
        key = hold_key(case.case_id)
        created, prior = await self._claim(key, case.case_id, "HOLD", {"vendor_id": vendor_id})
        if not created:
            return PaymentActionResult(
                "HOLD", prior.get("payment_ids", []), Decimal(prior.get("total", "0")), True
            )

        candidates = [
            p
            for p in await self._repo.list_payments(vendor_id)
            if p.status is PaymentStatus.SCHEDULED
        ]
        total = Decimal("0")
        ids: list[str] = []
        for p in candidates:
            p.status = PaymentStatus.HELD
            p.held_by_case_id = case.case_id
            await self._repo.save_payment(p)
            total += p.amount
            ids.append(p.payment_id)

        case.held_payment_ids = ids
        case.exposure_amount = total
        # Invariant 3, asserted at the point of mutation rather than trusted.
        case.assert_exposure_matches(await self._repo.get_payments(ids))
        await self._persist_effect_result(key, {"payment_ids": ids, "total": str(total)})
        return PaymentActionResult("HOLD", ids, total, False)

    async def freeze_proactively(
        self, payment_ids: list[str], origin_case_id: str, designation: str
    ) -> PaymentActionResult:
        """Freeze payments nobody complained about, on the fleet's own initiative.

        Keyed on the originating case so a re-run of the sweep cannot double-freeze, and so the
        audit trail records WHY each payment stopped: the operation that triggered it.
        """
        key = f"{origin_case_id}:sweep"
        created, prior = await self._claim(
            key, origin_case_id, "SWEEP_FREEZE",
            {"payment_ids": payment_ids, "designation": designation},
        )
        if not created:
            return PaymentActionResult(
                "SWEEP_FREEZE", prior.get("payment_ids", []),
                Decimal(prior.get("total", "0")), True,
            )

        total = Decimal("0")
        frozen: list[str] = []
        for payment in await self._repo.get_payments(payment_ids):
            if payment.status is not PaymentStatus.SCHEDULED:
                continue  # already held or resolved; never reopen a settled payment
            payment.status = PaymentStatus.HELD
            payment.held_by_case_id = origin_case_id
            await self._repo.save_payment(payment)
            total += payment.amount
            frozen.append(payment.payment_id)

        await self._persist_effect_result(key, {"payment_ids": frozen, "total": str(total)})
        return PaymentActionResult("SWEEP_FREEZE", frozen, total, False)

    async def finalize(self, case: Case, action: str) -> PaymentActionResult:
        """Apply the terminal decision. `action` is RELEASE or BLOCK."""
        if action not in ("RELEASE", "BLOCK"):
            raise ValueError(f"unsupported terminal payment action: {action}")

        key = terminal_key(case.case_id, action)
        created, prior = await self._claim(
            key, case.case_id, action, {"payment_ids": case.held_payment_ids}
        )
        if not created:
            # Exactly-once: a resumed runner reaching this line again is a logged no-op.
            return PaymentActionResult(
                action, prior.get("payment_ids", []), Decimal(prior.get("total", "0")), True
            )

        new_status = PaymentStatus.RELEASED if action == "RELEASE" else PaymentStatus.BLOCKED
        total = Decimal("0")
        for p in await self._repo.get_payments(case.held_payment_ids):
            p.status = new_status
            await self._repo.save_payment(p)
            total += p.amount

        await self._persist_effect_result(
            key, {"payment_ids": case.held_payment_ids, "total": str(total)}
        )
        return PaymentActionResult(action, list(case.held_payment_ids), total, False)

    async def _persist_effect_result(self, key: str, result: dict) -> None:
        await self._repo.put_effect_result(key, result)
