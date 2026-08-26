# PLATFORM — GEAP binding

## Status: VERIFIED REAL (2026-08-21)
"Gemini Enterprise Agent Platform" is a live Google Cloud product.
Docs root: `docs.cloud.google.com/gemini-enterprise-agent-platform`
Confirmed present: Agent Registry (`/govern/agent-registry`), Agent Runtime (`reasoningEngines`),
Memory Bank (`/scale/memory-bank`), Sessions with `appendEvent`, REST reference (`/reference/rest`),
and a documented path for registering ADK agents hosted on Agent Runtime.

**Still to confirm in the first 48 hours** (blocking for Phase 3):
- Exact request/response shapes on each method page.
- Regional availability for our project's region.
- Whether Agent Registry / Agent Gateway / semanticGovernancePolicies require allowlisting.
- Whether Memory Bank is provisionable on our project tier.

## Surface

| Component | Surface | Use |
|---|---|---|
| Agent Registry | `projects.locations.agents` — create/get/list/patch (v1beta1) | Publish seven versioned catalog entries |
| Agent Runtime | `projects.locations.reasoningEngines` — `query`, `streamQuery`, `asyncQuery`, `cancelAsyncQuery`, `runtimeRevisions` | Each agent deploys as a reasoning engine; orchestrator uses `asyncQuery` |
| Sessions / Memory | `reasoningEngines.sessions` — create/get/list/`appendEvent`; `sessions.events.list` | One session per case; survives dormancy; `appendEvent` is the durable audit spine |
| Model Armor | `ModelArmorConfig` | Attached to every agent touching inbound artifacts |
| Agent Gateway | `gcloud network-services agent-gateways` | Routing + policy between orchestrator and specialists |
| Governance | `projects.locations.semanticGovernancePolicies` | Declarative: which agents may see banking fields |
| Sandbox | `reasoningEngines.sandboxEnvironments` — create/execute/snapshot/pause/resume | Optional: isolate untrusted PDF parsing |

## Abstraction rule
Every GEAP call goes behind a Protocol in `backend/app/platform/`, each with a **GEAP
implementation and a local implementation**. `make test` must run with no cloud credentials.
If a component proves unavailable close to the deadline, we swap one binding rather than
rewriting the fleet. Test 18 asserts both impls produce identical case outcomes on all five
scenarios — that parity test is the insurance policy.

Protocols: `registry.py`, `runtime.py`, `memory.py`, `armor.py`, `gateway.py`, `telemetry.py`.

**The recorded demo runs against the real GEAP implementations.** Local impls are for CI and
rehearsal only — state this plainly in the README.

If Memory Bank specifically is not provisionable, fall back to `sessions` plus a Firestore memory
collection behind the same interface, and say so plainly in the README.

## Registry entries
Seven agents, real semantic versions. Write metadata as if a procurement manager at a real company
would read it: description, owner, required scopes, I/O schema, data-classification tags, changelog.
```
interdict.sentry           v1.4.0   Detects payee-detail changes; opens holds
interdict.callback         v1.2.1   Out-of-band vendor confirmation
interdict.ledger           v1.3.0   Relationship + invoice baseline        [ERP read]
interdict.provenance       v1.1.0   Inbound artifact forensics
interdict.registry-check   v1.0.2   Entity + account-name attestation
interdict.challenger       v2.0.0   Adversarial review of findings
interdict.adjudicator      v1.5.0   Decision + Nacha audit record          [payment write]
```
Challenger ships at v2.0.0 with a visible changelog entry —
*"v2.0.0: steelman now constructed before rebuttal; reduces false-positive blocks"* —
because versioning is only credible if something actually changed.

## Observability contract
Every agent step emits an OpenTelemetry span. Required attributes:
```
interdict.case_id          interdict.agent          interdict.agent_version
interdict.step             interdict.verdict        interdict.confidence
interdict.evidence_count   interdict.model          interdict.tokens
interdict.identity         interdict.policy_decision
gen_ai.system              gen_ai.request.model
```
Trace tree mirrors the reasoning chain: one root span per case, one child per agent, one
grandchild per tool call. A judge should reconstruct the decision from the tree without reading
code. Test 16 asserts every agent span carries the full attribute set.
