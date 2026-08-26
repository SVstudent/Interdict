# EXPANSION CONTRACT — F1 Red Team · F2 Precedent · F3 Threat Exchange

Every **shared** file is already edited and committed to the working tree. Three feature agents
implement against this document concurrently and never speak to each other, so the rule is
absolute:

> **Edit only the files your feature OWNS.** If you need a change in a shared file, do NOT make
> it — report it in your return value and integration will apply it.

Read `context/DECISIONS.md` D-001..D-020 first. Several defects there were invisible to a green
suite because the path had never been executed; D-011, D-012, D-018 and D-019a are the pattern.

---

## 0. What is already done (do not redo, do not re-edit)

| File | What landed |
|---|---|
| `backend/app/agents/scopes.py` | `Scope.CASES_SIMULATE`, `PRECEDENT_READ`, `PRECEDENT_WRITE`; `FLEET_SCOPES["redteam"]`, `FLEET_SCOPES["precedent-clerk"]` |
| `backend/app/models/domain.py` | `Tenant`, `DEFAULT_TENANT_ID`, `SHARED_EXCHANGE_ID`, `tenant_id` on `Case`/`Vendor`/`Payment`, `HumanOutcome`, `exposure_band()`, `tenure_band()`, `verdict_pattern()`, `PrecedentKey`, `Precedent` |
| `backend/app/models/export_schema.py` + `schemas/` | regenerated; `Tenant`, `PrecedentKey`, `Precedent` schemas, new enums, INV-8/INV-9, all new endpoints and SSE names |
| `backend/app/store/{base,memory,firestore}.py` | `save_precedent` / `get_precedent` / `list_precedents`; `tenant_id` filter on `list_cases`, `list_vendors`, `list_payments`; `precedents` collection wiped by `reset()` |
| `firestore.indexes.json` | tenant composites for `cases`, `payments` (×2), `vendors`; `precedents(tenant_id, decided_at desc)` |
| `backend/app/platform/precedent.py` | `PrecedentPort`, `LocalPrecedent`, `PrecedentMatch`, `key_from_case`, `score_precedent`, `WEIGHTS`, `CITE_THRESHOLD` |
| `backend/app/platform/exchange.py` | `ExchangePort`, `LocalExchange`, `ExchangeMatch` |
| `backend/app/platform/factory.py` | `Platform.precedent`, `Platform.exchange`; `build_platform(settings, repo)` |
| `backend/app/platform/catalog.py` | registry entries for `redteam` and `precedent-clerk` |
| `backend/app/orchestrator/pipeline.py` | exchange lookup inside `RecallStep`; exchange publish + precedent citation inside `AdjudicateStep`; `build_pipeline(..., precedent=, exchange=)` |
| `backend/app/state.py` | both agents registered; `cite_precedent` closure; ports threaded into the pipeline |
| `backend/app/api/cases.py` | `tenant_id` in every case payload; `?tenant_id=` on `/api/cases` and `/api/vendors` |
| `backend/app/main.py` | `redteam`, `precedent`, `tenants` routers mounted |
| `backend/app/api/{redteam,precedent,tenants}.py` | **stub routers**, mounted and empty — fill these in |
| `backend/app/agents/{redteam,precedent}.py` | **stub agents**, wired and registered — fill the `NotImplementedError` bodies in |
| `web/src/lib/types.ts` | every type for all three features |
| `web/src/lib/api.ts` | every client method for all three features |
| `web/src/lib/useEvents.ts` | every new SSE name registered |

**Shared files — nobody may edit these:** `scopes.py`, `domain.py`, `export_schema.py`,
`schemas/*`, `store/*`, `platform/factory.py`, `platform/precedent.py`, `platform/exchange.py`,
`platform/recall.py`, `platform/catalog.py`, `orchestrator/pipeline.py`, `orchestrator/runner.py`,
`state.py`, `main.py`, `api/cases.py`, `api/deps.py`, `api/demo.py`, `firestore.indexes.json`,
`web/src/lib/{types,api,useEvents}.ts`, `backend/tests/conftest.py`.

---

## 1. Rules that bind all three

- **Money is `Decimal` in Python and a STRING on the wire.** Never a float, never a JS number.
- **Timestamps come from the injected `Clock`.** `datetime.now()` anywhere under `app/` fails
  `test_no_wallclock.py`. Use `ctx.clock.now()` / `state.clock.now()`.
