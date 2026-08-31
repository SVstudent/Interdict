"""Demo control plane. One command per beat.

`kill_runner` genuinely cancels the in-flight task mid-step. The inherited implementation
broadcast a message and killed nothing, which would have made beat 6 theatre on camera
(DECISIONS D-001 F5).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..agents.scopes import ScopeViolation
from ..audit.nacha import AuditChain
from ..config import DEMO_EPOCH, DemoMode, FrozenClock, OffsetClock
from ..demo.replay import ReplayMiss
from ..models.domain import CaseState
from ..seed.generate import seed_all
from ..seed.history import seed_history
from ..seed.scenarios import CATALOG, as_dict, build_request
from ..seed.tenants import seed_tenants
from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/demo", tags=["demo"])


class ClockRequest(BaseModel):
    days: float = 0.0
    seconds: float = 0.0


@router.get("/scenarios")
async def scenarios() -> list[dict[str, Any]]:
    return [as_dict(s) for s in CATALOG.values()]


@router.post("/reset")
async def reset(state: AppState = Depends(get_state)) -> dict[str, Any]:
    started = time.perf_counter()
    state.kill()
    await state.repo.reset()
    # recall and exchange were missing here: a reset left the threat library and the
    # exchange holding entries that point at case ids the repository no longer has.
    for component in (state.platform.telemetry, state.platform.gateway, state.platform.memory,
                      state.platform.recall, state.platform.exchange):
        if hasattr(component, "reset"):
            component.reset()
    # Rewinding differs by clock. A FrozenClock returns to the fixed epoch so replay hashes stay
    # byte-identical; an OffsetClock drops its accumulated offset so a live rehearsal that ran
    # `+4 days` does not start the next take four days in the future.
    if isinstance(state.clock, FrozenClock):
        state.clock.set(DEMO_EPOCH)
    elif isinstance(state.clock, OffsetClock):
        state.clock.rewind()
    counts = await seed_all(state.repo, state.clock.now())
    # Added rather than merged: the second district's vendors and payments are additional rows in
    # the same store, and a reset that reported only Riverbend's would understate what was seeded.
    for key, value in (await seed_tenants(state.repo, state.clock.now())).items():
        counts[key] = counts.get(key, 0) + value
    counts["historical_cases"] = await seed_history(state.repo, state.clock)
    state.timings.clear()
    state.injection_seq = 0
    elapsed = time.perf_counter() - started
    await state.emit("demo_reset", {"seeded": counts, "elapsed_ms": int(elapsed * 1000)})
    # The runbook budgets 2s for reset because it is hit constantly during rehearsal.
    return {"ok": True, "seeded": counts, "elapsed_ms": int(elapsed * 1000),
            "within_budget": elapsed < 2.0}


async def _drive(state: AppState, case_id: str, payload: dict[str, Any]) -> None:
    runner = state.build_runner()
    case = await state.repo.get_case(case_id)
    if case and not case.session_id:
        case.session_id = await state.platform.memory.open_session(
            case_id, state.clock.now().isoformat()
        )
        await state.repo.save_case(case)
    with state.platform.telemetry.case_span(case_id=case_id):
        await runner.advance(case_id, payload)

    case = await state.repo.get_case(case_id)
    if case and case.session_id:
        await state.platform.memory.append_event(
            case.session_id, "findings_recorded",
            {"findings": [f.finding_id for f in case.findings],
             "state": case.state.value},
            state.clock.now().isoformat(),
        )
    if case and case.decision:
        request = await state.repo.get_request(case.request_id)
        screening = await state.platform.armor.screen(
            request.raw_artifact, request.artifact_metadata
        ) if request else None
        await AuditChain(state.repo, state.clock).emit(
            case, case.decision, screening=screening.as_dict() if screening else None
        )


def _request_id(state: AppState, label: str) -> str:
    """A request id that repeats across rehearsals but never collides within a run.

    Sequence rather than uuid4, because the id propagates into the case id and from there into
    finding ids and evidence excerpts — see the note in `sentry.open_case`. Rehearsing the same
    beat order after a reset therefore reproduces the same identifiers, which is the whole
    premise of a deterministic replay; injecting the same scenario twice still gets its own id.
    """
    state.injection_seq += 1
    return f"REQ-{label}-{state.injection_seq:03d}"


async def _inject(
    state: AppState,
    request,
    *,
    label: str,
    beat: str,
    callback_response: str | None,
    kill_mid_fanout: bool = False,
) -> dict[str, Any]:
    """Screen an artifact, open its case, and drive the pipeline. The one injection path.

    Both the scenario catalogue and the cross-district injection go through here so that a beat
    can never be demonstrated by a code path the other beats do not use. The tenant is not a
    parameter: `sentry.open_case` derives it from the targeted vendor, so a request aimed at a
    Harborview vendor opens a Harborview case without the endpoint asserting anything.
    """
    started = time.perf_counter()
    await state.repo.save_request(request)

    # Screen before any agent sees the artifact.
    screening = await state.platform.armor.screen(request.raw_artifact, request.artifact_metadata)
    if not screening.clean:
        await state.repo.append_posture_event({
            "event_id": f"PE-{uuid.uuid4().hex[:10].upper()}",
            "kind": "guardrail_screening",
            "occurred_at": state.clock.now().isoformat(),
            "request_id": request.request_id,
            "scenario_id": label,
            **screening.as_dict(),
        })

    sentry = state.agents["sentry"]
    case = await sentry.open_case(state.agent_ctx_for_request(request), request)
    await state.emit("case_opened", {"case_id": case.case_id, "scenario": label})

    payload: dict[str, Any] = {"callback_response": callback_response,
                               "claimed_reason": request.claimed_reason}
    task = asyncio.create_task(_drive(state, case.case_id, payload))
    state.track(case.case_id, task)

    if not kill_mid_fanout:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except ReplayMiss as exc:
            # Replay mode never invents a model response. Say so plainly rather than
            # degrading to a stub, which is the fakery §15 forbids.
            raise HTTPException(503, str(exc)) from exc
    state.timings[f"beat{beat}"] = time.perf_counter() - started

    # Persist immediately rather than only at shutdown: recording is slow and rate-limited, and
    # losing a completed scenario to a crash would mean paying for it twice.
    if state.settings.DEMO_MODE is DemoMode.RECORD:
        await state.replay.flush()

    result = await state.repo.get_case(case.case_id)
    return {
        "ok": True,
        "case_id": case.case_id,
        "tenant_id": result.tenant_id if result else None,
        "state": result.state.value if result else None,
        "outcome": result.decision.outcome if result and result.decision else None,
        "screening": screening.as_dict(),
        "elapsed_ms": int(state.timings[f"beat{beat}"] * 1000),
    }


@router.post("/inject_scenario/{scenario_id}")
async def inject_scenario(
    scenario_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    scenario = CATALOG.get(scenario_id.upper())
    if scenario is None:
        raise HTTPException(400, f"unknown scenario {scenario_id}; choose from {sorted(CATALOG)}")

    body = await _inject(
        state,
        build_request(
            scenario.scenario_id, state.clock.now(), _request_id(state, scenario.scenario_id)
        ),
        label=scenario.scenario_id,
        beat=scenario.beat,
        callback_response=scenario.callback_response,
        kill_mid_fanout=scenario.kill_mid_fanout,
    )
    return {**body, "scenario": as_dict(scenario)}


@router.post("/inject_cross_tenant")
async def inject_cross_tenant(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """The same operators hit the second district. Previously reachable only from a test.

    Cross-district recognition is one of the product's headline claims, and until this endpoint
    existed the only way to exercise it was `tests/test_tenancy.py` — so it could be asserted in
    CI but never shown in the running system. A capability with no path through the product is
    not a capability, and demonstrating one from a test harness on camera would be the fakery
    the operating rules forbid.

    Harborview shares no vendor with Riverbend and has blocked nothing. The recognition has to be
    earned from the exchange entry Riverbend contributed, on tradecraft alone.
    """
    from ..seed.tenants import CROSS_DISTRICT_CALLBACK, build_cross_district_request

    body = await _inject(
        state,
        build_cross_district_request(state.clock.now(), _request_id(state, "XT")),
        label="cross_tenant",
        beat="7x",
        callback_response=CROSS_DISTRICT_CALLBACK,
        kill_mid_fanout=False,
    )
    recognitions = await state.platform.exchange.recognitions()
    mine = [r for r in recognitions if r.get("case_id") == body["case_id"]]
    return {
        **body,
        "scenario": {
            "scenario_id": "XT",
            "slug": "cross_district_recognition",
            "headline": "The same operators hit the second district",
            "beat": "7x",
            "expected_outcome": "BLOCK",
        },
        "recognitions": mine,
        "recognised": bool(mine),
    }


@router.post("/advance_clock")
async def advance_clock(body: ClockRequest, state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Move the logical clock, then act on anything that became due.

    This is the scheduler tick. Advancing time is not just cosmetic: dormant cases waiting on a
    callback have a grace period, and once it lapses the case must stop waiting and decide.
    """
    if not isinstance(state.clock, (FrozenClock, OffsetClock)):
        raise HTTPException(409, "this clock cannot be advanced")
    now = state.clock.advance(days=body.days, seconds=body.seconds)
    await state.emit("clock_advanced", {"now": now.isoformat(), "days": body.days})

    woken = await _wake_expired_callbacks(state)
    return {"ok": True, "now": now.isoformat(), "woken": woken}


