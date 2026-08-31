"""FastAPI dependency wiring.

One dependency, deliberately: the assembled `AppState` built at startup. Routes never construct
a repository, a clock or a platform binding of their own, which is what keeps the whole system
injectable in tests.
"""
from __future__ import annotations

from fastapi import Request

from ..state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.interdict
