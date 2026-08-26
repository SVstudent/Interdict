/** Money, identifiers and durations, formatted once so they read identically everywhere. */

import type { Outcome } from '@/lib/types';

const USD = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const USD_CENTS = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const money = (value: string | number, cents = false): string => {
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return '—';
  return cents ? USD_CENTS.format(n) : USD.format(n);
};

export const pct = (value: number): string => `${Math.round(value * 100)}%`;

export const ms = (value: number): string =>
  value >= 1000 ? `${(value / 1000).toFixed(2)}s` : `${value}ms`;

/** Operator-facing state names. Never show a raw enum on screen. */
const STATE_LABELS: Record<string, string> = {
  opened: 'Opened',
  held: 'Payments held',
  verifying: 'Verifying',
  awaiting_callback: 'Waiting on vendor callback',
  challenging: 'Adversarial review',
  adjudicating: 'Adjudicating',
  escalated: 'Escalated to a human',
  released: 'Hold released',
  blocked: 'Payment blocked',
};

export const stateLabel = (state: string): string => STATE_LABELS[state] ?? state;

/**
 * Compact state names for the case queue, which both Console and Docket
 * render at the same width. Sized so the widest value ('Adjudicating', 12
 * glyphs) fits a 132px pill column; the full operator phrase is always on the
 * record header's StateChip and in every cell's `title`, so nothing is lost.
 */
const STATE_LABELS_SHORT: Record<string, string> = {
  opened: 'Opened',
  held: 'Held',
  verifying: 'Verifying',
  awaiting_callback: 'Awaiting',
  challenging: 'Challenging',
  adjudicating: 'Adjudicating',
  escalated: 'Escalated',
  released: 'Released',
  blocked: 'Blocked',
};

export const stateLabelShort = (state: string): string =>
  STATE_LABELS_SHORT[state] ?? state;

/**
 * Outcome, in the same vocabulary as `stateLabel` — one fact reads the same
 * on every surface. `outcomeWord` is the display-type form for the Balance
 * verdict band, where the figure is set at 52px and the subject ("payment",
 * "hold") is already the subject of the whole surface.
 */
const OUTCOME_LABELS: Record<Outcome, string> = {
  BLOCK: 'Payment blocked',
  RELEASE: 'Hold released',
  ESCALATE: 'Escalated to a human',
};

const OUTCOME_WORDS: Record<Outcome, string> = {
  BLOCK: 'Blocked',
  RELEASE: 'Released',
  ESCALATE: 'Escalated',
};

export const outcomeLabel = (outcome: Outcome): string => OUTCOME_LABELS[outcome];
export const outcomeWord = (outcome: Outcome): string => OUTCOME_WORDS[outcome];

/** The same fact as a verb phrase, for "Expected to …" sentences. */
const OUTCOME_VERBS: Record<Outcome, string> = {
  BLOCK: 'block the payment',
  RELEASE: 'release the hold',
  ESCALATE: 'escalate to a human',
};

export const outcomeVerb = (outcome: Outcome): string => OUTCOME_VERBS[outcome];

/**
 * De-underscore a value the backend adds after this file was written. It
 * makes a raw enum readable; it never guesses meaning. Every enum that is
 * known gets a real label above.
 */
export const humanize = (raw: string): string => {
  const words = raw.replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : raw;
};

const AGENT_LABELS: Record<string, string> = {
  orchestrator: 'Orchestrator',
  sentry: 'Sentry',
  callback: 'Callback',
  ledger: 'Ledger',
  provenance: 'Provenance',
  'registry-check': 'Registry Check',
  challenger: 'Challenger',
  adjudicator: 'Adjudicator',
};

export const agentLabel = (agent: string): string => AGENT_LABELS[agent] ?? agent;

/**
 * One naming convention for agents on every surface. Anything AGENT_LABELS
 * does not know is title-cased rather than rendered as a raw slug beside a
 * properly-named peer.
 */
export const agentName = (raw: unknown): string => {
  const value = raw === null || raw === undefined ? '' : String(raw);
  if (value.length === 0) return '—';
  const label = agentLabel(value);
  if (label !== value) return label;
  return value
    .split(/[-_]/)
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
};

/** Operator-facing names for the backend's `signal` enum. */
const SIGNAL_LABELS: Record<string, string> = {
  payee_change_detected: 'Payee change detected',
  artifact_forensics: 'Artifact forensics',
  relationship_baseline: 'Relationship baseline',
  entity_attestation: 'Entity attestation',
  out_of_band_confirmation: 'Out-of-band confirmation',
  adversarial_review: 'Adversarial review',
  adjudication: 'Adjudication',
  unspecified: 'Unspecified',
};

