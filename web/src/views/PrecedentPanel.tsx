import { useCallback, useEffect, useState } from 'react';
import { Gavel, Scale } from 'lucide-react';
import { api, ApiError } from '@/lib/api';
import type {
  CaseDetail, HumanOutcome, Precedent, PrecedentCitation, PrecedentMatchResult,
} from '@/lib/types';
import { clock, LOCAL_ZONE, LOCAL_ZONE_LONG, money, outcomeLabel } from '@/lib/format';
import { DataGrid, type Column } from '@/components/DataGrid';
import {
  Button, Callout, ConfidenceBar, FieldRow, Input, KeyValue, LoadBar, MonoId, NonIdealState,
  OUTCOME_TONE, Pill, Region, SectionHeader, Tag, Timestamp,
} from '@/components/primitives';

/* ============================================================================
   PRECEDENT — what this district decided the last time it saw a case like this.

   Sits beside Memory on the Docket because the two are the same faculty pointed
   at different things: memory remembers the ATTACKER, precedent remembers the
   ORGANISATION. One tells the operator who is on the other end; the other tells
   them what their own colleagues did about it, and who signed for it.

   THREE BANDS, in the order an auditor reads them:

     the citation   which earlier ruling spoke to this case, what it scored,
                    and whether the clerk argued that it actually governs
     the resolution the form that turns THIS escalation into the next citation,
                    open only while the case is genuinely escalated
     the book       every resolution this district has recorded

   NO OXBLOOD except on a BLOCK. A precedent is an argument, not an alarm; the
   score, the match reasons and the clerk's opinion are all structure, so they
   are brass and neutral. `--oxblood` appears only where the outcome word BLOCK
   does, which is money actually being stopped.
   ============================================================================ */

/** 12px surface gutter, matching every other tab on this surface. */
const GUT = 'px-3';
/** One reading measure for prose. */
const MEASURE = 'max-w-[92ch]';

const DASH = <span className="text-[var(--color-ink-faint)]">—</span>;

const BAND_LABELS: Record<string, string> = {
  below_callback_threshold: 'Below the callback threshold',
  callback_required: 'Callback required',
  above_release_ceiling: 'Above the release ceiling',
};

const TENURE_LABELS: Record<string, string> = {
  new: 'New vendor',
  under_2y: 'Under two years',
  established: 'Established',
};

