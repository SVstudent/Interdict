"""Emit JSON Schema for every wire type, plus the API request/response contract.

Run: python -m app.models.export_schema [outdir]

These files are the contract between the FastAPI backend and the React frontend. They are
generated, never hand-written — `make types` regenerates them and `make check-schema` fails if
the committed copies have drifted, so a model change cannot silently break the UI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .domain import (
    BankingChange,
    BankingDetails,
    Case,
    CaseState,
    ChallengeResult,
    ChangeRequest,
    Checkpoint,
    Decision,
    Effect,
    EvidenceRef,
    Finding,
    Invoice,
    Payment,
    Precedent,
    PrecedentKey,
    Rebuttal,
    Tenant,
    Vendor,
)

WIRE_MODELS: dict[str, type[BaseModel]] = {
    "BankingDetails": BankingDetails,
    "BankingChange": BankingChange,
    "Vendor": Vendor,
    "Invoice": Invoice,
    "Payment": Payment,
    "ChangeRequest": ChangeRequest,
    "EvidenceRef": EvidenceRef,
    "Finding": Finding,
    "Rebuttal": Rebuttal,
    "ChallengeResult": ChallengeResult,
    "Decision": Decision,
    "Checkpoint": Checkpoint,
    "Effect": Effect,
    "Case": Case,
    "Tenant": Tenant,
    "PrecedentKey": PrecedentKey,
    "Precedent": Precedent,
}


def enum_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Interdict enumerations",
        "$defs": {
            "CaseState": {
                "type": "string",
                "enum": [s.value for s in CaseState],
                "description": "opened -> held -> verifying -> {awaiting_callback} -> challenging "
                               "-> adjudicating -> {escalated | released | blocked}",
            },
            "Verdict": {
                "type": "string",
                "enum": ["supports", "contradicts", "inconclusive"],
                "description": "Whether the evidence supports the LEGITIMACY of the change "
                               "request. Not the analyst's confidence in their own analysis.",
            },
            "Outcome": {
                "type": "string",
                "enum": ["BLOCK", "RELEASE", "ESCALATE"],
                "description": "ESCALATE is a success state, not a failure.",
            },
            "PaymentStatus": {
                "type": "string",
                "enum": ["scheduled", "held", "released", "blocked"],
            },
            "CheckpointStatus": {"type": "string", "enum": ["started", "completed", "failed"]},
            "HumanOutcome": {
                "type": "string",
                "enum": ["RELEASE", "BLOCK"],
                "description": "What a human may resolve an escalation TO. Re-escalating is not "
                               "a resolution, so ESCALATE is absent.",
            },
            "ExposureBand": {
                "type": "string",
                "enum": ["below_callback_threshold", "callback_required",
                         "above_release_ceiling"],
                "description": "Which adjudication rail regime an exposure falls under. The "
                               "boundaries are CALLBACK_REQUIRED_THRESHOLD and "
                               "AUTO_RELEASE_CEILING, not round numbers.",
            },
            "TenureBand": {
                "type": "string",
                "enum": ["new", "under_2y", "established"],
                "description": "Vendor relationship age: <90d, <2y, otherwise.",
            },
        },
    }


def invariants() -> dict[str, Any]:
    """The rules that make the wire types safe. Enforced in code; documented here for consumers."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Interdict invariants",
        "description": "Constraints a consumer may rely on. Each is enforced by a validator or a "
                       "runtime assertion in the backend, and covered by a test.",
        "invariants": [
            {
                "id": "INV-1",
                "rule": "A Finding with verdict != 'inconclusive' MUST have non-empty evidence.",
                "enforced_by": "models/domain.py Finding._committed_verdicts_must_cite",
                "test":
                    "tests/test_invariants.py::test_committed_verdict_without_evidence_is_rejected",
                "rationale": "A hallucinated verdict cannot reach adjudication if it cannot cite.",
            },
            {
                "id": "INV-2",
                "rule": "outcome == 'RELEASE' requires >= 2 independent supporting agents, one of "
                        "which is callback with verdict 'supports'.",
                "enforced_by": "agents/adjudicator.py AdjudicatorAgent.apply_rails rule 5",
                "test": "tests/test_invariants.py (adjudication table)",
            },
            {
                "id": "INV-3",
                "rule": "case.exposure_amount == sum(amount of payments in held_payment_ids).",
                "enforced_by": "models/domain.py Case.assert_exposure_matches, called by "
                               "services/payments.py on every mutation",
                "test": "tests/test_invariants.py::test_exposure_matches_sum_of_held_payments",
            },
            {
                "id": "INV-4",
                "rule": "State transitions must appear in LEGAL_TRANSITIONS; anything else raises "
                        "IllegalTransition.",
                "enforced_by": "models/domain.py assert_transition",
                "test": "tests/test_invariants.py::test_every_illegal_transition_raises",
            },
            {
                "id": "INV-5",
                "rule":
                    "A side effect is applied at most once per idempotency_key, across crashes.",
                "enforced_by": "store/base.py Repository.record_effect (compare-and-set); "
                               "services/payments.py short-circuits on created=False",
                "test":
                    "tests/test_durability.py"
                    "::test_exactly_once_block_when_runner_dies_after_the_effect",
            },
            {
                "id": "INV-6",
                "rule": "Full account and routing numbers are NEVER stored or transmitted; only "
                        "4-digit fragments.",
                "enforced_by": "models/domain.py BankingDetails (account_last4/routing_last4 "
                               "pattern ^\\\\d{4}$)",
            },
            {
                "id": "INV-8",
                "rule": "A Precedent MUST carry a non-empty rationale. A resolution with no "
                        "reasoning cannot be cited in an adjudication.",
                "enforced_by": "models/domain.py Precedent._a_precedent_must_explain_itself",
                "test": "tests/test_precedent.py::test_a_precedent_without_a_rationale_is_rejected",
                "rationale": "Same reasoning as INV-1, applied to human decisions: a position "
                             "that cannot show its work must not carry weight.",
            },
            {
                "id": "INV-9",
                "rule": "Money is partitioned by tenant_id. A case, vendor or payment listing "
                        "scoped to a tenant NEVER returns another tenant's rows. Tradecraft in "
                        "the threat exchange is deliberately NOT partitioned.",
                "enforced_by": "store/base.py Repository list_* tenant_id filters; "
                               "platform/exchange.py LocalExchange.lookup",
                "test": "tests/test_tenancy.py::test_a_tenant_never_sees_another_tenants_payments",
            },
            {
                "id": "INV-7",
                "rule": "Every timestamp originates from the injected Clock, never the wall clock.",
                "enforced_by": "config.py Clock protocol",
                "test": "tests/test_no_wallclock.py::test_no_module_reads_the_wall_clock_directly",
            },
        ],
    }


