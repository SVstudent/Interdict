# AGENT FLEET

Twelve ADK agents (`google-adk` 2.7.1). Each has an explicit tool registry that **raises** on an
out-of-scope call. Scope is enforced, never asserted.

The first seven decide a case. The rest run either side of it: three turn a terminated case into
durable intelligence, one argues from the district's own past decisions, and one attacks the
fleet on purpose.

| Agent | Version | Model | Scope |
|---|---|---|---|
| `Sentry` | v1.4.0 | Flash | Detect payee-change intent, resolve vendor, freeze payments, open case. **Makes no legitimacy judgment.** |
| `Callback` | v1.2.1 | Flash | Contact vendor on `contact_phone_of_record` only. Records "request supplied its own number" as a signal, then ignores that number. Returns immediately; case goes dormant. |
| `Ledger` | v1.3.0 | Flash | Relationship baseline: tenure, invoice history, prior change frequency, whether an open invoice actually correlates. Read-only. |
| `Provenance` | v1.1.0 | Flash | Artifact forensics: reply-to divergence, domain age, homoglyph detection, PDF producer metadata vs historical invoices, thread-hijack indicators. |
| `RegistryCheck` | v1.0.2 | Flash | Entity attestation: account holder name vs legal entity, bank jurisdiction vs operating country. |
| `Challenger` | v2.0.0 | **Pro** | Argues *for* legitimacy as forcefully as evidence permits — acquisitions, bank mergers, factoring, treasury consolidation all cause real changes. Then rebuts each supporting finding. **Must sometimes win.** |
| `Adjudicator` | v1.5.0 | **Pro** | Weighs findings against the challenge. Emits decision + audit record. |
| `Scribe` | v1.0.0 | Flash | After a BLOCK, writes the operation's dossier — designation, assessment, tradecraft, likely next target. Off the critical path, so it runs on Flash and its latency costs the operator nothing. |
| `Attribution` | v1.0.0 | **Pro** | Reads a dossier and argues whether a new request is the same operator or a coincidence. Sceptical by construction: many vendors share a regional bank. |
| `Hunter` | v1.0.0 | **Pro** | After an interdiction, searches the district's own payment book for the operation's other likely targets and freezes them. Can interrupt; cannot conclude. |
| `PrecedentClerk` | v1.0.0 | **Pro** | Reads the district's book of human resolutions and argues whether an earlier one governs this case. Holds no money power — a precedent is an argument, never an instruction. |
| `RedTeam` | v1.0.0 | **Pro** | Invents tradecraft the fleet has never been shown and runs it through the real pipeline against a sandbox tenant. Publishes what got through. |

Models: Flash = `gemini-3.6-flash`; Pro = `gemini-3.1-pro-preview` (see DECISIONS D-000b for the
preview-availability risk and the required config-level fallback).

## Identity scopes — enforce, don't assert

| Agent | Granted | Denied |
|---|---|---|
| `sentry` | `payments:freeze`, `cases:write` | banking field read |
| `callback` | `vendor:contact_of_record:read` | `vendor:banking:read` |
| `ledger` | `erp:invoices:read`, `erp:vendor:read` | any write |
| `provenance` | `artifact:read` | ERP entirely |
| `registry-check` | `entity:lookup`, `vendor:banking:read` | any write |
| `challenger` | findings read-only | all tools |
| `adjudicator` | `payments:release`, `payments:block`, `audit:write` | ERP write |
| `scribe` | `findings:read`, `threatintel:write` | all money powers |
| `attribution` | `findings:read`, `threatintel:read` | `threatintel:write`, all money powers |
| `hunter` | `payments:scan`, `payments:freeze`, `threatintel:read` | `payments:release`, `payments:block`, `erp:write` |
| `precedent-clerk` | `findings:read`, `precedent:read`, `precedent:write` | all money powers, `threatintel:write` |
| `redteam` | `threatintel:read`, `cases:simulate` | `threatintel:write`, `cases:write`, all money powers |

`cases:simulate` exists as a scope of its own so that "run the real pipeline" and "open a case
against real money" are not the same permission. It is what lets the red team be genuine.

`POST /api/demo/force_scope_violation` makes `callback` attempt `vendor:banking:read`, which must
raise **and** emit a posture event carrying the policy that produced the denial.
An enforcement you can't show is one a judge assumes you didn't build.

## Adjudication rules — hard code, not prompt guidance
A bad generation must not be able to release $340,000. These run in Python, after the model.
```
if any finding.verdict == "contradicts" and confidence >= 0.85
   and not challenger.rebutted(finding):                          -> BLOCK
if callback unresolved and exposure > CALLBACK_REQUIRED_THRESHOLD: -> ESCALATE
if aggregate_support < 0.6 or findings in conflict:                -> ESCALATE
if exposure > AUTO_RELEASE_CEILING (default $250,000):             -> ESCALATE
RELEASE requires >= 2 independent supporting agents incl. Callback
```

**Rail 6 — precedent.** After rails 1-5 have settled an outcome, a cited precedent may argue.
It runs last and it can only ever move the outcome toward caution:
`max(railed_outcome, argued_outcome)` over `RELEASE < ESCALATE < BLOCK`.

```
governing BLOCK precedent  + ESCALATE -> BLOCK      the district already stopped this
governing BLOCK precedent  + RELEASE  -> ESCALATE   the lanes found live evidence; a person looks
governing RELEASE precedent + anything -> unchanged, cited into the rationale by name
```

A payment held in error is paid a week late; a payment released in error is gone. Because
precedent runs *after* `apply_rails` and never inside it, rails 1 and 2 are structurally
unreachable from it — a precedent cannot release on an unrebutted contradiction or an unanswered
callback. A missing clerk opinion means "match stands, no argument made", never "governs".

`challenger.rebutted(finding)` is **per-finding** (DATA_MODEL invariant 5). The inherited
implementation consults a single global `survived` flag — do not carry that over.

**Silence is never confirmation.** An unanswered callback cannot produce a RELEASE.

## Guardrails
`guardrails/injection.py` screens every inbound artifact before it reaches any agent:
hidden PDF instruction text, zero-width characters, white-on-white text, instruction-shaped
metadata strings. **The removal is logged with the literal removed content** — that log is beat 3,
so make it presentable.

> Known bug in the inherited version: `re.findall` on a pattern containing a capture group returns
> the group, not the full match, so `removed` holds `"previous"` instead of the whole injected
> sentence. Use `finditer` + `match.group(0)`. Test 6 must assert on the full literal string.

## Audit record
Hash-chained, immutable, one per terminal decision.
```json
{
  "record_id": "...", "case_id": "...",
  "framework": "nacha-2026-fraud-monitoring",
  "control_objective": "Identify ACH entries initiated under false pretenses",
  "vendor_ref": "...", "exposure_amount": "340000.00",
  "risk_signals_evaluated": [], "evidence_chain": [],
  "adversarial_review": {}, "outcome": "BLOCK", "decided_by": "fleet",
  "reasoning_trace_uri": "...", "emitted_at": "...",
  "record_hash": "sha256:...", "prev_record_hash": "sha256:..."
}
```
`GET /api/audit/{case_id}`, downloadable as JSON.