export const signalLabel = (signal: string): string =>
  SIGNAL_LABELS[signal] ?? humanize(signal);

/** Prompt-injection techniques. Keys mirror `guardrails/injection.py`
    `Technique`; "homoglyph" means nothing to an accounts-payable operator. */
const TECHNIQUE_LABELS: Record<string, string> = {
  instruction_override: 'Instruction override',
  authority_spoof: 'Impersonated authority',
  urgency_coercion: 'Urgency pressure',
  hidden_text: 'Hidden text',
  zero_width: 'Invisible characters',
  homoglyph: 'Look-alike characters',
  metadata_instruction: 'Instruction hidden in metadata',
};

export const techniqueLabel = (technique: string): string =>
  TECHNIQUE_LABELS[technique] ?? humanize(technique);

/** Where in the artifact it was found. The screener emits `metadata:<key>`
    for any metadata field, so the prefix is handled generically. */
const LOCATION_LABELS: Record<string, string> = {
  body: 'Document body',
  'metadata:producer': 'PDF metadata — Producer',
  'metadata:title': 'PDF metadata — Title',
  'metadata:subject': 'PDF metadata — Subject',
  'metadata:author': 'PDF metadata — Author',
  'metadata:keywords': 'PDF metadata — Keywords',
};

export const locationLabel = (raw: unknown): string => {
  const value = raw === null || raw === undefined ? '' : String(raw);
  if (value.length === 0) return '—';
  const known = LOCATION_LABELS[value];
  if (known) return known;
  const field = value.startsWith('metadata:') ? value.slice('metadata:'.length) : '';
  return field ? `Metadata — ${humanize(field)}` : humanize(value);
};

/** Registry data-classification names. One enum, one rendering. */
const CLASSIFICATION_LABELS: Record<string, string> = {
  internal: 'Internal',
  confidential: 'Confidential',
  restricted: 'Restricted',
  public: 'Public',
};

export const classificationLabel = (raw: string): string =>
  CLASSIFICATION_LABELS[raw] ?? humanize(raw);

/** Memory-event kinds. */
const EVENT_KIND_LABELS: Record<string, string> = {
  findings_recorded: 'Findings recorded',
};

export const eventKindLabel = (raw: string): string =>
  EVENT_KIND_LABELS[raw] ?? humanize(raw);

/** "1 artifact", never "1 ARTIFACTS". */
export const plural = (n: number, word: string): string =>
  `${n} ${word}${n === 1 ? '' : 's'}`;

/**
 * A case id as it is shown in a grid: the `CASE-` prefix is chrome repeated on
 * every row, so it is stripped once, here, rather than differently per surface.
 * The full id stays in the cell `title` and on the record header.
 */
export const caseRef = (caseId: string): string => caseId.replace(/^CASE-/, '');

export const shortHash = (hash: string, chars = 10): string => {
  const bare = hash.replace(/^sha256:/, '');
  return `${bare.slice(0, chars)}…`;
};

/* --- time ----------------------------------------------------------------
   The zone is resolved ONCE, here, and declared once per feed by whichever
   surface renders it. Every surface said "local" or recomputed this; a
   timestamp that reads `PDT` on one pane and `local` on the next is two
   facts, not one. */

/** The viewer's zone, abbreviated — e.g. `PDT`. Declared once per feed. */
export const LOCAL_ZONE: string =
  new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' })
    .formatToParts(new Date())
    .find((p) => p.type === 'timeZoneName')?.value ?? 'local';

/** The viewer's IANA zone — e.g. `America/Los_Angeles`. For a `title` only. */
export const LOCAL_ZONE_LONG: string =
  Intl.DateTimeFormat().resolvedOptions().timeZone;

const CLOCK = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
});

const CLOCK_PRECISE = new Intl.DateTimeFormat('en-US', {
  month: 'short', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});

export const clock = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : CLOCK.format(d);
};

/** To the second, for a security-event feed where ordering is the point. */
export const clockPrecise = (iso: unknown): string => {
  const d = new Date(String(iso ?? ''));
  return Number.isNaN(d.getTime()) ? '—' : CLOCK_PRECISE.format(d);
};

export const holdCountdown = (hours: number): string => {
  if (hours <= 0) return 'expired';
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
};
