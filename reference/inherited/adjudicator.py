import uuid
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from .base import BaseADKAgent
from ..models import Case, Finding, ChallengeResult, Decision, CaseState
from ..store.firestore import get_store
from ..audit.nacha import get_audit_store
from ..config import settings

ADJUDICATOR_TOOLS = [
    "render_decision",
    "emit_audit_record",
    "release_payments",
    "block_payments",
    "escalate_to_human"
]

class AdjudicatorAgent(BaseADKAgent):
    def __init__(self):
        super().__init__(
            name="Adjudicator",
            model="gemini-3.1-pro-preview", # Pro-tier model
            system_instruction="Adjudicate payment change requests. Enforce Nacha rules and hard risk guardrails.",
            allowed_tools=ADJUDICATOR_TOOLS,
        )

    def evaluate(
        self, case: Case, findings: List[Finding], challenge: Optional[ChallengeResult], clock_now: datetime
    ) -> Decision:
        self.verify_tool_scope("render_decision")
        self.verify_tool_scope("emit_audit_record")

        store = get_store()
        audit_store = get_audit_store()

        # Hard Rule 1: High-confidence contradictory finding + failed challenge -> BLOCK
        unrebutted_contradictions = [
            f for f in findings
            if f.verdict == "contradicts" and f.confidence >= 0.85
        ]
        if unrebutted_contradictions and (not challenge or not challenge.survived):
            self.verify_tool_scope("block_payments")
            self._execute_payment_action(case, "BLOCK")
            decision = Decision(
                outcome="BLOCK",
                confidence=0.98,
                rationale=f"BLOCKED: Identified {len(unrebutted_contradictions)} high-confidence contradictory signals ({', '.join([c.signal for c in unrebutted_contradictions])}) that failed adversarial challenge.",
                dissenting_findings=[f.signal for f in findings if f.verdict == "supports"],
                decided_at=clock_now,
                decided_by="fleet"
            )
            audit_store.emit_record(case, decision, clock_now)
            return decision

        # Check Callback verdict
        callback_finding = next((f for f in findings if f.agent == "Callback"), None)
        supporting_findings = [f for f in findings if f.verdict == "supports"]

        # Hard Rule 5: Auto-release ceiling check
        if case.exposure_amount > settings.AUTO_RELEASE_CEILING:
            self.verify_tool_scope("escalate_to_human")
            decision = Decision(
                outcome="ESCALATE",
                confidence=0.85,
                rationale=f"ESCALATED: Case exposure amount (${case.exposure_amount}) exceeds auto-release ceiling (${settings.AUTO_RELEASE_CEILING}). Human authorization required.",
                dissenting_findings=[],
                decided_at=clock_now,
                decided_by="fleet"
            )
            audit_store.emit_record(case, decision, clock_now)
            return decision

        # Hard Rule 2: Unresolved callback + exposure > threshold -> ESCALATE
        if not callback_finding or callback_finding.verdict == "inconclusive":
            self.verify_tool_scope("escalate_to_human")
            decision = Decision(
                outcome="ESCALATE",
                confidence=0.80,
                rationale=f"ESCALATED: Out-of-band callback to vendor phone of record is unresolved or pending. Silence is not confirmation for exposure ${case.exposure_amount}.",
                dissenting_findings=[],
                decided_at=clock_now,
                decided_by="fleet"
            )
            audit_store.emit_record(case, decision, clock_now)
            return decision

        # Hard Rule 4: RELEASE requires positive confirmation from >= 2 independent agents, one of which must be Callback
        if (
            len(supporting_findings) >= 2
            and callback_finding
            and callback_finding.verdict == "supports"
            and challenge
            and challenge.survived
        ):
            self.verify_tool_scope("release_payments")
            self._execute_payment_action(case, "RELEASE")
            decision = Decision(
                outcome="RELEASE",
                confidence=0.96,
                rationale=f"RELEASED: Verified by {len(supporting_findings)} independent agents including positive out-of-band callback confirmation. Adversarial review passed.",
                dissenting_findings=[],
                decided_at=clock_now,
                decided_by="fleet"
            )
            audit_store.emit_record(case, decision, clock_now)
            return decision

        # Hard Rule 3: Conflicting findings or low aggregate confidence -> ESCALATE
        self.verify_tool_scope("escalate_to_human")
        decision = Decision(
            outcome="ESCALATE",
            confidence=0.70,
            rationale="ESCALATED: Findings present genuine conflict or lack mandatory double-verification quorum. Abstaining to human reviewer.",
            dissenting_findings=[f.signal for f in findings if f.verdict == "contradicts"],
            decided_at=clock_now,
            decided_by="fleet"
        )
        audit_store.emit_record(case, decision, clock_now)
        return decision

    def _execute_payment_action(self, case: Case, outcome: str) -> None:
        store = get_store()
        for payment_id in case.held_payment_ids:
            key = f"idemp_{case.case_id}_{outcome}_{payment_id}"
            effect_payload = {
                "case_id": case.case_id,
                "payment_id": payment_id,
                "outcome": outcome,
                "timestamp": datetime.now().isoformat()
            }
            is_new = store.record_effect(key, effect_payload)
            if not is_new:
                self.log(case.case_id, "WARN", f"Idempotent guard: effect {key} already executed previously. Skipping duplicate action.")

adjudicator_agent = AdjudicatorAgent()
