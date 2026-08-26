"""Nacha Phase 2 audit records — hash-chained and tamper-evident.

Nacha's fraud-monitoring rule (effective June 2026) requires non-consumer ACH originators to run
risk-based processes to identify entries initiated under false pretenses AND to document that
process. This record is that documentation, which is why it is a first-class artifact with a
download rather than a log line.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import Clock
from ..models.domain import Case, Decision
from ..store.base import Repository

GENESIS = "sha256:" + "0" * 64
FRAMEWORK = "nacha-2026-fraud-monitoring"
CONTROL_OBJECTIVE = "Identify ACH entries initiated under false pretenses"


def canonical_hash(payload: dict[str, Any]) -> str:
    """Hash excludes `record_hash` itself; everything else is canonicalised."""
    body = {k: v for k, v in payload.items() if k != "record_hash"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


class AuditChain:
    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def _head(self) -> str:
        records = await self._repo.list_audit_records()
        return records[-1]["record_hash"] if records else GENESIS

    async def emit(
        self,
        case: Case,
        decision: Decision,
        *,
        screening: dict[str, Any] | None = None,
        trace_uri: str | None = None,
    ) -> dict[str, Any]:
        records = await self._repo.list_audit_records()
        payload: dict[str, Any] = {
            "record_id": f"AR-{len(records) + 1:05d}",
            "case_id": case.case_id,
            "framework": FRAMEWORK,
            "control_objective": CONTROL_OBJECTIVE,
            "vendor_ref": case.vendor_id or "UNRESOLVED",
            "exposure_amount": str(case.exposure_amount),
            "risk_signals_evaluated": [
                {
                    "agent": f.agent,
                    "agent_version": f.agent_version,
                    "signal": f.signal,
                    "verdict": f.verdict,
                    "confidence": f.confidence,
                }
                for f in case.findings
            ],
            "evidence_chain": [
                {
                    "finding_id": f.finding_id,
                    "source": e.source,
                    "locator": e.locator,
                    "excerpt": e.excerpt,
                }
                for f in case.findings
                for e in f.evidence
            ],
            "adversarial_review": {
                "strongest_legitimate_explanation":
                    case.challenge.strongest_legitimate_explanation if case.challenge else None,
                "rebuttals": [r.model_dump() for r in case.challenge.rebuttals] if case.challenge else [],
                "survived": case.challenge.survived if case.challenge else None,
            },
            "guardrail_screening": screening or {"clean": True, "neutralizations": []},
            "outcome": decision.outcome,
            "decision_rationale": decision.rationale,
            "decided_by": decision.decided_by,
            "human_reviewer": decision.human_reviewer,
            "session_id": case.session_id,
            "reasoning_trace_uri": trace_uri or f"/api/cases/{case.case_id}/trace",
            "emitted_at": self._clock.now().isoformat(),
            "prev_record_hash": await self._head(),
        }
        payload["record_hash"] = canonical_hash(payload)
        await self._repo.append_audit_record(payload)
        return payload

    async def verify(self) -> dict[str, Any]:
        """Walk the chain. Reports the first break rather than a bare False, so the UI can
        point at the record that was altered."""
        prev = GENESIS
        for index, record in enumerate(await self._repo.list_audit_records()):
            if record.get("prev_record_hash") != prev:
                return {
                    "intact": False,
                    "broken_at": index,
                    "record_id": record.get("record_id"),
                    "reason": "prev_record_hash does not match the preceding record",
                }
            expected = canonical_hash(record)
            if record.get("record_hash") != expected:
                return {
                    "intact": False,
                    "broken_at": index,
                    "record_id": record.get("record_id"),
                    "reason": "record contents do not match their hash",
                }
            prev = record["record_hash"]
        return {"intact": True, "length": len(await self._repo.list_audit_records())}

    async def for_case(self, case_id: str) -> dict[str, Any] | None:
        for record in reversed(await self._repo.list_audit_records()):
            if record["case_id"] == case_id:
                return record
        return None