export function PrecedentPanel({
  caseId, detail, nonce, tenantId, onResolved,
}: {
  caseId: string;
  detail: CaseDetail | null;
  nonce: number;
  tenantId: string | null;
  onResolved: () => void;
}) {
  const [match, setMatch] = useState<PrecedentMatchResult | null>(null);
  const [book, setBook] = useState<Precedent[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    let live = true;
    setLoading(true);
    void Promise.all([
      api.precedent.forCase(caseId).catch(() => null),
      api.precedent.all(tenantId ?? undefined).catch(() => ({ precedents: [], count: 0 })),
    ])
      .then(([m, b]) => {
        if (!live) return;
        setMatch(m);
        setBook(b.precedents);
      })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [caseId, tenantId]);

  useEffect(() => load(), [load, nonce]);

  const escalated = detail?.state === 'escalated';
  const cited = match?.cited ?? null;

  const columns: Column<Precedent>[] = [
    {
      key: 'precedent',
      header: 'Precedent',
      width: '140px',
      sortable: true,
      value: (r) => r.precedent_id,
      render: (r) => <MonoId>{r.precedent_id}</MonoId>,
    },
    {
      key: 'outcome',
      header: 'Resolved to',
      width: '104px',
      sortable: true,
      value: (r) => r.outcome,
      render: (r) => (
        <Pill tone={OUTCOME_TONE[r.outcome]} minWidth={68}>{outcomeLabel(r.outcome)}</Pill>
      ),
    },
    {
      key: 'exposure',
      header: 'Exposure',
      width: '116px',
      numeric: true,
      sortable: true,
      value: (r) => Number(r.exposure_amount),
      render: (r) => (
        <span data-numeric="" className="font-mono tabular">{money(r.exposure_amount)}</span>
      ),
    },
    {
      key: 'by',
      header: 'Decided by',
      width: '160px',
      sortable: true,
      value: (r) => r.decided_by,
      title: (r) => r.decided_by,
      render: (r) => <span className="truncate">{r.decided_by}</span>,
    },
    {
      key: 'at',
      header: `Decided (${LOCAL_ZONE})`,
      width: '132px',
      headerTitle: `Local time — ${LOCAL_ZONE_LONG}`,
      sortable: true,
      value: (r) => r.decided_at,
      render: (r) => <Timestamp>{clock(r.decided_at)}</Timestamp>,
    },
    {
      key: 'cited',
      header: 'Cited by',
      width: '84px',
      numeric: true,
      sortable: true,
      value: (r) => r.cited_by_case_ids.length,
      title: (r) => (r.cited_by_case_ids.join(', ') || 'Never cited'),
      render: (r) => r.cited_by_case_ids.length,
    },
    {
      key: 'rationale',
      header: 'Rationale',
      title: (r) => r.rationale,
      render: (r) => (
        <span className="truncate text-[var(--color-ink-muted)]">{r.rationale}</span>
      ),
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <LoadBar loading={loading} />
      <SectionHeader
        title="Precedent"
        actions={
          <span className="label-micro tabular">
            {match ? `${match.candidates_considered} in the book` : '—'}
          </span>
        }
      />
      <Region label="Precedent">
        <Citation citation={cited} />

        {escalated && (
          <ResolveForm
            caseId={caseId}
            exposure={detail?.exposure_amount ?? '0'}
            onResolved={() => { onResolved(); load(); }}
          />
        )}

        <SectionHeader title="The book" tone="neutral" />
        <DataGrid
          label="Recorded precedents"
          density="dense"
          columns={columns}
          rows={book}
          rowKey={(r) => r.precedent_id}
          defaultSort={{ key: 'at', dir: 'desc' }}
          loading={loading && book.length === 0}
          skeletonRows={6}
          empty={
            <NonIdealState
              visual={<Scale aria-hidden size={22} strokeWidth={1.75} />}
              title="No resolutions recorded yet"
              description="The book fills as people resolve escalations. Until it has an entry, every escalation costs a fresh judgement."
            />
          }
        />
      </Region>
    </div>
  );
}

/* --- the citation ---------------------------------------------------------
   The one thing an auditor asks first: did this case lean on an earlier
   decision, and was that lean argued or assumed? A missing opinion is stated
   as a missing opinion — never rendered as agreement. */

function Citation({ citation }: { citation: PrecedentCitation | null }) {
  if (!citation) {
    return (
      <div className={`py-3 ${GUT}`}>
        <Callout compact>
          Nothing in this district's book scores above the citation threshold for this case.
        </Callout>
      </div>
    );
  }

  const opinion = citation.opinion;
  const governs = opinion?.governs === true;

  return (
    <div className={`flex flex-col gap-3 py-3 ${GUT}`}>
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <KeyValue label="Cited precedent" className="min-w-[160px]">
          <MonoId copyable>{citation.precedent_id}</MonoId>
        </KeyValue>
        <KeyValue label="Prior case" className="min-w-[160px]">
          <MonoId copyable>{citation.prior_case_id}</MonoId>
        </KeyValue>
        <KeyValue label="Resolved to" className="min-w-[112px]">
          <Pill tone={OUTCOME_TONE[citation.outcome]} minWidth={68}>
            {outcomeLabel(citation.outcome)}
          </Pill>
        </KeyValue>
        <KeyValue label="Decided by" className="min-w-[160px]">{citation.decided_by}</KeyValue>
        <KeyValue label="Match" className="min-w-[112px]">
          {/* Brass, not a severity hue: a similarity score is structure. */}
          <ConfidenceBar value={citation.score} />
        </KeyValue>
      </div>

      <dl>
        <FieldRow label="Exposure band">{BAND_LABELS[citation.key.exposure_band] ?? citation.key.exposure_band}</FieldRow>
        <FieldRow label="Callback">
          {citation.key.callback_resolved ? 'Answered on the number of record' : 'Never answered'}
        </FieldRow>
        <FieldRow label="Vendor tenure">
          {TENURE_LABELS[citation.key.vendor_tenure_band] ?? citation.key.vendor_tenure_band}
        </FieldRow>
        <FieldRow label="Lane pattern">
          <span className="flex flex-wrap gap-1">
            {citation.key.verdict_pattern.length
              ? citation.key.verdict_pattern.map((v) => <Tag key={v} tone="neutral">{v}</Tag>)
              : DASH}
          </span>
        </FieldRow>
        <FieldRow label="Matched on">
          <span className="flex flex-wrap gap-1">
            {citation.matched_on.length
              ? citation.matched_on.map((m) => <Tag key={m} tone="brass">{m}</Tag>)
              : DASH}
          </span>
        </FieldRow>
      </dl>

      {/* The reviewer's words, verbatim. A citation months later has to quote what
          they actually wrote, not a paraphrase that drifted. */}
      <blockquote
        className={`border-l-2 border-[var(--color-brass)] pl-3 text-base leading-6
          text-[var(--color-ink-muted)] ${MEASURE}`}
      >
        {citation.rationale}
      </blockquote>
      <Timestamp dim>{clock(citation.decided_at)}</Timestamp>

      <Callout
        compact
        tone={governs ? 'amber' : 'neutral'}
        title={
          opinion
            ? governs ? 'The clerk argued this precedent governs' : 'The clerk distinguished this case'
            : 'No argument was made'
        }
      >
        {opinion ? (
          <>
            <p className="text-mini leading-5">{opinion.reasoning}</p>
            {opinion.distinguished_by && (
              <p className="mt-1 text-mini leading-5 text-[var(--color-ink-dim)]">
                Distinguished by: {opinion.distinguished_by}
              </p>
            )}
          </>
        ) : (
          <p className="text-mini leading-5">
            The clerk was unavailable, so the match stands as a match and nothing more.
          </p>
        )}
      </Callout>
    </div>
  );
}

/* --- the resolution -------------------------------------------------------
   Where the loop closes. An escalation that dead-ends at a human teaches the
   fleet nothing; a named person, a rationale and an outcome make the next case
   of the same shape cheaper. The rationale is required by the same rule that
   requires evidence on a finding — a position that cannot show its work must
   not carry weight later (INV-8). */

function ResolveForm({
  caseId, exposure, onResolved,
}: {
  caseId: string;
  exposure: string;
  onResolved: () => void;
}) {
  // BLOCK is the default because a payment held in error is paid a week late and a payment
  // released in error is gone. It is a default, not a shortcut: nothing submits without a named
  // person and a rationale, so the conservative option is never one click away either.
  const [outcome, setOutcome] = useState<HumanOutcome>('BLOCK');
  const [rationale, setRationale] = useState('');
  const [decidedBy, setDecidedBy] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = rationale.trim().length > 0 && decidedBy.trim().length > 0;

  const submit = () => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    void api.precedent.resolve(caseId, outcome, rationale.trim(), decidedBy.trim())
      .then(() => {
        setRationale('');
        setDecidedBy('');
        onResolved();
      })
      .catch((e: unknown) => {
        setError(
          e instanceof ApiError
            ? e.status === 409
              ? 'This case is no longer escalated — someone has already resolved it.'
              : `The resolution was refused (HTTP ${e.status}).`
            : 'The resolution could not reach the backend.',
        );
      })
      .finally(() => setBusy(false));
  };

  return (
    <>
      <SectionHeader
        title="Resolve this escalation"
        actions={
          <span data-numeric="" className="font-mono tabular text-mini text-[var(--color-ink-dim)]">
            {money(exposure)}
          </span>
        }
      />
      <div className={`flex flex-col gap-3 py-3 ${GUT}`}>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-[2px]">
            <span className="label-micro">Outcome</span>
            <div
              role="radiogroup"
              aria-label="Outcome"
              className="flex h-[30px] items-center gap-1"
            >
              {(['RELEASE', 'BLOCK'] as const).map((o) => (
                <Button
                  key={o}
                  size="sm"
                  variant={outcome === o ? 'default' : 'outlined'}
                  tone={outcome === o ? OUTCOME_TONE[o] : 'neutral'}
                  onClick={() => setOutcome(o)}
                >
                  {outcomeLabel(o)}
                </Button>
              ))}
            </div>
          </div>

          <label className="flex min-w-[220px] flex-col gap-[2px]">
            <span className="label-micro">Decided by</span>
            <Input
              value={decidedBy}
              onChange={setDecidedBy}
              placeholder="Name and role"
              ariaLabel="Decided by"
            />
          </label>

          <label className="flex min-w-[320px] flex-1 flex-col gap-[2px]">
            <span className="label-micro">Rationale</span>
            <Input
              value={rationale}
              onChange={setRationale}
              placeholder="Why, in one or two sentences"
              ariaLabel="Rationale"
            />
          </label>

          <Button
            size="md"
            variant="default"
            tone="brass"
            disabled={!ready || busy}
            onClick={submit}
            title={ready ? 'Record this resolution and finalise the payments' : 'A resolution needs a named person and a rationale'}
          >
            {busy ? 'Recording…' : 'Record resolution'}
          </Button>
        </div>

        {!ready && (
          <p className="text-mini leading-5 text-[var(--color-ink-faint)]">
            A name and a rationale are required.
          </p>
        )}

        {error && (
          <Callout compact tone="amber" icon={<Gavel size={12} strokeWidth={1.75} aria-hidden />}>
            {error}
          </Callout>
        )}
      </div>
    </>
  );
}
