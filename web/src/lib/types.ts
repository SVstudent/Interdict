/* Mirrors backend/app/models/domain.py. Regenerate with `make types`. */

export type Verdict = 'supports' | 'contradicts' | 'inconclusive';
export type Outcome = 'BLOCK' | 'RELEASE' | 'ESCALATE';

export type CaseState =
  | 'opened' | 'held' | 'verifying' | 'awaiting_callback'
  | 'challenging' | 'adjudicating' | 'escalated' | 'released' | 'blocked';

export interface EvidenceRef {
  source: string;
  locator: string;
  excerpt: string;
}

export interface Finding {
  finding_id: string;
  agent: string;
  agent_version: string;
  signal: string;
  verdict: Verdict;
  confidence: number;
  evidence: EvidenceRef[];
  reasoning: string;
  latency_ms: number;
}

export interface Rebuttal {
  finding_id: string;
  argument: string;
  succeeds: boolean;
}

export interface ChallengeResult {
  strongest_legitimate_explanation: string;
  rebuttals: Rebuttal[];
  survived: boolean;
  reasoning: string;
}

export interface Decision {
  outcome: Outcome;
  confidence: number;
  rationale: string;
  dissenting_findings: string[];
  decided_at: string;
  decided_by: 'fleet' | 'human';
  human_reviewer: string | null;
}

export interface BankingDetails {
  account_name: string;
  account_last4: string;
  routing_last4: string;
  bank_name: string;
  bank_country: string;
  effective_from: string;
}

export interface Vendor {
  vendor_id: string;
  tenant_id: string;
  legal_name: string;
  dba_name: string | null;
  onboarded_at: string;
  contact_email_of_record: string;
  contact_phone_of_record: string;
  banking: BankingDetails;
  banking_change_history: unknown[];
  total_paid_lifetime: string;
  invoice_count: number;
  operating_country: string;
}

export interface ChangeRequest {
  request_id: string;
  vendor_id: string | null;
  channel: string;
  received_at: string;
  raw_artifact: string;
  artifact_metadata: Record<string, unknown>;
  proposed_banking: BankingDetails;
  claimed_reason: string | null;
}

export interface Payment {
  payment_id: string;
  vendor_id: string;
  tenant_id: string;
  invoice_id: string | null;
  amount: string;
  currency: string;
  status: 'scheduled' | 'held' | 'released' | 'blocked';
  scheduled_for: string;
  held_by_case_id: string | null;
}

export interface CaseSummary {
  case_id: string;
  tenant_id: string;
  vendor_id: string | null;
  vendor_name: string;
  state: CaseState;
  exposure_amount: string;
  opened_at: string;
  deadline_at: string;
  finding_count: number;
  outcome: Outcome | null;
  session_id: string | null;
  hold_remaining_hours: number;
}

export interface CaseDetail extends Omit<CaseSummary, 'vendor_name' | 'hold_remaining_hours'> {
  vendor: Vendor | null;
  request: ChangeRequest | null;
  held_payments: Payment[];
  findings: Finding[];
  challenge: ChallengeResult | null;
  decision: Decision | null;
}

export interface Span {
  span_id: string;
  parent_id: string | null;
  name: string;
  kind: 'case' | 'agent' | 'tool';
  attributes: Record<string, unknown>;
  duration_ms: number;
}

export interface Checkpoint {
  seq: number;
  case_id: string;
  step: string;
  status: 'started' | 'completed' | 'failed';
  state_before: CaseState;
  state_after: CaseState | null;
  input_hash: string;
  output_hash: string | null;
  attempt: number;
  started_at: string;
  completed_at: string | null;
}

export interface Effect {
  idempotency_key: string;
  case_id: string;
  action: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  recorded_at: string;
}

