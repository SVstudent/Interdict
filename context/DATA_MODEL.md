# DATA MODEL

Pydantic v2 in `backend/app/models/`. TypeScript generated from JSON schema into
`web/src/lib/types.ts` via `make types` — generation is a make target, never a manual copy.

**Freeze this before agents exist.** Phase 1 builds it; Phase 2 consumes it.

## Entities

**`Vendor`** — `vendor_id`, `legal_name`, `dba_name`, `onboarded_at`, `contact_email_of_record`,
`contact_phone_of_record` *(sacred: the callback number)*, `banking`, `banking_change_history`,
`total_paid_lifetime`, `invoice_count`, `operating_country`.

**`BankingDetails`** — `account_name`, `account_last4`, `routing_last4`, `bank_name`,
`bank_country`, `effective_from`. **Never store full account or routing numbers, even synthetic.**

**`ChangeRequest`** — `request_id`, `vendor_id | None` *(None is itself a strong signal)*,
`channel`, `received_at`, `raw_artifact`, `artifact_metadata`, `proposed_banking`, `claimed_reason`.

**`Case`** — `case_id`, `request_id`, `vendor_id`, `state`, `exposure_amount: Decimal`,
`held_payment_ids`, `opened_at`, `deadline_at`, `findings`, `challenge`, `decision`,
`checkpoints`, `idempotency_keys`, `session_id`.

**`CaseState`** — `OPENED → HELD → VERIFYING → {AWAITING_CALLBACK} → CHALLENGING → ADJUDICATING
→ {ESCALATED | RELEASED | BLOCKED}`.

**`Finding`** — `finding_id`, `agent`, `agent_version`, `signal`,
`verdict: supports|contradicts|inconclusive`, `confidence: float`, `evidence: list[EvidenceRef]`,
`reasoning`, `latency_ms`.

**`EvidenceRef`** — `source`, `locator`, `excerpt` *(the literal observed value, not a summary)*.

**`ChallengeResult`** — `strongest_legitimate_explanation`, `rebuttals`, `survived: bool`,
`reasoning`. Rebuttals must be addressable per-finding (see invariant 5).

**`Decision`** — `outcome: BLOCK|RELEASE|ESCALATE`, `confidence`, `rationale`,
`dissenting_findings`, `decided_at`, `decided_by`, `human_reviewer`.

## Invariants — validators, not prose
1. A `Finding` with `verdict != "inconclusive"` and empty `evidence` raises.
   *(Inherited implementation is correct — `domain.py` `validate_evidence`.)*
2. `outcome == "RELEASE"` requires >=2 independent supporting agents, one being Callback.
3. `exposure_amount` equals the sum of held payments; assert on **every** mutation.
   *(Inherited code violates this — hardcodes 340000 and invents payment IDs. D-001 F11.)*
4. State transitions validated against an explicit adjacency map; illegal transitions raise.
5. Challenger rebuttals bind to a `finding_id`, so BLOCK can ask "was *this* finding rebutted?"
   rather than consulting a single global `survived` flag. *(Inherited code uses the global flag.)*

## Firestore
```
vendors/{vendor_id}
invoices/{invoice_id}                  idx: vendor_id, status
payments/{payment_id}                  idx: vendor_id, status, scheduled_for
change_requests/{request_id}
cases/{case_id}                        idx: state, opened_at, deadline_at
  cases/{case_id}/findings/{finding_id}
  cases/{case_id}/checkpoints/{seq}
effects/{idempotency_key}              <- the exactly-once ledger
audit_records/{record_id}              idx: case_id, emitted_at (hash-chained)
posture_events/{event_id}              idx: kind, occurred_at
replay_cache/{prompt_hash}
```

`payments/` is **not optional** — invariant 3 and the exactly-once guarantee both depend on real
payment documents to hold and release. The inherited code has no payments collection, which is why
its idempotency guard protects a no-op (D-001 F8).

Emulator locally via docker-compose. `firestore.indexes.json` and `firestore.rules` ship in
Phase 1, not as an afterthought.

**Repository pattern.** All Firestore access goes through `store/`. No agent, route, or
orchestrator step touches the client directly.
