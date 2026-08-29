# Interdict — Working Memory

## What this is
Vendor-payment fraud (BEC) works by getting a human to update remittance bank details from a
clean-looking email. Interdict sits at the last controllable moment before money leaves and
refuses to release payment until the payee is independently verified by an agent fleet.

## The demo is the product
The deliverable is a 4-minute **unedited** recording. Judges will not run this repo.
The beats are in `context/DEMO_RUNBOOK.md`. Before any change, ask which beat it serves.
Code that improves the product but produces no visible beat is deprioritized.
Code that produces a beat but is faked is disqualifying.

## Non-negotiables
- Gemini 3.x only. `gemini-3.6-flash` routine; `gemini-3.1-pro-preview` ONLY Challenger + Adjudicator.
- Real Google ADK agents (`google-adk` 2.7.1) with real tool definitions. Not API calls in a loop.
- All GEAP access goes through `backend/app/platform/` protocols. Never call GEAP from an agent.
- All time reads from the injected Clock. Never `datetime.now()`. A test enforces this.
- A Finding with a non-inconclusive verdict and empty evidence must fail validation.
- Side-effecting tools take an `idempotency_key` and check `effects/` first — and SHORT-CIRCUIT on hit.
- `--oxblood` is reserved for `contradicts` findings and BLOCK. Nowhere else. ~4 uses total.
- All data is synthetic. No real companies, people, banks, or emails. Persistent UI banner.

## Inherited-code warning
`untitled/` is a prior full-stack attempt that *looks* finished and is not. Zero LLM calls,
no ADK, no Firestore, dead checkpoint code, `kill_runner` is a no-op, sequential "parallel"
fan-out, forbidden palette. See `context/DECISIONS.md` D-001 for the file-by-file verdict.
**Never assume a file from that tree does what its name or docstring says.** Read it.

## Commands
make dev / make test / make seed / make rehearse / make deploy
make schemas       regenerate schemas/ from Pydantic (18 files; commit them)
make check-schema  fail if schemas/ drifted from the models
make record        populate the replay cache from live models — COSTS ~$0.06, see CACHE.md
make probe-geap    re-verify GEAP surfaces and locations