async def _wake_expired_callbacks(state: AppState) -> list[dict[str, Any]]:
    """Resume every dormant case whose callback grace period has lapsed.

    They resume with NO callback response, which is the truth: nobody called back. The
    adjudication rail then escalates them, because silence is never confirmation.
    """
    from datetime import timedelta

    grace = timedelta(hours=state.settings.CALLBACK_GRACE_HOURS)
    now = state.clock.now()
    woken: list[dict[str, Any]] = []

    for case in await state.repo.list_resumable_cases():
        if case.state is not CaseState.AWAITING_CALLBACK:
            continue
        if now - case.opened_at < grace:
            continue
        await state.emit("callback_window_expired", {
            "case_id": case.case_id,
            "waited_hours": int((now - case.opened_at).total_seconds() // 3600),
        })
        try:
            # `callback_window_expired` is what lets the fan-out stop suspending. Without it the
            # woken case re-evaluates the same unanswered callback and goes straight back to
            # sleep, so beats 4 and 5 never resolve.
            await _drive(state, case.case_id, {
                "callback_response": None, "callback_window_expired": True,
            })
        except Exception as exc:  # noqa: BLE001
            woken.append({"case_id": case.case_id, "error": repr(exc)[:160]})
            continue
        refreshed = await state.repo.get_case(case.case_id)
        woken.append({
            "case_id": case.case_id,
            "state": refreshed.state.value if refreshed else None,
            "outcome": refreshed.decision.outcome if refreshed and refreshed.decision else None,
        })
    return woken


@router.post("/kill_runner")
async def kill_runner(
    case_id: str | None = None, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    killed = state.kill(case_id)
    await state.emit("runner_killed", {"cases": killed})
    return {"ok": True, "killed": killed,
            "note": "in-flight tasks cancelled mid-step; state is whatever was checkpointed"}


@router.post("/resume_runner")
async def resume_runner(
    case_id: str | None = None, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    runner = state.build_runner()
    if case_id:
        case = await state.repo.get_case(case_id)
        if case is None:
            raise HTTPException(404, f"case {case_id} not found")
        payload = {"callback_response": "denied"}
        report = await runner.advance(case_id, payload)
        reports = [report.as_dict()]
    else:
        reports = [r.as_dict() for r in await runner.resume_all()]
    await state.emit("runner_resumed", {"reports": reports})
    return {"ok": True, "reports": reports}


@router.post("/force_scope_violation")
async def force_scope_violation(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Make `callback` attempt a banking read. It must raise and leave a posture event."""
    callback = state.agents["callback"]
    vendors = await state.repo.list_vendors()
    if not vendors:
        raise HTTPException(409, "seed the corpus first: POST /api/demo/reset")

    ctx = state.agent_ctx_for_request(None, case_id="SCOPE-PROBE")
    try:
        await callback.call_tool(ctx, "read_vendor_banking", vendor=vendors[0])
    except ScopeViolation as exc:
        await state.emit("scope_denied", {"agent": "callback", "policy": exc.policy_id})
        return {
            "ok": True, "denied": True, "agent": "callback", "scope": exc.scope,
            "policy_id": exc.policy_id, "message": str(exc),
        }
    raise HTTPException(500, "scope violation was NOT enforced — this is a defect, not a demo")


@router.get("/timings")
async def timings(state: AppState = Depends(get_state)) -> dict[str, Any]:
    return {
        "beats": {k: round(v, 3) for k, v in sorted(state.timings.items())},
        "mode": state.settings.DEMO_MODE.value,
        "platform": state.platform.backend.value,
    }
