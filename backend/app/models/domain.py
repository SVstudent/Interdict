"""Interdict domain model.

Invariants live here as validators, not as prose in a docstring. A caller that constructs an
invalid object gets an exception at construction time, which is why a bad model generation
cannot release $340,000: the Finding it would need to justify the release will not validate.

See context/DATA_MODEL.md.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Verdict = Literal["supports", "contradicts", "inconclusive"]
Outcome = Literal["BLOCK", "RELEASE", "ESCALATE"]


# --------------------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------------------

class CaseState(str, Enum):
    OPENED = "opened"
    HELD = "held"
    VERIFYING = "verifying"
    AWAITING_CALLBACK = "awaiting_callback"
    CHALLENGING = "challenging"
    ADJUDICATING = "adjudicating"
    ESCALATED = "escalated"
    RELEASED = "released"
    BLOCKED = "blocked"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATES


TERMINAL_STATES: frozenset[CaseState] = frozenset(
    {CaseState.ESCALATED, CaseState.RELEASED, CaseState.BLOCKED}
)

# Explicit adjacency. Anything not listed is illegal and raises.
LEGAL_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.OPENED: frozenset({CaseState.HELD}),
    CaseState.HELD: frozenset({CaseState.VERIFYING}),
    # Verification can suspend on an unanswered callback, or run straight to challenge.
    CaseState.VERIFYING: frozenset({CaseState.AWAITING_CALLBACK, CaseState.CHALLENGING}),
    # A dormant case wakes back into verification (beat 5) or proceeds if the deadline forces it.
    CaseState.AWAITING_CALLBACK: frozenset({CaseState.VERIFYING, CaseState.CHALLENGING}),
    CaseState.CHALLENGING: frozenset({CaseState.ADJUDICATING}),
    CaseState.ADJUDICATING: frozenset(
        {CaseState.RELEASED, CaseState.BLOCKED, CaseState.ESCALATED}
    ),
    CaseState.RELEASED: frozenset(),
    CaseState.BLOCKED: frozenset(),
    CaseState.ESCALATED: frozenset(),
}


class IllegalTransition(Exception):
    """Raised when a case is asked to move somewhere the adjacency map forbids."""

    def __init__(self, case_id: str, current: CaseState, requested: CaseState) -> None:
        allowed = sorted(s.value for s in LEGAL_TRANSITIONS[current])
        super().__init__(
            f"case {case_id}: {current.value} -> {requested.value} is illegal; "
            f"allowed from {current.value}: {allowed or '(terminal)'}"
        )
        self.case_id, self.current, self.requested = case_id, current, requested


def assert_transition(case_id: str, current: CaseState, requested: CaseState) -> None:
    if requested not in LEGAL_TRANSITIONS[current]:
        raise IllegalTransition(case_id, current, requested)


# --------------------------------------------------------------------------------------
# Tenancy
# --------------------------------------------------------------------------------------

# Every vendor, payment and case belongs to a district. The default exists so that everything
# built before tenancy keeps working unchanged: an un-tagged record is the first district's,
# which is what it always was.
DEFAULT_TENANT_ID = "riverbend"

# The red team's sandbox. A real tenant for partitioning purposes and nothing else: it holds no
# district's money, so it is not in `TENANTS`, never appears in the exchange membership, and is
# filtered out of the unscoped docket rather than left to surface as a fifth district.
SIMULATION_TENANT_ID = "simulation"

# The one exchange every tenant publishes into. A tenant scopes money and cases; it does NOT
# scope tradecraft, because the whole point is that district B recognises an operator district A
# has already met.
SHARED_EXCHANGE_ID = "k12-payments-exchange"


class Tenant(BaseModel):
    """One district. Money, vendors and cases are partitioned by tenant_id; the threat exchange
    deliberately is not."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str
    display_name: str
    short_name: str = Field(max_length=12, description="badge text in the UI")
    exchange_id: str = SHARED_EXCHANGE_ID


# --------------------------------------------------------------------------------------
# Vendor / banking
# --------------------------------------------------------------------------------------

class BankingDetails(BaseModel):
    """Only fragments are ever stored. Full account and routing numbers are never persisted,
    even synthetic ones — a screenshot of this system must not teach a bad habit."""

    model_config = ConfigDict(frozen=True)

    account_name: str
    account_last4: str = Field(pattern=r"^\d{4}$")
    routing_last4: str = Field(pattern=r"^\d{4}$")
    bank_name: str
    bank_country: str = Field(min_length=2, max_length=2, description="ISO 3166-1 alpha-2")
    effective_from: datetime


class BankingChange(BaseModel):
    changed_at: datetime
    previous: BankingDetails
    proposed: BankingDetails
    reason: str


class Vendor(BaseModel):
    vendor_id: str
    tenant_id: str = DEFAULT_TENANT_ID
    legal_name: str
    dba_name: str | None = None
    onboarded_at: datetime
    contact_email_of_record: str
    # Sacred. The callback number. Never sourced from an inbound request.
    contact_phone_of_record: str
    banking: BankingDetails
    banking_change_history: list[BankingChange] = Field(default_factory=list)
    total_paid_lifetime: Decimal = Decimal("0")
    invoice_count: int = 0
    operating_country: str = Field(min_length=2, max_length=2)

    def tenure_days(self, now: datetime) -> int:
        return (now - self.onboarded_at).days


