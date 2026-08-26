"""Server-sent events. Agent progress reaches the console as it happens.

A spinner followed by a result is a failed beat, so every step, lane start, finding and decision
is pushed the moment it occurs rather than polled for.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ..state import AppState
from .deps import get_state

router = APIRouter(prefix="/api", tags=["events"])

HEARTBEAT_SECONDS = 15


@router.get("/events")
async def events(request: Request, state: AppState = Depends(get_state)) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    state.subscribers.append(queue)

    async def stream() -> AsyncGenerator[str, None]:
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # Comment frame: keeps proxies from closing an idle stream mid-demo.
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {payload['event']}\ndata: {json.dumps(payload, default=str)}\n\n"
        finally:
            if queue in state.subscribers:
                state.subscribers.remove(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
