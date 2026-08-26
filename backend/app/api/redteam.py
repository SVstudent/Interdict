"""Red Team — F1.

`POST /api/redteam/run` COSTS MODEL CALLS: one variant-generation call, then a full case per
variant. It is flagged as such in schemas/_api_contract.json and must stay flagged.

Which is why it defaults to `dry_run`. A dry run generates the attacks and returns them without
executing any of them, so the capability can be inspected — and the variants read — for the price
of a single call rather than six per variant. Spending the real money has to be asked for.

Runs are persisted as posture events. A hit rate is only worth reading as a series: one run saying
"caught 4 of 5" is an anecdote, and the number that matters is whether it moves when the fleet
changes.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..agents.redteam import RedTeamRun
from ..demo.replay import ReplayMiss
from ..services.simulation import SIMULATION_TENANT_ID, run_variant, target_brief
from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/redteam", tags=["redteam"])

# Five is the ceiling because a run is a full fan-out per variant on top of the generation call.
MAX_VARIANTS = 5


class RunRequest(BaseModel):
    variants: int = 3
    # Defaulted so that a client which knows nothing about the cost — including the generated
    # TypeScript one — cannot spend a district's Vertex quota by pressing a button once.
    dry_run: bool = True


@router.get("/runs")
async def list_runs(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Every run, newest first, plus the accumulated scoreboard across all of them."""
    runs = await _stored_runs(state)
    return {"runs": runs, "scoreboard": _scoreboard(runs)}


@router.get("/runs/{run_id}")
async def read_run(run_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    run = next((r for r in await _stored_runs(state) if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, f"red team run {run_id} not found")
    return run


@router.post("/run")
async def start_run(
    body: RunRequest | None = None, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    """Generate a batch of attacks and, unless this is a dry run, execute them."""
    request = body or RunRequest()
    count = max(1, min(request.variants, MAX_VARIANTS))
    agent = state.agents["redteam"]

    run = RedTeamRun(
        run_id=f"RT-{uuid.uuid4().hex[:10].upper()}",
        tenant_id=SIMULATION_TENANT_ID,
        started_at=state.clock.now().isoformat(),
        model=agent.model,
    )
    await state.emit("redteam_run_started", {
        "run_id": run.run_id, "tenant_id": run.tenant_id, "variants": count,
    })

    ctx = state.agent_ctx_for_request(None, case_id=run.run_id)
    ctx.payload["simulation_target"] = target_brief()
    try:
        # Through the tool, so the generator sees tradecraft and not the district's victims.
        library = await agent.call_tool(
            ctx, "read_threat_library",
            operations=await state.platform.recall.library(),
        )
        run.variants = await agent.invent(ctx, library, count)
    except ReplayMiss as exc:
        # Replay mode never invents a model response, and a red team running against a stub of
        # itself would be measuring nothing at all.
        raise HTTPException(503, str(exc)) from exc

    for variant in run.variants:
        await state.emit("redteam_variant_generated", {
            "run_id": run.run_id, "variant": variant.as_dict(),
        })

    if not request.dry_run:
        for variant in run.variants:
            trial = await run_variant(state, variant)
            run.trials.append(trial)
            await state.emit("redteam_trial_completed", {
                "run_id": run.run_id, "trial": trial.as_dict(),
            })

    run.completed_at = state.clock.now().isoformat()
    await _persist(state, run)
    await state.emit("redteam_run_completed", {
        "run_id": run.run_id,
        "caught": run.caught,
        "total": len(run.trials),
        "hit_rate": run.hit_rate,
        "escaped": [t.as_dict() for t in run.trials if not t.caught],
    })
    return run.as_dict()


async def _persist(state: AppState, run: RedTeamRun) -> None:
    await state.repo.append_posture_event({
        "event_id": run.run_id,
        "kind": "redteam_run",
        "occurred_at": run.completed_at,
        "run": run.as_dict(),
    })


async def _stored_runs(state: AppState) -> list[dict[str, Any]]:
    events = await state.repo.list_posture_events()
    return [e["run"] for e in reversed(events) if e.get("kind") == "redteam_run"]


def _scoreboard(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The number the feature exists to produce, across every run rather than the last one.

    Dry runs contribute variants and no trials, so they move the generated count and leave the
    hit rate alone — an attack that was never executed has neither been caught nor missed.
    """
    trials = [t for run in runs for t in run["trials"]]
    caught = sum(1 for t in trials if t["caught"])
    return {
        "runs": len(runs),
        "variants_generated": sum(len(run["variants"]) for run in runs),
        "trials": len(trials),
        "caught": caught,
        "hit_rate": round(caught / len(trials), 3) if trials else 0.0,
        "escaped": [t for t in trials if not t["caught"]],
    }
