"""Checkpoint log.

Written before a step runs, updated after it completes. On restart the runner replays this log to
decide what it may skip. The inherited implementation had the right shape but zero callers, so
resume re-executed everything — see DECISIONS D-001 F4.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import Clock
from ..models.domain import Case, CaseState, Checkpoint, CheckpointStatus
from .base import Repository


def stable_hash(data: Any) -> str:
    """Order-independent, type-stable digest. Used for both step inputs and outputs."""
    raw = json.dumps(data, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class CheckpointLog:
    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def completed_step(
        self, case_id: str, step: str, input_hash: str
    ) -> Checkpoint | None:
        """The completed checkpoint for this exact step+input, if one exists.

        Matching on input_hash rather than step name alone is what makes resume safe: a step
        re-entered with different inputs is genuinely different work and must run again.
        """
        for cp in await self._repo.list_checkpoints(case_id):
            if cp.step == step and cp.input_hash == input_hash and cp.is_complete:
                return cp
        return None

    async def begin(self, case: Case, step: str, step_input: Any) -> Checkpoint:
        input_hash = stable_hash(step_input)
        prior = [
            cp
            for cp in await self._repo.list_checkpoints(case.case_id)
            if cp.step == step and cp.input_hash == input_hash
        ]
        cp = Checkpoint(
            seq=await self._repo.next_checkpoint_seq(case.case_id),
            case_id=case.case_id,
            step=step,
            status=CheckpointStatus.STARTED,
            state_before=case.state,
            input_hash=input_hash,
            attempt=len(prior) + 1,
            started_at=self._clock.now(),
        )
        await self._repo.append_checkpoint(cp)
        return cp

    async def complete(
        self, cp: Checkpoint, state_after: CaseState, output: Any
    ) -> Checkpoint:
        cp.status = CheckpointStatus.COMPLETED
        cp.state_after = state_after
        cp.output_hash = stable_hash(output)
        cp.completed_at = self._clock.now()
        await self._repo.update_checkpoint(cp)
        return cp

    async def fail(self, cp: Checkpoint, error: str) -> Checkpoint:
        cp.status = CheckpointStatus.FAILED
        cp.output_hash = stable_hash({"error": error})
        cp.completed_at = self._clock.now()
        await self._repo.update_checkpoint(cp)
        return cp