- **A `Finding` with a non-inconclusive verdict and no evidence must fail validation.** Do not
  weaken `Finding._committed_verdicts_must_cite`, and do not route around it.
- **Never call a real model in a test.** Monkeypatch `agent.infer`, exactly as
  `backend/tests/test_hunter.py` and `test_recall.py` do.
- **Scopes are enforced, not asserted.** Every feature ships tests that prove its agent's denials
  hold — a `pytest.raises(ScopeViolation)` on a real `call_tool`, not just a `grant.permits()`
  assertion. `test_hunter.py::test_hunter_cannot_read_banking_details` is the model.
- **Enrichment is never a gate.** If your model call fails, the case must decide exactly as it
  did before your feature existed. Emit `*_unavailable` and carry on.
- **Bars:** `./.venv/bin/python -m pytest backend/tests -q` green (115 at handoff) and
  `cd web && npx tsc --noEmit` exit 0. `vite build` does not typecheck; it proves nothing.
- **Never POST to `/api/demo/inject_scenario/*` or `/api/inbox/process`** while developing.
- **`--oxblood` means money is being stopped:** contradicts verdicts and BLOCK states only. No
  red for a red-team escape, a precedent citation, or an exchange badge.

---

## 2. F1 — RED TEAM

The fleet attacks itself and publishes the score. Reads the threat library, invents a variant of
that tradecraft the fleet has **never** been shown, runs it through the real pipeline against a
simulation tenant, and reports what got through and why.

### Owns

```
backend/app/agents/redteam.py          (fill the stubs)
backend/app/api/redteam.py             (fill the stub router)
backend/app/services/simulation.py     (new — the sandbox harness)
backend/tests/test_redteam.py          (new)
web/src/views/RedTeam*.tsx             (new, if the UI phase asks)
```

### Scopes — already enforced, do not change

```
redteam  granted: threatintel:read, cases:simulate
         denied : threatintel:write, cases:write, payments:release, payments:block,
                  payments:freeze, payments:scan, erp:write, vendor:banking:read
         policy : interdict-policy/redteam-v1
```

