"""Interdict API."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import (
    audit,
    callback,
    cases,
    demo,
    events,
    inbox,
    posture,
    precedent,
    redteam,
    registry,
    tenants,
)
from .config import Settings
from .seed.generate import seed_all
from .seed.history import seed_history
from .seed.tenants import seed_tenants
from .state import build_state


class JsonFormatter(logging.Formatter):
    """Structured logs with case_id and agent on every line, per §2."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "case_id": getattr(record, "case_id", None),
            "agent": getattr(record, "agent", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in payload.items() if v is not None})


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = Settings()
    state = build_state(settings)
    app.state.interdict = state

    # Fail fast: a record run on a non-sanctioned provider would poison the replay cache that
    # the judged recording plays back.
    state.replay.assert_recordable(state.llm)

    restored = await state.replay.load()
    if restored:
        logging.getLogger("interdict").info(
            "replay cache: %d cached response(s) restored from disk", restored
        )

    await seed_all(state.repo, state.clock.now())
    await seed_tenants(state.repo, state.clock.now())
    await seed_history(state.repo, state.clock)

    # Crash recovery: anything left non-terminal by a previous process resumes now. This is the
    # same path beat 6 exercises, so it is exercised on every boot rather than only on camera.
    try:
        reports = await state.build_runner().resume_all()
        if reports:
            logging.getLogger("interdict").info(
                "resumed %d non-terminal case(s) on startup", len(reports)
            )
    except Exception:  # noqa: BLE001 - never block startup on recovery
        logging.getLogger("interdict").exception("startup resume failed")

    yield

    # Persist anything captured during a record run so the next process can replay it.
    try:
        written = await state.replay.flush()
        if written:
            logging.getLogger("interdict").info(
                "replay cache: %d response(s) written to disk", written
            )
    except Exception:  # noqa: BLE001
        logging.getLogger("interdict").exception("replay cache flush failed")
    state.kill()


app = FastAPI(
    title="Interdict",
    version="1.0.0",
    description="Agent fleet that refuses to release payment until the payee is independently "
                "verified. All data is synthetic.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (cases.router, registry.router, posture.router, audit.router,
               demo.router, events.router, callback.router, inbox.router,
               redteam.router, precedent.router, tenants.router):
    app.include_router(router)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    state = app.state.interdict
    return {
        "ok": True,
        "mode": state.settings.DEMO_MODE.value,
        "platform": state.platform.backend.value,
        "clock": state.clock.now().isoformat(),
        "synthetic_data": True,
    }


# --- single-container hosting ----------------------------------------------------------------
#
# Mounted LAST so every API route above still wins. Present only when a built front end exists,
# which is the case in the container image and not in local development, where Vite serves the
# app on its own port and proxies /api here.
#
# `html=True` makes the mount serve index.html for unknown paths, so a deep link into a surface
# reloads instead of 404ing.
_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if _WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web")