export interface RegistryEntry {
  agent_id: string;
  display_name: string;
  version: string;
  description: string;
  owner: string;
  department: string;
  data_classification: string;
  granted_scopes: string[];
  denied_scopes: string[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  changelog: { version: string; note: string }[];
  used_by: string[];
  reasoning_engine_id: string | null;
  runtime_revision: string | null;
  fleet: string;
}

export interface Neutralization {
  technique: string;
  excerpt: string;
  location: string;
  offset: number;
  detail: string;
}

export interface PostureEvent {
  event_id: string;
  kind: string;
  occurred_at: string;
  [key: string]: unknown;
}

export interface GatewayDecision {
  request_id: string;
  source: string;
  target: string;
  allowed: boolean;
  policy_id: string;
  reason: string;
}

export interface ScopeManifestRow {
  agent: string;
  granted: string[];
  denied: string[];
  policy_id: string;
}

export interface AuditRecord {
  record_id: string;
  case_id: string;
  framework: string;
  control_objective: string;
  vendor_ref: string;
  exposure_amount: string;
  risk_signals_evaluated: unknown[];
  evidence_chain: unknown[];
  adversarial_review: Record<string, unknown>;
  guardrail_screening: Record<string, unknown>;
  outcome: Outcome;
  decision_rationale: string;
  decided_by: string;
  session_id: string | null;
  reasoning_trace_uri: string;
  emitted_at: string;
  record_hash: string;
  prev_record_hash: string;
}

/** A dossier Scribe wrote after an interdiction. The fleet's institutional memory. */
export interface ThreatDossier {
  designation: string;
  assessment: string;
  tradecraft: string[];
  indicators: string[];
  likely_next_target: string;
  confidence: number;
  first_seen_case_id: string;
  authored_by?: string;
  model?: string;
}

export interface KnownOperation {
  case_id: string;
  vendor_id: string | null;
  designation: string;
  dossier: ThreatDossier;
  fingerprint: Record<string, unknown>;
}

export interface ThreatLibrary {
  known_operations: number;
  operations: KnownOperation[];
}

export interface ImpactSummary {
  prevented_loss: string;
  pending_human_decision: string;
  released_after_verification: string;
  interdictions: number;
  equivalent_average_incidents: number;
  benchmark: { source: string; average_bec_loss_per_complaint: string };
  known_attacker_operations: number;
  as_of: string;
}

export interface CallbackInstructions {
  case_id: string;
  awaiting: boolean;
  vendor_name: string | null;
  dial: string | null;
  dial_source: string;
  request_supplied_number: string | null;
  do_not_dial_reason: string | null;
  script: string | null;
}

export interface InboxMessage {
  message_id: string;
  received_at: string;
  sender_name: string;
  sender_email: string;
  subject: string;
  body: string;
  has_attachment: boolean;
  attachment_name: string | null;
  scenario_id: string | null;
}

export interface TriageVerdict {
  message_id: string;
  action: 'investigate' | 'ignore';
  confidence: number;
  reason: string;
  used_model: boolean;
}

export interface InboxRun {
  ok: boolean;
  messages_read: number;
  triage: {
    investigate: number;
    ignored: number;
    settled_without_a_model_call: number;
    model_calls: number;
  };
  cases_opened: {
    message_id: string;
    subject: string;
    case_id: string | null;
    state?: string;
    outcome?: string | null;
    note?: string;
  }[];
  verdicts: TriageVerdict[];
}

export interface LedgerTotals {
  totals: Record<'held' | 'released' | 'blocked' | 'escalated', string>;
  counts: Record<'held' | 'released' | 'blocked' | 'escalated', number>;
  as_of: string;
}

export interface Scenario {
  scenario_id: string;
  slug: string;
  headline: string;
  beat: string;
  expected_outcome: Outcome;
}

export interface Health {
  ok: boolean;
  mode: 'live' | 'replay' | 'record';
  platform: 'local' | 'geap';
  clock: string;
  synthetic_data: boolean;
}

/* ------------------------------------------------------------------------------------
 * Red Team (F1) — the fleet attacks itself and publishes the score.
 * ---------------------------------------------------------------------------------- */

export interface AttackVariant {
  variant_id: string;
  name: string;
  technique: string;
  /** Why the fleet has never seen this. A variant that replays a library entry proves nothing. */
  novelty: string;
  based_on_designation: string | null;
  artifact: string;
  proposed_account_name: string;
  proposed_bank: string;
  reply_to_domain: string;
  supplied_phone: string | null;
}

export interface RedTeamTrial {
  variant_id: string;
  variant_name: string;
  technique: string;
  /** ESCALATE counts as caught: stopping money and asking a human is the designed outcome. */
  caught: boolean;
  outcome: Outcome | null;
  simulated_case_id: string;
  escaped_reason: string | null;
  top_signal: string | null;
  latency_ms: number;
}

export interface RedTeamRun {
  run_id: string;
  tenant_id: string;
  started_at: string;
  completed_at: string | null;
  variants: AttackVariant[];
  trials: RedTeamTrial[];
  caught: number;
  total: number;
  /** caught / total, 0..1. */
  hit_rate: number;
  escaped: RedTeamTrial[];
  model: string;
}

/** Accumulated across every run, because one run of three variants is an anecdote. */
export interface RedTeamScoreboard {
  runs: number;
  variants_generated: number;
  trials: number;
  caught: number;
  hit_rate: number;
  escaped: RedTeamTrial[];
}

/* ------------------------------------------------------------------------------------
 * Precedent (F2) — an escalation stops dead-ending at a human.
 * ---------------------------------------------------------------------------------- */

/** What a human may resolve an escalation TO. Re-escalating is not a resolution. */
export type HumanOutcome = 'RELEASE' | 'BLOCK';

export type ExposureBand =
  | 'below_callback_threshold' | 'callback_required' | 'above_release_ceiling';

export type TenureBand = 'new' | 'under_2y' | 'established';

/** The four characteristics that decide whether one case may cite another. */
export interface PrecedentKey {
  exposure_band: ExposureBand;
  /** Sorted `agent:verdict` pairs — what the fleet concluded, not how sure it was. */
  verdict_pattern: string[];
  callback_resolved: boolean;
  vendor_tenure_band: TenureBand;
}

export interface Precedent {
  precedent_id: string;
  case_id: string;
  tenant_id: string;
  outcome: HumanOutcome;
  rationale: string;
  decided_by: string;
  decided_at: string;
  key: PrecedentKey;
  vendor_id: string | null;
  exposure_amount: string;
  cited_by_case_ids: string[];
}

/** The precedent-clerk's judgement on whether a matched precedent actually governs. */
export interface PrecedentOpinion {
  governs: boolean;
  confidence: number;
  reasoning: string;
  distinguished_by: string | null;
}

export interface PrecedentCitation {
  precedent_id: string;
  prior_case_id: string;
  outcome: HumanOutcome;
  rationale: string;
  decided_by: string;
  decided_at: string;
  /** 0..1 weighted match. Citation requires >= 0.75. */
  score: number;
  matched_on: string[];
  key: PrecedentKey;
  opinion?: PrecedentOpinion;
}

export interface PrecedentMatchResult {
  case_id: string;
  cited: PrecedentCitation | null;
  candidates_considered: number;
}

export interface PrecedentResolution {
  ok: boolean;
  case_id: string;
  precedent_id: string;
  outcome: HumanOutcome;
  state: CaseState;
}

/* ------------------------------------------------------------------------------------
 * Tenants and the shared threat exchange (F3).
 * ---------------------------------------------------------------------------------- */

export interface Tenant {
  tenant_id: string;
  display_name: string;
  short_name: string;
  exchange_id: string;
}

export interface TenantSummary extends Tenant {
  vendor_count: number;
  open_cases: number;
  exposure_held: string;
  blocked_total: string;
  /** Entries this district published to the exchange. */
  contributed: number;
  /** Cases this district recognised using another district's entry. */
  recognised_from_exchange: number;
}

export interface TenantDetail extends TenantSummary {
  vendors: Vendor[];
  cases: CaseSummary[];
}

/** One published operation. Carries tradecraft only — never the victim or the amount. */
export interface ExchangeEntry {
  entry_id: string;
  contributed_by_tenant_id: string;
  first_seen_case_id: string;
  designation: string;
  fingerprint: Record<string, unknown>;
  dossier: ThreatDossier;
  published_at: string;
  recognised_by_tenant_ids: string[];
}

export interface ExchangeRecognition {
  case_id: string;
  tenant_id: string;
  contributed_by_tenant_id: string;
  entry_id: string;
  prior_case_id: string;
  designation: string;
  score: number;
  matched_on: string[];
  recognised_at: string;
}

export interface ExchangeFeed {
  exchange_id: string;
  members: TenantSummary[];
  entries: ExchangeEntry[];
  recognitions: ExchangeRecognition[];
  /**
   * Field names checked against every published entry and found genuinely absent. Computed, not
   * asserted: if `publish()` ever starts carrying one, it drops out of this list rather than the
   * UI going on claiming it was withheld.
   */
  withheld: string[];
}