## Docs map
CLAUDE.md      this file — fast index, current state, gotchas
CACHE.md       the replay cache: modes, keying, recording, cost, gotchas
schemas/       generated JSON Schema files + _api_contract.json + _invariants.json
context/*.md   the durable spec; on conflict context/ wins and you fix CLAUDE.md

## Architecture at a glance
FastAPI + ADK fleet behind a durable case state machine (checkpoint before each step,
idempotent effects ledger for exactly-once release). GEAP bindings live behind Protocols
in `platform/` with GEAP + local impls so `make test` runs credential-free.
React/Vite front end with four surfaces: Console, Docket, Registry, Posture.
See `ARCHITECTURE.md`.

## Current state
12 agents, 230 tests, four surfaces, two tenants. tsc + vite build clean. LIGHT theme.
Capabilities: inbox triage -> case -> 4-lane fan-out -> adversarial challenge -> deterministic
rails -> named threat dossier -> proactive sweep -> cross-case attribution -> cross-TENANT
exchange -> human precedent. Plus a Red Team that attacks the fleet and scores it.

VERIFIED LIVE, whole runbook, three consecutive clean runs (2026-08-29): 57 checks, 0 failures.
  Every beat asserted on substance, not just status: BLOCK with 4 evidenced findings and a named
  safety rail; the literal injected sentence struck through; abstention; clock wake -> ESCALATE;
  kill+resume skipping hold_payments and begin_verification; hash-chained audit; identity denial;
  cross-district recognition at Harborview; ledger totals. `/tmp/interdict-run/runthrough.py`.
BEAT 2 ON CAMERA: hold 2.5s | lanes 2.7s | findings 10.9-12.4s | steelman defeated 24.2s |
  VERDICT 30.4s. The injection request returns ~65s but that tail is background learning work.
REPLAY serves the whole runbook offline, no credentials, ~1.8s per scenario, identical outcomes.
  TODO  deploy, video. README + ARCHITECTURE written.

## Environment (verified 2026-08-24)
Project `interdict-demo-57216` (num 192346570826), org `<org-id redacted>`, billing ENABLED.
Owned by `<project-owner account>` — ADC on this machine is ALREADY that account with quota_project set.
The other gcloud CLI accounts on this machine CANNOT see this project; use ADC.
`<account B>`'s own billing accounts are both CLOSED — that account cannot host Vertex.
Enabled: aiplatform, run, firestore, pubsub, modelarmor, networkservices, cloudscheduler.
THREE different location values in one system:
  VERTEX_LOCATION=global            (Gemini 3.x publisher models — us-central1 404s)
  GEAP_RUNTIME_LOCATION=us-central1 (reasoningEngines)
  GEAP_REGISTRY_LOCATION=global     (agents)

## Frontend conformance
context/UI_SPEC.md (491 lines) is the implementable enterprise spec: Blueprint elevation model +
control ladder (20/24/30/40/50), SLDS spacing ramp and type scale, 29 testable conformance
assertions, and a D1-D8 table of deliberate deviations. Our brass/oxblood/verdigris semantics and
Newsreader/Inter Tight/IBM Plex Mono kept; the NEUTRAL ramp was rebuilt to the reference dark-theme
structure. tokens.css carries a commented `@theme blueprint-exact` block for a one-swap A/B.
Verified clean: 0 raw Tailwind palette classes, 0 raw hex outside tokens.css, 0 trademark strings.

## Gotchas discovered
- ADK IS THE FLEET'S RUNTIME and `agents/adk_runtime.py` is the only place it is constructed.
  Every reasoning step is a real `LlmAgent` on a real `Runner`, with the agent's scope-permitted
  tools declared as `FunctionTool`s and the scope gate wired into `before_tool_callback`. Before
  this, `google-adk` was pinned and imported nowhere — the exact defect D-001 F1 records against
  the inherited scaffold. Do not "simplify" this back to a bare generate_content call.
- ANYTHING THAT REACHES A PROMPT MUST BE STABLE ACROSS RUNS or the replay cache can never hit,
  and the miss is reported against the agent DOWNSTREAM of the culprit. Finding ids, case ids and
  demo request ids are all derived, never uuid4; the Challenger and Adjudicator sort findings
  because the concurrent fan-out completes in arbitrary order. `test_prompt_determinism.py`
  guards all four. This is why replay was broken for the entire project before 2026-08-25.
- TOOL_PROTOCOL in agents/base.py is a latency control, not decoration. Declaring tools without
  telling the models the observations were already gathered made them re-fetch what they had just
  been handed: beat 2 went from ~50s to 80s+ and blew the 70s budget. It is appended to the
  prompt AND hashed with it, so the cache key is always the instruction actually sent.
- Live mode uses `OffsetClock` (wall clock + adjustable offset), NOT SystemClock. A bare system
  clock cannot be advanced, so `advance_clock` 409'd and beats 4 and 5 were unrecordable live;
  a FrozenClock would report every span as 0ms. Reset rewinds the offset between takes.
- BEAT 2 LATENCY IS VARIABLE — measured 57.8s, 67.6s and 79.4s live on the same code. The budget
  is 70s. Do a warm-up run before the take and be ready to re-shoot.
- ONE VENDOR PER SCENARIO. `hold_scheduled_payments` only holds SCHEDULED payments, so scenarios
  sharing a vendor starve each other — every beat after the first opened at $0. See D-012.
- S3/S4 exposure MUST stay below AUTO_RELEASE_CEILING or S4 can never RELEASE (rail 4). The
  fixture and the adjudication thresholds are coupled; test_scenario_fixtures.py enforces it.
- Documented expected outcomes are NOT tests. Both D-011 and D-012 were invisible to a green
  suite because no test had ever executed the path.
- VERDICT SEMANTICS. `VERDICT_RUBRIC` in agents/base.py is load-bearing. Without an explicit
  definition, both Flash models returned "supports" for blatant fraud — reading it as "supports my
  analysis". The Adjudicator counts `supports` toward RELEASE, so this would have turned the
  flagship $340K BLOCK into a RELEASE. Never paraphrase the rubric per-agent. See D-011.
- Gemini 3.x Flash are THINKING models: a small maxOutputTokens is consumed by thoughts and
  returns empty text. Do not tighten output budgets.
- A green offline test suite proves nothing about prompt semantics. Test discrimination live:
  assert the agent says the OPPOSITE on inverted evidence.
- The shell's cwd persists across Bash calls; a stale `cd untitled` silently redirected an
  entire batch of file creation into the scaffold. Use absolute paths for structural work.
- `re.findall` with capture groups returns the groups, not the whole match. The injection
  guardrail's "literal removed content" log is wrong because of this — and that log is beat 3.
- `gemini-3.1-pro-preview` is the ONLY Gemini 3.x Pro tier and is still preview. Treat its
  availability as a live risk; keep a config-level fallback to Flash for the two Pro agents.
- GEAP components are NOT all in one location. Agent Registry is `global`; Agent Runtime is
  `us-central1`; other regions return "AgentService not supported in this location". Every
  platform Protocol carries its own location.
- `gcloud` on this machine needs
  `CLOUDSDK_PYTHON=/Library/Frameworks/Python.framework/Versions/3.14/bin/python3`
  or it dies on a pyOpenSSL mismatch in system Python 3.13. The Makefile exports it.
- Use `./.venv/bin/python`, not system python3. System pytest 9.0.2 + pytest-asyncio 0.23.3 are
  an incompatible pair and fail with a confusing `'Package' object has no attribute 'obj'`.
- A step skipped because the case has moved past it is NOT the same as one skipped by checkpoint
  match. The runner reports both as `skipped` deliberately — beat 6 has to *show* that nothing
  re-executed, and a silently-passed-over step shows nothing.
- No Gemini 3.x Pro model satisfies the rules' "3.5 or newer" floor (only 3.1-pro exists).
  Reasoning agents use `gemini-3.7-flash`. Do not "restore" Pro without reading D-007a.
- Replay mode raises ReplayMiss (503) when a prompt has no cached response. That is correct and
  deliberate — it must never degrade to a stub. Populate the cache with DEMO_MODE=record.
- Seeded historical cases (seed/history.py) are CORPUS, not agent output. Never present them on
  camera as live reasoning; inject a scenario for that.
- DataGrid tables need `table-fixed` or a long vendor name expands the column and blows out the
  three-pane layout. Measure with getBoundingClientRect before "fixing" apparent clipping —
  the screenshot canvas is wider than the viewport and fakes an overflow that isn't there.
- This machine's Chrome window will not exceed a 1309px viewport. The demo records at 1080p
  (~1925 CSS px). To check the real recording condition, set `document.body.style.zoom = 0.68`
  and re-measure. At 1309px the Console overlaps and clips; at 1925px it is clean. Judge layout
  at 1925, but the 390px responsive requirement still needs work.
- Code-only subagents cannot see rendering. The UI workflow produced excellent structure and a
  clean tsc/build while leaving visible overlaps at narrow widths. Always follow an agent UI pass
  with a real browser measurement pass.
