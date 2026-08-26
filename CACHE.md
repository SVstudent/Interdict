# CACHE.md — the replay cache

## Why this exists

Interdict's demo is a four-minute unedited recording. Two things follow from that:

1. **Rehearsal must be free and deterministic.** We will run the beats dozens of times. Paying for
   model calls each time, and getting slightly different reasoning each time, makes rehearsal
   useless as a regression check.
2. **CI must run with no credentials.** `make test` runs on a machine with no GCP access.

The replay cache solves both. It stores real model responses keyed by a hash of the exact request,
and replays them byte-for-byte.

## The three modes

`DEMO_MODE` in `.env` controls it. `backend/app/demo/replay.py`.

| Mode | Model calls | Cache | Use |
|---|---|---|---|
| `live` | real | ignored | the recorded demo takes |
| `record` | real | **written** | populating the cache after a prompt change |
| `replay` | **none** | read-only | rehearsal, CI, frontend development |

**`replay` never invents a response.** A cache miss raises `ReplayMiss`, which the API surfaces as
HTTP 503 with the prompt hash. It does not fall back to a stub. A cache that silently degraded
would let a broken fixture pass rehearsal and then fail on camera — the exact failure mode the
project's operating rules forbid.

## The key

`prompt_hash(agent, model, prompt, context)` — SHA-256 over a canonical JSON encoding of all four,
sorted keys, no whitespace. From `backend/app/demo/replay.py`.

**Every one of those four inputs is part of the key.** So the cache is invalidated by:

- editing an agent's prompt (including `VERDICT_RUBRIC`, which every agent inherits — a rubric
  change invalidates the **entire** cache)
- changing `FLASH_MODEL` or `REASONING_MODEL`
- any change to the observations a tool produces, because those are the context

This is intentional. A stale response for a changed prompt would be worse than a miss.

## Storage

`replay_cache/{prompt_hash}` — a Firestore collection, or a dict in the in-memory repository.

**The cache deliberately survives `POST /api/demo/reset`.** Reset clears case state; the cache is
fixture data, not state. `InMemoryRepository.reset()` clears everything *except* `_replay`.

## Recording

```bash
# 1. Point at a sanctioned provider. Vertex is the default.
#    LLM_PROVIDER=vertex, GCP_PROJECT_ID=interdict-demo-57216, VERTEX_LOCATION=global
# 2. Switch to record mode
sed -i '' 's/^DEMO_MODE=.*/DEMO_MODE=record/' .env
# 3. Restart the backend, then drive every scenario
make record
```

### The compliance gate

`ReplayCache.assert_recordable()` **raises** if `DEMO_MODE=record` under a non-sanctioned provider,
and `main.py` calls it at startup so a misconfigured run dies immediately.

Only `vertex` and `gemini` are sanctioned. `tokenrouter` is not: the competition rules mandate
Gemini 3.5+ through Gemini API or Vertex AI, and the cache feeds the judged recording, so a
response captured through a third-party aggregator would end up in the submitted artifact.
See `context/DECISIONS.md` D-008.

## Cost

Measured against Vertex, `gemini-3.x-flash` at $0.75 in / $3.75 out per 1M tokens
(output includes thinking tokens):

| | Calls | Cost |
|---|---|---|
| One case | 6 | ~$0.01 |
| One full recording pass (5 scenarios) | 30 | **~$0.06** |
| Every rehearsal thereafter | 0 | **$0.00** |

A full re-record after a rubric change costs about six cents. Never hesitate to re-record.

## The determinism requirement

A cache keyed on the request only works if the request repeats. Every input to `prompt_hash` must
therefore be stable across two runs of the same beat — and for most of this project's life, four
of them were not:

| Was | Now | Why it mattered |
|---|---|---|
| `finding_id` was a `uuid4` | derived from agent + signal | The Challenger reasons over the fan-out's findings, so their ids are in its observations |
| `case_id` was a `uuid4` | SHA-256 of the request id | It reaches prompts through the attribution finding's evidence, which quotes the prior case |
| demo `request_id` was a `uuid4` | reset-scoped sequence (`REQ-S1-001`) | It determines the case id |
| findings passed in arrival order | sorted by agent | The four lanes are concurrent; arrival order is whatever the network returned |

The symptom was badly signposted. A miss is reported against the agent that MISSED, which is the
one downstream of whichever agent introduced the randomness — so a `uuid4` in `build_finding`
surfaced as `no cached response for challenger:adversarial_review`. Offline rehearsal could not
complete a single scenario. `tests/test_prompt_determinism.py` now fails on the randomness itself
rather than on its downstream symptom.

`TOOL_PROTOCOL` is appended to every agent's prompt and is hashed with it, so the key is always
the instruction the model actually received.

## Gotchas

- **A `VERDICT_RUBRIC` edit invalidates everything.** Re-record all five scenarios, not one. So
  does an edit to `TOOL_PROTOCOL`, for the same reason: both are inherited by every agent.
- **Re-record the cross-tenant case and the clock wake too**, not just S1-S5. `make record` walks
  the catalogue; the cross-district injection and `advance_clock` are separate calls.
- **Gemini 3.x Flash are thinking models.** They spend output tokens on internal reasoning before
  emitting text. A tight `maxOutputTokens` returns `finishReason: MAX_TOKENS` with empty text and
  caches an empty response. Do not tighten output budgets to save money.
- **`replay` mode still needs the corpus.** The cache holds model responses, not case data. Seed
  runs on startup and on reset.
- **Cache hits make the fan-out near-instantaneous**, so a replay rehearsal will look faster than
  the live take. Time beat 2 in `live` mode against the 70-second budget, never in `replay`.
- **A recorded response is a snapshot of a model version.** If `gemini-3.6-flash` is updated
  server-side, `live` and `replay` can diverge. Re-record before the final takes.