def api_contract() -> dict[str, Any]:
    """Endpoint inventory. The authoritative machine-readable version is /openapi.json from the
    running service; this is the stable, reviewable summary."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Interdict API contract",
        "base_url": "http://localhost:8077",
        "openapi": "/openapi.json",
        "notes": [
            "All money fields are DECIMAL STRINGS, never floats — parse with a decimal type.",
            "All timestamps are ISO-8601 with timezone, sourced from the injected Clock.",
            "POST /api/demo/inject_scenario/* makes real model calls and costs money.",
            "GET /api/events is Server-Sent Events and stays open.",
        ],
        "endpoints": [
            {"method": "GET", "path": "/healthz", "returns": "Health"},
            {"method": "GET", "path": "/api/cases", "returns": "CaseSummary[]",
             "notes": "sorted by exposure_amount descending"},
            {"method": "GET", "path": "/api/cases/{case_id}", "returns": "CaseDetail"},
            {"method": "GET", "path": "/api/cases/{case_id}/trace",
             "returns": "{case_id, spans: Span[]}"},
            {"method": "GET", "path": "/api/cases/{case_id}/checkpoints",
             "returns": "{case_id, checkpoints: Checkpoint[], effects: Effect[]}"},
            {"method": "GET", "path": "/api/cases/{case_id}/memory",
             "returns": "{case_id, session_id, age_days, events[]}"},
            {"method": "GET", "path": "/api/vendors", "returns": "Vendor[]"},
            {"method": "GET", "path": "/api/ledger", "returns": "LedgerTotals"},
            {"method": "GET", "path": "/api/registry",
             "returns": "{entries: RegistryEntry[], backend}"},
            {"method": "GET", "path": "/api/registry/{agent_id}", "returns": "RegistryEntry"},
            {"method": "GET", "path": "/api/posture",
             "returns": "{events: PostureEvent[], gateway_decisions[], scope_manifest[]}"},
            {"method": "GET", "path": "/api/audit",
             "returns": "{records: AuditRecord[], verification}"},
            {"method": "GET", "path": "/api/audit/{case_id}", "returns": "AuditRecord"},
            {"method": "GET", "path": "/api/audit/{case_id}/download",
             "returns": "AuditRecord (attachment)"},
            {"method": "GET", "path": "/api/events", "returns": "text/event-stream"},
            {"method": "GET", "path": "/api/demo/scenarios", "returns": "Scenario[]"},
            {"method": "POST", "path": "/api/demo/reset", "cost": "free"},
            {"method": "POST", "path": "/api/demo/inject_scenario/{id}",
             "cost": "MODEL CALLS — ~$0.01"},
            {"method": "POST", "path": "/api/demo/advance_clock", "cost": "free"},
            {"method": "POST", "path": "/api/demo/kill_runner", "cost": "free"},
            {"method": "POST", "path": "/api/demo/resume_runner", "cost": "may resume model calls"},
            {"method": "POST", "path": "/api/demo/force_scope_violation", "cost": "free"},
            {"method": "GET", "path": "/api/demo/timings", "returns": "{beats, mode, platform}"},
            {"method": "GET", "path": "/api/redteam/runs",
             "returns": "{runs: RedTeamRun[], scoreboard: RedTeamScoreboard}"},
            {"method": "GET", "path": "/api/redteam/runs/{run_id}", "returns": "RedTeamRun"},
            {"method": "POST", "path": "/api/redteam/run",
             "body": "{variants: int = 3 (clamped 1..5), dry_run: bool = true}",
             "cost": "MODEL CALLS — one variant generation plus a full pipeline run per variant; "
                     "dry_run costs the generation only and executes nothing"},
            {"method": "GET", "path": "/api/precedent",
             "returns": "{precedents: Precedent[], count}", "query": "tenant_id (optional)"},
            {"method": "GET", "path": "/api/precedent/{precedent_id}", "returns": "Precedent"},
            {"method": "GET", "path": "/api/cases/{case_id}/precedent",
             "returns": "PrecedentMatchResult"},
            {"method": "POST", "path": "/api/cases/{case_id}/resolve",
             "returns": "PrecedentResolution",
             "cost": "free — records the human's resolution as precedent"},
            {"method": "GET", "path": "/api/tenants",
             "returns": "{tenants: TenantSummary[], exchange_id}"},
            {"method": "GET", "path": "/api/tenants/{tenant_id}", "returns": "TenantDetail"},
            {"method": "GET", "path": "/api/exchange",
             "returns": "ExchangeFeed + withheld: string[]"},
        ],
        "sse_events": [
            "demo_reset", "case_opened", "state_changed", "step_started", "step_completed",
            "step_failed", "lane_started", "lane_failed", "finding_added", "challenge_completed",
            "decision_rendered", "payments_held", "payments_finalized", "clock_advanced",
            "runner_killed", "runner_resumed", "scope_denied",
            "recall_hit", "dossier_written", "fingerprint_recorded", "inbox_triaged",
            "sweep_completed", "callback_recorded", "callback_window_expired",
            "attribution_unavailable", "scribe_unavailable",
            "redteam_run_started", "redteam_variant_generated", "redteam_trial_completed",
            "redteam_run_completed",
            "precedent_recorded", "precedent_cited", "precedent_unavailable",
            "tenant_switched", "exchange_published", "exchange_recognised",
        ],
    }


def main() -> int:
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "schemas")
    outdir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for name, model in WIRE_MODELS.items():
        path = outdir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        written.append(path.name)

    (outdir / "_enums.schema.json").write_text(json.dumps(enum_schema(), indent=2) + "\n")
    (outdir / "_invariants.json").write_text(json.dumps(invariants(), indent=2) + "\n")
    (outdir / "_api_contract.json").write_text(json.dumps(api_contract(), indent=2) + "\n")
    written += ["_enums.schema.json", "_invariants.json", "_api_contract.json"]

    # One bundle for tools that prefer a single document.
    bundle = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Interdict wire types",
        "$defs": {name: model.model_json_schema() for name, model in WIRE_MODELS.items()},
    }
    (outdir / "interdict.bundle.schema.json").write_text(json.dumps(bundle, indent=2) + "\n")
    written.append("interdict.bundle.schema.json")

    print(f"wrote {len(written)} files to {outdir}/")
    for w in sorted(written):
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
