# Repository guide

Orientation for anyone — human or agent — reading this codebase for the first time. It says where
the load-bearing code is, what each piece guarantees, and which test proves it.

**Everything below is checkable.** `./scripts/verify_claims.sh` executes every claim in the README
and prints pass/fail; it runs credential-free.

---

## Read these six files first

In this order. Together they are about 1,800 lines and they contain every claim the project makes.

| # | File | What it guarantees | Proved by |
|---|---|---|---|
| 1 | `backend/app/agents/adk_runtime.py` | **The only place Google ADK is constructed.** Every reasoning step is an `LlmAgent` on a `Runner`, tools declared as `FunctionTool`s, scope gate in `before_tool_callback`. No second path, no direct-API fallback | `tests/test_adk_runtime.py` |
| 2 | `backend/app/models/domain.py` | **Invariants are validators, not prose.** A committed verdict citing no evidence raises at construction — confabulation is a schema violation here | `tests/test_invariants.py` |
| 3 | `backend/app/config.py` | Thresholds and the injected `Clock`. Every number the rails use lives here, never in a prompt | `tests/test_no_wallclock.py` |
| 4 | `backend/app/agents/scopes.py` | `FLEET_SCOPES` — twelve identity grants, each with explicit denials and a policy id | `tests/test_adk_runtime.py` |
| 5 | `backend/app/orchestrator/runner.py` | The durable runner: checkpoint before each step, complete after, idempotent effects ledger | `tests/test_durability.py` |
| 6 | `backend/app/agents/base.py` | `VERDICT_RUBRIC` and `TOOL_PROTOCOL`, both hashed into the prompt. Load-bearing — see the note below | `tests/test_prompt_determinism.py` |

---

## Layout

```
backend/app/
  agents/        twelve agents + the ADK runtime that executes them + identity scopes
  api/           11 FastAPI routers
  audit/         hash-chained Nacha Phase 2 audit records
  guardrails/    inbound artifact screening; runs before any agent parses anything
  models/        the Pydantic domain model — invariants live here as validators
  orchestrator/  durable runner, pipeline steps, concurrent fan-out
  platform/      nine Protocol bindings, each with a GEAP and a local implementation
  services/      payments (the only code allowed to move money) + red-team sandbox
  store/         Repository (in-memory + Firestore), checkpoint log, effects ledger
backend/tests/   255 tests, credential-free
context/         the durable spec + DECISIONS.md, the judgment log
reference/       inherited code kept for reading only — does not import, does not run
```

---

## Five rules this codebase holds to

1. **All GEAP access goes through `platform/` Protocols.** An agent never calls a Google Cloud API
   directly. This is what lets the full suite run with no credentials.
2. **All time reads come from the injected `Clock`.** `tests/test_no_wallclock.py` greps
   `backend/app/` and fails the build on any `datetime.now()`. Without this, `advance_clock` would
   be a fixture swap rather than a real four-day jump.
3. **A Finding with a non-`inconclusive` verdict and empty evidence fails validation.**
   `inconclusive` is the only verdict permitted to cite nothing.
4. **Side-effecting tools take an `idempotency_key` and short-circuit on a ledger hit.** This is
   what makes release exactly-once across a crash.
5. **Anything reaching a prompt must be stable across runs.** Case, finding and request ids are
   derived rather than random, and the two adversarial agents sort their inputs, because the
   fan-out completes in arbitrary order.

---

## Things that look wrong and are not

- **`reference/inherited/` does not import and is not tested.** It is one file from a prior
  scaffold, kept for its rule shapes, with its defects documented in `context/DECISIONS.md` D-001.
  It is deliberately outside `backend/app/`.
- **`VERDICT_RUBRIC` is never paraphrased per agent.** Without an explicit shared definition both
  Flash tiers read `supports` as "supports my analysis" and returned it for blatant fraud — which
  the Adjudicator counts toward RELEASE. One shared rubric, hashed with the prompt. See D-011.
- **`TOOL_PROTOCOL` is a latency control, not decoration.** Declaring tools without telling the
  model its observations were already gathered made it re-fetch what it had just been handed, and
  pushed the flagship case from ~50s past the 70s budget.
- **`MAX_LLM_CALLS_PER_STEP = 4` looks aggressive.** ADK defaults to 500, which is a runaway guard
  for a long-lived assistant, not a budget for a step whose observations are already gathered. The
  expected tool-call count is zero.
- **A step skipped because the case moved past it is reported the same as one skipped by checkpoint
  match.** Deliberate: the crash-resume demo has to *show* that nothing re-executed.

---

## Running it

```bash
make test                    # 255 tests, replay mode, no credentials
make check-schema            # fails if schemas/ drifted from the Pydantic models
./scripts/verify_claims.sh   # executes every README claim, prints pass/fail
ruff check backend scripts   # lint; config and per-rule rationale in pyproject.toml
```

Live setup, Google Cloud provisioning and deployment are in [README.md](README.md).
Architecture is in [ARCHITECTURE.md](ARCHITECTURE.md) and `docs/interdict-architecture.pdf`.
The reasoning behind every significant call — and every rejected alternative — is in
`context/DECISIONS.md`.
