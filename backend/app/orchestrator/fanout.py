"""Parallel verification fan-out, tolerant of partial failure.

Genuinely concurrent (`asyncio.gather`), unlike the inherited sequential try/except chain
(DECISIONS D-001 F6). Four lanes start together and stream findings to the console as each one
lands, which is what makes parallelism visible in beat 2 rather than merely asserted.

A lane that fails, times out, or returns an invalid Finding does not sink the case: its absence
becomes a recorded gap the Adjudicator must weigh. That is the answer to "how does the system
recover if a worker agent loops or returns a hallucination?"
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..models.domain import Finding
from .runner import StepContext


@dataclass
class LaneResult:
    agent: str
    finding: Finding | None = None
    error: str | None = None
    started_ms: int = 0
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.finding is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "ok": self.ok,
            "error": self.error,
            "started_ms": self.started_ms,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FanoutReport:
    lanes: list[LaneResult] = field(default_factory=list)
    wall_ms: int = 0

    @property
    def findings(self) -> list[Finding]:
        return [lane.finding for lane in self.lanes if lane.finding is not None]

    @property
    def failures(self) -> list[LaneResult]:
        return [lane for lane in self.lanes if not lane.ok]

    @property
    def concurrent(self) -> bool:
        """True when lanes genuinely overlapped rather than running back to back.

        Asserted by the rehearsal skill: if total lane time greatly exceeds wall time, the lanes
        ran together; if they are near-equal, something serialised them.
        """
        total = sum(lane.duration_ms for lane in self.lanes)
        return bool(self.lanes) and total > self.wall_ms * 1.3

    def as_dict(self) -> dict[str, Any]:
        return {
            "lanes": [lane.as_dict() for lane in self.lanes],
            "wall_ms": self.wall_ms,
            "concurrent": self.concurrent,
            "finding_count": len(self.findings),
            "failure_count": len(self.failures),
        }


class VerificationFanout:
    """Runs the four verification agents concurrently.

    `stagger_seconds` offsets each lane's start. It is not a throttle on the work — all four lanes
    are still in flight together, which is what beat 2 shows — it just flattens the instantaneous
    request spike. Vertex limits requests per minute, and four simultaneous calls plus the
    downstream reasoning agents was reliably tripping 429 RESOURCE_EXHAUSTED, whose backoff cost
    far more wall-clock than the stagger does.
    """

    def __init__(
        self, agents: dict[str, Any], make_agent_ctx,
        timeout_seconds: float = 45.0, stagger_seconds: float = 0.6,
    ) -> None:
        self._agents = agents
        self._make_ctx = make_agent_ctx
        self._timeout = timeout_seconds
        self._stagger = stagger_seconds

    async def __call__(self, ctx: StepContext) -> list[Finding]:
        report = await self.run(ctx)
        # Record the shape of the fan-out so Posture and the rehearsal can show it.
        await ctx.repo.append_posture_event({
            "event_id": f"PE-FANOUT-{ctx.case.case_id}",
            "kind": "fanout_completed",
            "occurred_at": ctx.clock.now().isoformat(),
            "case_id": ctx.case.case_id,
            **report.as_dict(),
        })
        return report.findings

    async def run(self, ctx: StepContext) -> FanoutReport:
        origin = time.perf_counter()
        report = FanoutReport()

        async def lane(name: str, slot: int) -> LaneResult:
            if slot and self._stagger:
                await asyncio.sleep(slot * self._stagger)
            agent = self._agents[name]
            started = time.perf_counter()
            result = LaneResult(agent=name, started_ms=int((started - origin) * 1000))
            await ctx.emit("lane_started", {"case_id": ctx.case.case_id, "agent": name})
            try:
                agent_ctx = self._make_ctx(ctx, name)
                finding = await asyncio.wait_for(agent.run(agent_ctx), timeout=self._timeout)
                result.finding = finding
                await ctx.emit("finding_added", {
                    "case_id": ctx.case.case_id, **finding.model_dump(mode="json")
                })
            except TimeoutError:
                result.error = f"{name} exceeded {self._timeout}s and was cut off"
            except ValidationError as exc:
                # A model that asserted a verdict without citing evidence. The Finding never
                # validates, so the claim cannot reach adjudication.
                result.error = f"{name} returned an uncitable finding: {exc.error_count()} error(s)"
            except Exception as exc:  # noqa: BLE001 - a lane must not sink the case
                result.error = f"{name} failed: {exc!r}"
            finally:
                result.duration_ms = int((time.perf_counter() - started) * 1000)
            if result.error:
                await ctx.emit("lane_failed", {
                    "case_id": ctx.case.case_id, "agent": name, "error": result.error
                })
            return result

        report.lanes = list(
            await asyncio.gather(*(lane(n, i) for i, n in enumerate(self._agents)))
        )
        report.wall_ms = int((time.perf_counter() - origin) * 1000)
        return report