# --------------------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------------------

class PaymentStatus(str, Enum):
    SCHEDULED = "scheduled"
    HELD = "held"
    RELEASED = "released"
    BLOCKED = "blocked"


class Payment(BaseModel):
    """Real payment documents exist so that exposure can be a sum rather than a literal, and so
    the exactly-once guarantee has something to actually guard."""

    payment_id: str
    vendor_id: str
    tenant_id: str = DEFAULT_TENANT_ID
    invoice_id: str | None = None
    amount: Decimal
    currency: str = "USD"
    status: PaymentStatus = PaymentStatus.SCHEDULED
    scheduled_for: datetime
    held_by_case_id: str | None = None

    @field_validator("amount")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("payment amount must be positive")
        return v


class Invoice(BaseModel):
    invoice_id: str
    vendor_id: str
    amount: Decimal
    issued_at: datetime
    due_at: datetime
    status: Literal["open", "paid", "void"] = "open"


# --------------------------------------------------------------------------------------
# Inbound artifact
# --------------------------------------------------------------------------------------

class ChangeRequest(BaseModel):
    request_id: str
    # None is itself a strong signal: the request could not be tied to a known vendor.
    vendor_id: str | None = None
    channel: Literal["email", "portal", "invoice_pdf", "phone"]
    received_at: datetime
    raw_artifact: str
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)
    proposed_banking: BankingDetails
    claimed_reason: str | None = None

    @property
    def supplies_own_callback_number(self) -> bool:
        """A request that helpfully includes a phone number alongside a banking change is
        offering to verify itself. That is a fraud signal, never a convenience."""
        return bool(self.artifact_metadata.get("supplied_phone"))


# --------------------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(description="e.g. 'email_headers', 'erp:invoices', 'entity_registry'")
    locator: str = Field(description="where in the source, e.g. 'Reply-To' or 'INV-4471'")
    excerpt: str = Field(min_length=1, description="the literal observed value, not a summary")


class Finding(BaseModel):
    finding_id: str
    agent: str
    agent_version: str
    signal: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    reasoning: str
    latency_ms: int = 0

    @model_validator(mode="after")
    def _committed_verdicts_must_cite(self) -> Finding:
        """A Finding that takes a position must show its work. Structurally enforced, so no
        prompt regression can smuggle an uncited conclusion into an adjudication."""
        if self.verdict != "inconclusive" and not self.evidence:
            raise ValueError(
                f"finding {self.finding_id} ({self.agent}) has verdict "
                f"'{self.verdict}' but cites no evidence"
            )
        return self

    @property
    def is_committed(self) -> bool:
        return self.verdict != "inconclusive"


class Rebuttal(BaseModel):
    """Bound to a specific finding, so BLOCK can ask 'was *this* finding rebutted?' instead of
    consulting one global survived flag."""

    finding_id: str
    argument: str
    succeeds: bool


class ChallengeResult(BaseModel):
    strongest_legitimate_explanation: str
    rebuttals: list[Rebuttal] = Field(default_factory=list)
    survived: bool
    reasoning: str

    def rebutted(self, finding_id: str) -> bool:
        return any(r.finding_id == finding_id and r.succeeds for r in self.rebuttals)


class Decision(BaseModel):
    outcome: Outcome
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    dissenting_findings: list[str] = Field(default_factory=list)
    decided_at: datetime
    decided_by: Literal["fleet", "human"] = "fleet"
    human_reviewer: str | None = None


# --------------------------------------------------------------------------------------
# Precedent
# --------------------------------------------------------------------------------------

# What a human may actually resolve an escalation TO. Re-escalating is not a resolution, so
# ESCALATE is deliberately absent: a precedent records where the organisation drew the line.
HumanOutcome = Literal["RELEASE", "BLOCK"]


def exposure_band(
    amount: Decimal, *, callback_threshold: Decimal, release_ceiling: Decimal
) -> str:
    """Which rail regime this figure falls under.

    The boundaries are the adjudication thresholds themselves, not round numbers. Two cases only
    belong in the same band if the same rails governed them: below the callback threshold nobody
    had to be phoned, above the auto-release ceiling nothing could have been released without a
    human. A $40,000 precedent cannot speak for a $400,000 case even though both are "large".
    The thresholds are passed in rather than imported so that moving a rail moves the bands with
    it instead of silently invalidating every stored precedent.
    """
    if amount < callback_threshold:
        return "below_callback_threshold"
    if amount <= release_ceiling:
        return "callback_required"
    return "above_release_ceiling"


def tenure_band(days: int) -> str:
    """Vendor relationship age, in the three steps that change how a change request reads.

    A supplier of six years and one of five behave identically, which is why this is the weakest
    of the four characteristics — but a banking change from a vendor onboarded last month is a
    different question from one arriving from a decade-long relationship.
    """
    if days < 90:
        return "new"
    if days < 730:
        return "under_2y"
    return "established"


