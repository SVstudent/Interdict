"""Durable case runner.

Advances a case one step at a time. Before each step it writes a checkpoint; after the step it
records the result. On restart it replays the checkpoint log and skips any step already completed
with the same input, so a process that dies mid-fan-out resumes without re-executing work and
without emitting a second side effect.

Steps are injected rather than hard-coded so that Phase 2 can plug in the ADK agent fleet without
touching the state machine. The state machine is the part that must not be parallelised or
improvised (§15).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import Clock
from ..models.domain import (
    Case,
    CaseState,
    IllegalTransition,
    assert_transition,
)
from ..store.base import Repository
from ..store.checkpoint import CheckpointLog

log = logging.getLogger("interdict.runner")


class CaseSuspended(Exception):
    """Raised internally when a case must go dormant (e.g. awaiting a vendor callback)."""


@dataclass
class StepOutcome:
    next_state: CaseState
    output: dict[str, Any] = field(default_factory=dict)
    suspend: bool = False


@dataclass
class StepContext:
    case: Case
    repo: Repository
    clock: Clock
    emit: Callable[[str, dict[str, Any]], Awaitable[None]]
    payload: dict[str, Any] = field(default_factory=dict)


class Step(Protocol):
    name: str

    def input_for(self, ctx: StepContext) -> Any:
        """Everything that determines this step's result. Hashed into the checkpoint, so a step
        re-entered with different inputs correctly runs again instead of being skipped."""
        ...

    async def run(self, ctx: StepContext) -> StepOutcome: ...

    def applies_to(self, state: CaseState) -> bool: ...


@dataclass
class RunReport:
    case_id: str
    executed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    final_state: CaseState = CaseState.OPENED
    suspended: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "executed": self.executed,
            "skipped": self.skipped,
            "final_state": self.final_state.value,
            "suspended": self.suspended,
        }


class CaseRunner:
    def __init__(
        self,
        repo: Repository,
        clock: Clock,
        steps: Sequence[Step],
        emit: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._repo = repo
        self._clock = clock
        self._steps = list(steps)
        self._log = CheckpointLog(repo, clock)
        self._emit = emit or self._noop_emit

    @staticmethod
    async def _noop_emit(event: str, data: dict[str, Any]) -> None:
        return None

    async def _transition(self, case: Case, to: CaseState) -> None:
        if to == case.state:
            return
        assert_transition(case.case_id, case.state, to)
        frm = case.state
        case.state = to
        await self._repo.save_case(case)
        await self._emit(
            "state_changed",
            {"case_id": case.case_id, "from": frm.value, "to": to.value},
        )

    async def advance(self, case_id: str, payload: dict[str, Any] | None = None) -> RunReport:
        """Drive the case as far as it will go. Safe to call repeatedly and after a crash."""
        case = await self._repo.get_case(case_id)
        if case is None:
            raise ValueError(f"case {case_id} not found")

        report = RunReport(case_id=case_id, final_state=case.state)
        if case.state.is_terminal:
            return report

        ctx = StepContext(
            case=case,
            repo=self._repo,
            clock=self._clock,
            emit=self._emit,
            payload=payload or {},
        )

        # Steps already completed in an earlier run of this case. Beat 6 shows this list, so a
        # step passed over because the case has moved beyond it must be reported as skipped
        # rather than silently ignored — "nothing re-executed" has to be visible, not inferred.
        completed_steps = {
            cp.step for cp in await self._repo.list_checkpoints(case_id) if cp.is_complete
        }

        for step in self._steps:
            case = ctx.case
            if case.state.is_terminal:
                break
            if not step.applies_to(case.state):
                if step.name in completed_steps:
                    report.skipped.append(step.name)
                continue

            step_input = step.input_for(ctx)
            done = await self._log.completed_step(case_id, step.name, _hash_input(step_input))
            if done is not None:
                # Already ran with these exact inputs. This is the line that makes crash-resume
                # cheap and makes a duplicate side effect impossible.
                report.skipped.append(step.name)
                if done.state_after is not None and done.state_after != case.state:
                    await self._transition(case, done.state_after)
                    report.final_state = case.state
                continue

            cp = await self._log.begin(case, step.name, step_input)
            await self._emit("step_started", {"case_id": case_id, "step": step.name})
            try:
                outcome = await step.run(ctx)
            except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
                await self._log.fail(cp, repr(exc))
                await self._emit(
                    "step_failed", {"case_id": case_id, "step": step.name, "error": repr(exc)}
                )
                raise

            await self._transition(case, outcome.next_state)
            await self._log.complete(cp, case.state, outcome.output)
            await self._repo.save_case(case)
            report.executed.append(step.name)
            report.final_state = case.state
            await self._emit(
                "step_completed",
                {"case_id": case_id, "step": step.name, "state": case.state.value},
            )

            if outcome.suspend:
                report.suspended = True
                break

        await self._repo.save_case(ctx.case)
        report.final_state = ctx.case.state
        return report

    async def resume_all(self) -> list[RunReport]:
        """Startup recovery: pick up every non-terminal case from its last completed checkpoint."""
        reports: list[RunReport] = []
        for case in await self._repo.list_resumable_cases():
            try:
                reports.append(await self.advance(case.case_id))
            except IllegalTransition:
                log.exception("case %s could not be resumed", case.case_id)
        return reports


def _hash_input(step_input: Any) -> str:
    from ..store.checkpoint import stable_hash

    return stable_hash(step_input)