The two denials that carry the feature: **`threatintel:write`** (a red team that can edit the
library it tests against measures its own edits) and **`cases:write`** (an invented attack must
never freeze a district's actual payments).

### Signatures — already stubbed in `backend/app/agents/redteam.py`

```python
@dataclass
class AttackVariant:
    variant_id: str; name: str; technique: str; novelty: str
    based_on_designation: str | None; artifact: str
    proposed_account_name: str; proposed_bank: str; reply_to_domain: str
    supplied_phone: str | None = None
    def as_dict(self) -> dict[str, Any]: ...

@dataclass
class RedTeamTrial:
    variant_id: str; variant_name: str; technique: str
    caught: bool; outcome: str | None; simulated_case_id: str
    escaped_reason: str | None = None; top_signal: str | None = None; latency_ms: int = 0
    def as_dict(self) -> dict[str, Any]: ...

@dataclass
class RedTeamRun:
    run_id: str; tenant_id: str; started_at: str; completed_at: str | None = None
    variants: list[AttackVariant]; trials: list[RedTeamTrial]; model: str = ""
    @property caught -> int
    @property hit_rate -> float        # caught / total, ESCALATE counts as caught
    def as_dict(self) -> dict[str, Any]: ...

class RedTeamAgent(InterdictAgent):
    name = "redteam"; version = "1.0.0"; signal = "adversarial_variant"
    model -> settings.reasoning_model()
    async def invent(ctx, library: list[dict], count: int) -> list[AttackVariant]
    async def explain_escape(ctx, variant: AttackVariant, case: dict) -> str
```

You must additionally create the harness:

```python
# backend/app/services/simulation.py
SIMULATION_TENANT_ID = "simulation"

async def run_variant(state: AppState, variant: AttackVariant) -> RedTeamTrial:
    """Seed a throwaway vendor + payments under SIMULATION_TENANT_ID, build a ChangeRequest
    from the variant, open a case with tenant_id=SIMULATION_TENANT_ID and drive the REAL
    pipeline over it."""
```

`state.agents["redteam"]` and `state.agents["precedent-clerk"]` already exist. Reach the library
through `state.platform.recall.library()` — never the repository directly.

### Judgement calls that are yours

- **`caught` counts ESCALATE.** Stopping the money and asking a human is the designed outcome, not
  a miss. Only `RELEASE` is an escape. Say so in the docstring and pin it with a test.
- **A variant that replays a library entry is not a variant.** `AttackVariant.novelty` is the
  agent's own argument for why this is new; reject or re-prompt on an empty one.
- **The simulation tenant is a real tenant.** Its cases must never appear in a district's docket,
  and its blocks must never enter the shared exchange as though a district had been attacked.
  This is the single highest-risk thing in F1 — pin it with a test.

### API — fill `backend/app/api/redteam.py` (`prefix="/api/redteam"`)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/redteam/runs` | `{"runs": RedTeamRun[]}`, newest first |
| GET | `/api/redteam/runs/{run_id}` | `RedTeamRun`; **404** when unknown |
| POST | `/api/redteam/run` | `RedTeamRun` — body `{"variants": int}` default 3, clamp 1..5 |

`POST /api/redteam/run` **costs model calls** (one generation + a full pipeline run per variant).
It is already flagged in `schemas/_api_contract.json`; keep it flagged.

Store runs on `AppState` (add a field via integration, or keep them in
`repo.append_posture_event` with `kind="redteam_run"` — the latter needs no shared-file edit and
is the preferred route).

### TypeScript — already in `types.ts` / `api.ts`

`AttackVariant`, `RedTeamTrial`, `RedTeamRun`;
`api.redteam.runs()`, `api.redteam.run(runId)`, `api.redteam.start(variants?)`.

### SSE events — already registered

`redteam_run_started` `{run_id, tenant_id, variants}` ·
`redteam_variant_generated` `{run_id, variant}` ·
`redteam_trial_completed` `{run_id, trial}` ·
`redteam_run_completed` `{run_id, caught, total, hit_rate, escaped}`

### Tests you must ship (`backend/tests/test_redteam.py`)

1. `test_redteam_may_read_the_threat_library_but_never_write_it` — `pytest.raises(ScopeViolation)`
   on a real `call_tool` for a `threatintel:write` tool.
2. `test_redteam_cannot_open_a_real_case_or_move_money` — denials for `cases:write`,
   `payments:release`, `payments:block`, `payments:freeze`.
3. `test_a_simulated_case_never_appears_in_a_district_docket` — `repo.list_cases("riverbend")`
   excludes it.
4. `test_a_simulated_block_never_enters_the_shared_exchange`.
5. `test_escalate_counts_as_caught_and_release_does_not`.
6. `test_hit_rate_is_zero_when_no_trials_ran` (no ZeroDivisionError).
7. `test_every_escape_carries_a_reason` — a trial with `caught=False` and no `escaped_reason` is
   a bug report nobody can act on.

---

## 3. F2 — PRECEDENT

An `ESCALATE` stops dead-ending at a human. Their resolution becomes a durable record, later cases
match against it and cite it, and the fleet escalates less as the book fills.

### Owns

```
backend/app/agents/precedent.py        (fill the stubs)
backend/app/api/precedent.py           (fill the stub router)
backend/app/agents/adjudicator.py      (exclusive — only F2 touches this)
backend/tests/test_precedent.py        (new)
web/src/views/Precedent*.tsx           (new, if the UI phase asks)
```

### Scopes — already enforced, do not change

```
precedent-clerk  granted: findings:read, precedent:read, precedent:write
                 denied : payments:release, payments:block, payments:freeze,
                          erp:write, vendor:banking:read, threatintel:write
                 policy : interdict-policy/precedent-clerk-v1
```

A precedent is an **argument put to the adjudicator, never an instruction**. The agent that
remembers what the organisation decided must not also be able to act on it.

### The similarity judgement — already decided, in `platform/precedent.py`

Four characteristics, in `PrecedentKey`:

| Characteristic | Weight | Why |
|---|---|---|
| `verdict_pattern` (sorted `agent:verdict`) | **0.40** | what the fleet concluded is the substance of the decision the human overruled; *which* lane objected matters, not just how many |
| `exposure_band` | **0.30** | boundaries are the rails themselves — `CALLBACK_REQUIRED_THRESHOLD` and `AUTO_RELEASE_CEILING` — so a different band is a different rail regime |
| `callback_resolved` | **0.20** | silence is never confirmation; a precedent set after a confirmed callback cannot govern a case where nobody answered |
| `vendor_tenure_band` | **0.10** | weakest: a five-year and a six-year vendor read identically |

`CITE_THRESHOLD = 0.75`, far above recall's 0.45, because a recall match only raises suspicion
while a cited precedent argues for moving money. The arithmetic means a citation requires the
exposure band, the callback state and substantially the same verdict pattern to agree; tenure is
the only characteristic allowed to differ on its own. `verdict_pattern` scores by Jaccard overlap,
not equality — exact equality would make a precedent essentially never citable twice.

**Do not tune these numbers without a test that demonstrates the false positive you are fixing.**

### Signatures — already stubbed in `backend/app/agents/precedent.py`

```python
@dataclass
class PrecedentOpinion:
    governs: bool; confidence: float; reasoning: str
    distinguished_by: str | None = None
    def as_dict(self) -> dict[str, Any]: ...

class PrecedentClerkAgent(InterdictAgent):
    name = "precedent-clerk"; version = "1.0.0"; signal = "precedent_citation"
    model -> settings.reasoning_model()
    async def opine(ctx, candidate: dict, case_summary: dict) -> PrecedentOpinion
    async def summarise_resolution(ctx, case: dict, rationale: str) -> str
```

`candidate` is a `PrecedentMatch.as_dict()`:
`{precedent_id, prior_case_id, outcome, rationale, decided_by, decided_at, score, matched_on, key}`.

### Already wired for you — do not rebuild it

`state.build_runner()` defines `cite_precedent(ctx, case)`, which builds the `PrecedentKey`,
queries `platform.precedent.match(key, case.tenant_id)`, calls your `opine()`, records the
citation, and stashes the result at **`ctx.payload["precedent"]`**. `AdjudicateStep` runs it
*before* `adjudicate()` and emits `precedent_cited`.

**Your adjudicator reads `ctx.payload["precedent"]`.** Shape:
`{...PrecedentMatch.as_dict(), "opinion": {governs, confidence, reasoning, distinguished_by}}`.
`opinion` is absent when the model was unavailable — treat a missing opinion as "match stands, no
argument made", never as "governs".

### Judgement calls that are yours

- **How the adjudicator weighs a citation.** The deterministic rails still run on top. A governing
  precedent may lower an ESCALATE to the outcome the human chose — it may **never** override
  rail 1 (unrebutted contradiction ≥ `CONTRADICTION_BLOCK_CONFIDENCE` → BLOCK) and it may never
  release with an unresolved callback. Encode that in `apply_rails`, in Python, not in a prompt.
- **`summarise_resolution` must never invent reasoning the human did not give.** An empty
  rationale stays empty and `Precedent` rejects it.
- **Resolving a terminal case.** `POST /resolve` on an already-`RELEASED`/`BLOCKED` case is a
  **409**, same as `api/callback.py` does.

### API — fill `backend/app/api/precedent.py` (**no prefix**, full paths)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/precedent` | — | `{"precedents": Precedent[], "count": int}`; query `?tenant_id=` optional |
| GET | `/api/precedent/{precedent_id}` | — | `Precedent`; **404** when unknown |
| GET | `/api/cases/{case_id}/precedent` | — | `PrecedentMatchResult` |
| POST | `/api/cases/{case_id}/resolve` | `{"outcome": "RELEASE"\|"BLOCK", "rationale": str, "decided_by": str}` | `PrecedentResolution` |

```jsonc
// PrecedentMatchResult
{"case_id": "CASE-...", "cited": PrecedentCitation | null, "candidates_considered": 4}

// PrecedentResolution
{"ok": true, "case_id": "CASE-...", "precedent_id": "PR-...", "outcome": "RELEASE",
 "state": "released"}
```

`POST /resolve` must: validate the case is `ESCALATED` (409 otherwise), build the `PrecedentKey`
via `platform.precedent.key_from_case`, persist through `state.platform.precedent.record(...)`,
append a posture event `kind="precedent_recorded"`, emit `precedent_recorded`, and finalise the
payments for the chosen outcome via `state.payments.finalize(case, outcome)`.

`precedent_id` format: `PR-{uuid4().hex[:10].upper()}`, matching `PE-`/`CB-` elsewhere.

### TypeScript — already in `types.ts` / `api.ts`

`HumanOutcome`, `ExposureBand`, `TenureBand`, `PrecedentKey`, `Precedent`, `PrecedentOpinion`,
`PrecedentCitation`, `PrecedentMatchResult`, `PrecedentResolution`;
`api.precedent.all(tenantId?)`, `.one(id)`, `.forCase(caseId)`, `.resolve(caseId, outcome,
rationale, decidedBy)`.

### SSE events — already registered

`precedent_recorded` `{case_id, precedent_id, outcome, decided_by}` ·
`precedent_cited` `{case_id, ...PrecedentCitation}` ·
`precedent_unavailable` `{case_id, error}`

### Tests you must ship (`backend/tests/test_precedent.py`)

1. `test_a_precedent_without_a_rationale_is_rejected` — INV-8, named in
   `schemas/_invariants.json`. Do not weaken the validator to make this pass.
2. `test_the_precedent_clerk_holds_no_money_power` — `ScopeViolation` on `payments:release`,
   `payments:block`, `payments:freeze`, `erp:write`.
3. `test_a_precedent_is_scoped_to_one_tenant` — one district's book never matches another's. Risk
   appetite does not travel even though tradecraft does.
4. `test_a_different_exposure_band_is_not_citable` — $40k cannot speak for $400k.
5. `test_an_unanswered_callback_cannot_cite_a_confirmed_callback_precedent`.
6. `test_three_of_four_lanes_agreeing_still_cites_but_two_of_four_does_not` — pins the Jaccard
   gradient.
7. `test_a_precedent_never_overrides_the_block_rail` — the whole safety argument.
8. `test_a_case_decides_normally_when_the_clerk_is_unavailable` — enrichment, not a gate.
9. `test_resolving_a_terminal_case_is_a_conflict` — 409.
10. `test_the_second_identical_escalation_cites_the_first` — the end-to-end claim, stub agents
    only.

---

## 4. F3 — MULTI-TENANT THREAT EXCHANGE

Two districts as real tenants in one instance, each with its own vendors, payments and cases,
sharing **one** threat exchange. District A blocks an operation; district B — which has never seen
those attackers — recognises them on first contact.

### Owns

```
backend/app/api/tenants.py             (fill the stub router)
backend/app/seed/tenants.py            (new — the tenant registry)
backend/app/seed/generate.py           (exclusive — only F3 touches this)
backend/app/seed/scenarios.py          (exclusive — only F3 touches this)
backend/app/seed/history.py            (exclusive — only F3 touches this)
backend/tests/test_tenants.py          (new)
web/src/views/Tenant*.tsx, Exchange*.tsx   (new, if the UI phase asks)
```

### The asymmetry — already built into the ports, do not undo it

**Money is partitioned. Tradecraft is not.** `repo.list_cases/list_vendors/list_payments` take a
`tenant_id`; `platform.precedent.match` is always tenant-scoped; `platform.exchange.lookup`
returns **only other tenants'** entries. A district's own blocks already reach it through
`recall`, so returning them from the exchange would double-count and let the UI claim a
cross-district recognition that never crossed a boundary.

What crosses the boundary is bounded by `recall.Fingerprint`, which already excludes the victim
vendor and the specific domain. **A district sharing intelligence must not be publishing its
supplier list.** Do not widen what `publish()` carries.

### Already wired for you — do not rebuild it

- `AdjudicateStep` publishes to the exchange on every `BLOCK` and emits `exchange_published`.
- `RecallStep` queries the exchange when the district's **own** memory has nothing, adapts the hit
  into a `RecallMatch`, runs the same Attribution judgement, calls `note_recognition`, and emits
  `exchange_recognised`. The attribution finding cites
  `source="shared_threat_exchange"` and names the contributing district.
- `Platform.exchange` is a `LocalExchange` in both backends.

### `ExchangePort` — the surface you consume

```python
async def publish(tenant_id, case_id, fp: Fingerprint, dossier: dict, published_at: str) -> str
async def lookup(fp: Fingerprint, tenant_id: str) -> list[ExchangeMatch]
async def note_recognition(tenant_id, case_id, match: ExchangeMatch, recognised_at: str) -> None
async def entries() -> list[dict]        # ExchangeEntry rows
async def recognitions() -> list[dict]   # ExchangeRecognition rows
async def members() -> list[str]
```

### Seeding — the substance of F3

`backend/app/seed/tenants.py`:

```python
from ..models.domain import DEFAULT_TENANT_ID, SHARED_EXCHANGE_ID, Tenant

TENANTS: dict[str, Tenant] = {
    DEFAULT_TENANT_ID: Tenant(tenant_id=DEFAULT_TENANT_ID, display_name="...", short_name="..."),
    "<second>":        Tenant(tenant_id="<second>",        display_name="...", short_name="..."),
}
```

`DEFAULT_TENANT_ID` is `"riverbend"` and every existing seeded record already belongs to it —
`Vendor`, `Payment` and `Case` default to it, so nothing pre-existing breaks. Add the second
district's vendors, invoices and payments with an explicit `tenant_id`.

### Judgement calls that are yours

- **The second district must be a different vertical.** D-012's lesson: consecutive beats sharing
  a vendor produced $0 exposure on camera. The cross-district recognition is only convincing if
  district B's targeted vendor is plainly unrelated to district A's, so the ONLY thing linking
  them is the tradecraft.
- **The recognition must be earned.** `MATCH_THRESHOLD` is 0.45 and the weights are recall's,
  unchanged, on purpose: a cross-district hit must be exactly as hard to earn as a within-district
  one, or the exchange becomes a false-positive source a district cannot investigate because the
  prior case is not theirs. Do not lower it to make a demo land.
- **`short_name` is badge text, max 12 chars.** Pick something that reads at 13px.

### API — fill `backend/app/api/tenants.py` (**no prefix**, full paths)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/tenants` | `{"tenants": TenantSummary[], "exchange_id": str}` |
| GET | `/api/tenants/{tenant_id}` | `TenantDetail`; **404** when unknown |
| GET | `/api/exchange` | `ExchangeFeed` |

```jsonc
// TenantSummary — money figures are DECIMAL STRINGS
{"tenant_id": "riverbend", "display_name": "...", "short_name": "...",
 "exchange_id": "k12-payments-exchange",
 "vendor_count": 20, "open_cases": 3,
 "exposure_held": "340000.00", "blocked_total": "340000.00",
 "contributed": 2, "recognised_from_exchange": 1}

// TenantDetail = TenantSummary + {"vendors": Vendor[], "cases": CaseSummary[]}

// ExchangeFeed
{"exchange_id": "k12-payments-exchange",
 "members": TenantSummary[],
 "entries": ExchangeEntry[],
 "recognitions": ExchangeRecognition[]}
```

`ExchangeEntry` and `ExchangeRecognition` are exactly what `LocalExchange.entries()` and
`.recognitions()` already return — pass them through, do not reshape them.

### TypeScript — already in `types.ts` / `api.ts`

`Tenant`, `TenantSummary`, `TenantDetail`, `ExchangeEntry`, `ExchangeRecognition`, `ExchangeFeed`;
`Vendor`/`Payment`/`CaseSummary` carry `tenant_id`;
`api.tenants()`, `api.tenant(id)`, `api.exchange()`, and `api.cases(tenantId?)` /
`api.vendors(tenantId?)`.

### SSE events — already registered

`exchange_published` `{case_id, tenant_id, entry_id, designation}` ·
`exchange_recognised` `{case_id, tenant_id, ...ExchangeMatch}` ·
`tenant_switched` `{tenant_id}` — emit from the UI's tenant selector path

### Tests you must ship (`backend/tests/test_tenants.py`)

1. `test_a_tenant_never_sees_another_tenants_payments` — INV-9, named in
   `schemas/_invariants.json`. Also cases and vendors.
2. `test_existing_records_default_to_the_first_district` — nothing pre-tenancy broke.
3. `test_a_block_in_one_district_is_recognised_in_the_other_on_first_contact` — the headline
   claim. Stub agents; assert the finding cites `source="shared_threat_exchange"` and names the
   contributing tenant.
4. `test_the_exchange_never_carries_the_victim_vendor` — assert no `vendor_id` and no amount
   appears in any `entries()` row.
5. `test_a_district_does_not_recognise_its_own_entry_through_the_exchange` — own memory only,
   or the recognition count is inflated.
6. `test_a_cross_district_recognition_is_exactly_as_hard_to_earn_as_a_local_one` — a genuine
   change scores below `MATCH_THRESHOLD` across districts too.
7. `test_precedent_does_not_cross_the_tenant_boundary` — the asymmetry, stated as a test.

---

## 5. Integration checklist

Before you return, each feature agent runs both bars and reports:

```
cd $REPO_ROOT && ./.venv/bin/python -m pytest backend/tests -q
cd $REPO_ROOT/web && npx tsc --noEmit
```

and lists, verbatim, any change it needed in a shared file and did not make.