def verdict_pattern(findings: list[Finding]) -> list[str]:
    """What the fleet concluded, canonicalised as sorted `agent:verdict` pairs.

    Agent identity is kept alongside the verdict because *which* lane objected is the substance
    of the decision: a case the callback contradicted is not the same case as one the ledger
    contradicted, even though both are "one contradiction".
    """
    return sorted(f"{f.agent}:{f.verdict}" for f in findings)


class PrecedentKey(BaseModel):
    """The characteristics a precedent keys on — the whole judgement of what makes two cases
    similar enough to cite one on the other.

    Four dimensions, chosen because each one changes what a reasonable human would decide. They
    are deliberately coarse: an exact match on exposure amount or vendor identity would mean a
    precedent is never citable twice, and the point of precedent is that it generalises.
    """

    model_config = ConfigDict(frozen=True)

    exposure_band: str
    verdict_pattern: list[str]
    # Whether a human actually spoke to the vendor on the number of record. Silence is never
    # confirmation, so a precedent set after a confirmed callback cannot govern a case where
    # nobody answered — those are different facts, not a different confidence in the same fact.
    callback_resolved: bool
    vendor_tenure_band: str


class Precedent(BaseModel):
    """A human's resolution of an escalation, kept so the fleet can cite it later.

    Today an ESCALATE dead-ends at a person and the reasoning leaves with them. This is that
    reasoning made durable: the fleet learns the organisation's risk appetite from what the
    organisation actually did, and escalates less as the book fills up.
    """

    precedent_id: str
    case_id: str
    tenant_id: str = DEFAULT_TENANT_ID
    outcome: HumanOutcome
    rationale: str = Field(min_length=1)
    decided_by: str = Field(min_length=1, description="the human, named — not 'operator'")
    decided_at: datetime
    key: PrecedentKey
    # Carried for display and for the audit trail; never used for matching, because a precedent
    # that only applies to one vendor is a note, not a precedent.
    vendor_id: str | None = None
    exposure_amount: Decimal = Decimal("0")
    cited_by_case_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _a_precedent_must_explain_itself(self) -> Precedent:
        """A resolution with no rationale teaches the fleet nothing and cannot be argued with.

        Same reasoning as INV-1: a position that cannot show its work must not be citable in an
        adjudication. Structurally enforced so no UI shortcut can write a blank precedent.
        """
        if not self.rationale.strip():
            raise ValueError(
                f"precedent {self.precedent_id} (case {self.case_id}) records outcome "
                f"'{self.outcome}' but no rationale"
            )
        return self


# --------------------------------------------------------------------------------------
# Durability
# --------------------------------------------------------------------------------------

class CheckpointStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class Checkpoint(BaseModel):
    """Written before a step runs and updated after it completes. On restart the runner replays
    the checkpoint log to decide what it may skip."""

    seq: int
    case_id: str
    step: str
    status: CheckpointStatus = CheckpointStatus.STARTED
    state_before: CaseState
    state_after: CaseState | None = None
    input_hash: str
    output_hash: str | None = None
    attempt: int = 1
    started_at: datetime
    completed_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        return self.status is CheckpointStatus.COMPLETED


class Effect(BaseModel):
    """One row in the exactly-once ledger, keyed by idempotency_key."""

    idempotency_key: str
    case_id: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime


# --------------------------------------------------------------------------------------
# Case
# --------------------------------------------------------------------------------------

class Case(BaseModel):
    case_id: str
    request_id: str
    tenant_id: str = DEFAULT_TENANT_ID
    vendor_id: str | None = None
    state: CaseState = CaseState.OPENED
    exposure_amount: Decimal = Decimal("0")
    held_payment_ids: list[str] = Field(default_factory=list)
    opened_at: datetime
    deadline_at: datetime
    findings: list[Finding] = Field(default_factory=list)
    challenge: ChallengeResult | None = None
    decision: Decision | None = None
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    idempotency_keys: list[str] = Field(default_factory=list)
    session_id: str | None = None

    def finding_by_agent(self, agent: str) -> Finding | None:
        return next((f for f in self.findings if f.agent == agent), None)

    def assert_exposure_matches(self, payments: list[Payment]) -> None:
        """Invariant 3. Called after every mutation that touches held payments."""
        held = [p for p in payments if p.payment_id in self.held_payment_ids]
        total = sum((p.amount for p in held), Decimal("0"))
        if total != self.exposure_amount:
            raise ValueError(
                f"case {self.case_id}: exposure {self.exposure_amount} != "
                f"sum of {len(held)} held payments ({total})"
            )

    def unrebutted_contradictions(self, min_confidence: float) -> list[Finding]:
        return [
            f
            for f in self.findings
            if f.verdict == "contradicts"
            and f.confidence >= min_confidence
            and not (self.challenge and self.challenge.rebutted(f.finding_id))
        ]
