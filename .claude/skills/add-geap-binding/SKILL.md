---
name: add-geap-binding
description: Add a new GEAP platform binding as a Protocol with paired GEAP and local implementations plus a parity test. Use when wiring any Gemini Enterprise Agent Platform capability into backend/app/platform/.
---

# Adding a GEAP binding

Every GEAP capability is a Protocol with two implementations. `make test` runs with **no cloud
credentials**, so the local implementation is not optional and is not a stub — it must produce the
same case outcomes as the GEAP one.

## Steps
1. **Define the Protocol** in `backend/app/platform/<capability>.py`. Narrow surface — only the
   methods the fleet actually calls. Do not mirror the whole REST API.
2. **Implement `Geap<Capability>`** against the verified REST surface in `context/PLATFORM.md`.
   Read the method page before writing; do not infer shapes from the resource name.
3. **Implement `Local<Capability>`** backed by Firestore/in-process state.
4. **Register both** in `platform/factory.py`, selected by `settings.PLATFORM_BACKEND`.
5. **Add the parity test** asserting identical outcomes across all five scenarios (test 18).
6. Record the targeted API version and any allowlisting requirement in `context/DECISIONS.md`.

## Template

```python
# backend/app/platform/memory.py
from typing import Protocol, Sequence
from ..models import Finding

class MemoryPort(Protocol):
    async def open_session(self, case_id: str) -> str: ...
    async def append_event(self, session_id: str, kind: str, payload: dict) -> None: ...
    async def rehydrate(self, session_id: str) -> Sequence[Finding]: ...


class GeapMemory:
    """Backed by reasoningEngines.sessions + appendEvent."""
    async def open_session(self, case_id: str) -> str: ...


class LocalMemory:
    """Backed by Firestore `sessions/` + `session_events/`. Same semantics, no cloud."""
    async def open_session(self, case_id: str) -> str: ...
```

## Parity test shape
```python
@pytest.mark.parametrize("scenario", ["S1", "S2", "S3", "S4", "S5"])
@pytest.mark.parametrize("backend", ["local", "geap"])
async def test_platform_parity(scenario, backend, expected_outcomes):
    case = await run_scenario(scenario, platform=make_platform(backend))
    assert case.decision.outcome == expected_outcomes[scenario]
```
Skip the `geap` leg when credentials are absent — but **fail loudly**, never silently pass:
`pytest.skip("GEAP credentials absent")`.

## Why this matters
If Agent Registry, Memory Bank, or Agent Gateway turns out to need allowlisting we don't have
before the deadline, we swap one binding. Without the abstraction we'd be rewriting the fleet
during the last week. See `context/PLATFORM.md` for what is still unconfirmed.
