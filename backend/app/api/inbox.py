"""The business office inbox.

`GET /api/inbox` is the morning's post. `POST /api/inbox/process` hands the whole thing to Sentry,
which decides on its own which messages deserve the fleet and opens cases for those.

The endpoint reports how the triage was reached, not just what it concluded — how many messages
were settled without a model call, and how many needed one. That ratio is the argument: the fleet
is affordable because it is pointed only where it is needed.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends

from ..seed.inbox import build_inbox
from ..seed.scenarios import CATALOG, build_request
from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _materialise(state: AppState) -> list:
    """The inbox with scenario bodies filled in from their fixtures."""
    messages = build_inbox(state.clock.now())
    for message in messages:
        if message.scenario_id and message.scenario_id in CATALOG:
            request = build_request(
                message.scenario_id, state.clock.now(), f"REQ-{message.scenario_id}"
            )
            message.body = request.raw_artifact
            meta = request.artifact_metadata
            message.sender_name = "Accounts Receivable"
            message.sender_email = str(meta.get("from", "—"))
            message.metadata = {k: str(v) for k, v in meta.items() if v is not None}
    return messages


@router.get("")
async def read_inbox(state: AppState = Depends(get_state)) -> dict[str, Any]:
    messages = _materialise(state)
    return {
        "messages": [m.as_dict() for m in messages],
        "count": len(messages),
    }


@router.post("/process")
async def process_inbox(state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Triage every message, then run the fleet on whatever survives triage.

    Triage runs concurrently — it is cheap and mostly free. The resulting CASES are driven one at
    a time on purpose: each is six model calls across a bursty fan-out, and firing three of those
    at once is what trips the provider's requests-per-minute ceiling.
    """
    from .demo import _drive

    messages = _materialise(state)
    sentry = state.agents["sentry"]

    async def triage(message):
        ctx = state.agent_ctx_for_request(None, case_id=f"TRIAGE-{message.message_id}")
        try:
            return await sentry.triage(ctx, message)
        except Exception:  # noqa: BLE001 - a triage failure must not swallow the message
            from ..agents.sentry import TriageVerdict

            return TriageVerdict(
                message.message_id, "investigate", 0.0,
                "Triage unavailable; escalated rather than dropped.", used_model=True,
            )

    verdicts = list(await asyncio.gather(*(triage(m) for m in messages)))
    await state.emit("inbox_triaged", {
        "total": len(messages),
        "investigate": sum(1 for v in verdicts if v.investigate),
        "model_calls": sum(1 for v in verdicts if v.used_model),
    })

    by_id = {m.message_id: m for m in messages}
    opened: list[dict[str, Any]] = []

    for verdict in verdicts:
        if not verdict.investigate:
            continue
        message = by_id[verdict.message_id]
        if not message.scenario_id:
            # Flagged, but we have no structured change request behind it. Surface it for a
            # human rather than inventing one.
            opened.append({
                "message_id": message.message_id,
                "subject": message.subject,
                "case_id": None,
                "note": "Flagged at intake; no structured change request to open a case from.",
            })
            continue

        request = build_request(
            message.scenario_id, state.clock.now(), f"REQ-{uuid.uuid4().hex[:8].upper()}"
        )
        await state.repo.save_request(request)

        screening = await state.platform.armor.screen(
            request.raw_artifact, request.artifact_metadata
        )
        if not screening.clean:
            await state.repo.append_posture_event({
                "event_id": f"PE-{uuid.uuid4().hex[:10].upper()}",
                "kind": "guardrail_screening",
                "occurred_at": state.clock.now().isoformat(),
                "request_id": request.request_id,
                "scenario_id": message.scenario_id,
                **screening.as_dict(),
            })

        case = await sentry.open_case(state.agent_ctx_for_request(request), request)
        await state.emit("case_opened", {
            "case_id": case.case_id,
            "message_id": message.message_id,
            "subject": message.subject,
        })

        scenario = CATALOG[message.scenario_id]
        await _drive(state, case.case_id, {
            "callback_response": scenario.callback_response,
            "claimed_reason": request.claimed_reason,
        })
        result = await state.repo.get_case(case.case_id)
        opened.append({
            "message_id": message.message_id,
            "subject": message.subject,
            "case_id": case.case_id,
            "state": result.state.value if result else None,
            "outcome": result.decision.outcome if result and result.decision else None,
        })

    free = sum(1 for v in verdicts if not v.used_model)
    return {
        "ok": True,
        "messages_read": len(messages),
        "triage": {
            "investigate": sum(1 for v in verdicts if v.investigate),
            "ignored": sum(1 for v in verdicts if not v.investigate),
            "settled_without_a_model_call": free,
            "model_calls": len(verdicts) - free,
        },
        "cases_opened": opened,
        "verdicts": [v.as_dict() for v in verdicts],
    }
