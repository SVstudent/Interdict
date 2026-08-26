import { useCallback, useEffect, useState } from 'react';
import { Swords } from 'lucide-react';
import { api, ApiError } from '@/lib/api';
import type { AttackVariant, RedTeamRun, RedTeamScoreboard, RedTeamTrial } from '@/lib/types';
import { clock, LOCAL_ZONE, outcomeLabel, pct, plural } from '@/lib/format';
import { DataGrid, type Column } from '@/components/DataGrid';
import {
  Button, Callout, Latency, MonoId, NonIdealState, Panel, Pill, Timestamp,
  TONE_RAIL,
} from '@/components/primitives';

/* ============================================================================
   RED TEAM — the fleet's own score, on the surface that catalogues the fleet.

   It lives on Registry rather than Posture because the hit rate is a claim
   about THESE AGENTS. Registry is where a procurement reviewer reads an agent's
   version history and its scope manifest to decide whether to trust it; "and
   here is how it did when we attacked it on purpose" is the third column of
   that same argument. Posture answers a different question — what the system
   did with data it was given — and a scoreboard there would be a statistic
   filed under events.

   TWO NUMBERS, IN THIS ORDER. The hit rate first, because it is the claim.
   The escapes second, because they are the only part anyone can act on.

   NO OXBLOOD. An escape is a finding about the fleet, not money being stopped;
   it renders amber, the hue this system already uses for "a person needs to
   look at this". Painting it red would spend the oxblood budget on a
   simulation and dilute the one place it means a real interdiction.
   ============================================================================ */

const DEFAULT_VARIANTS = 3;

export function RedTeamPanel() {
  const [runs, setRuns] = useState<RedTeamRun[]>([]);
  const [board, setBoard] = useState<RedTeamScoreboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    let live = true;
    void api.redteam.runs()
      .then((r) => { if (live) { setRuns(r.runs); setBoard(r.scoreboard); setError(null); } })
      .catch(() => { if (live) { setRuns([]); setBoard(null); } })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  useEffect(() => load(), [load]);

  /* Dry by default and labelled as such. A wet run drives the whole pipeline once
     per variant against the sandbox tenant, which is the honest test and also the
     expensive one; the operator should choose it deliberately, never by reflex. */
  const generate = (dryRun: boolean) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    void api.redteam.start(DEFAULT_VARIANTS, dryRun)
      .then(() => load())
      .catch((e: unknown) => {
        setError(
          e instanceof ApiError
            ? e.status === 503
              ? 'Replay mode has no recording for this generation. A red team running against a stub of itself measures nothing, so it declines to run.'
              : `The run was refused (HTTP ${e.status}).`
            : 'The run could not reach the backend.',
        );
      })
      .finally(() => setBusy(false));
  };

  const latest = runs[0] ?? null;
  const trials: RedTeamTrial[] = runs.flatMap((r) => r.trials);
  const escaped = board?.escaped ?? [];

  const columns: Column<RedTeamTrial>[] = [
    {
      key: 'variant',
      header: 'Attack',
      width: '208px',
      sortable: true,
      value: (r) => r.variant_name,
      title: (r) => `${r.variant_name} — ${r.technique}`,
      render: (r) => (
        <span className="truncate font-medium text-[var(--color-ink)]">{r.variant_name}</span>
      ),
    },
    {
      key: 'technique',
      header: 'Technique',
      width: '184px',
      sortable: true,
      value: (r) => r.technique,
      title: (r) => r.technique,
      render: (r) => <span className="truncate text-[var(--color-ink-dim)]">{r.technique}</span>,
    },
    {
      key: 'result',
      header: 'Result',
      width: '104px',
      sortable: true,
      value: (r) => (r.caught ? 1 : 0),
      headerTitle: 'ESCALATE counts as caught: stopping the money and asking a person is the designed outcome',
      render: (r) => (
        <Pill tone={r.caught ? 'verdigris' : 'amber'} minWidth={68}>
          {r.caught ? 'Caught' : 'Escaped'}
        </Pill>
      ),
    },
    {
      key: 'outcome',
      header: 'Adjudication',
      width: '112px',
      sortable: true,
      value: (r) => r.outcome ?? '',
      render: (r) => (
        r.outcome
          /* Deliberately not OUTCOME_TONE: that map paints BLOCK oxblood, and a BLOCK here
             stopped a fictional payment in a sandbox tenant. The Result column beside this one
             already carries the judgement in colour, so this stays a factual label. */
          ? <Pill tone="neutral" minWidth={68}>{outcomeLabel(r.outcome)}</Pill>
          : <span className="text-[var(--color-ink-faint)]">—</span>
      ),
    },
    {
      key: 'why',
      header: 'Top signal, or why it got through',
      title: (r) => r.escaped_reason ?? r.top_signal ?? '',
      render: (r) => (
        <span
          className={r.caught
            ? 'truncate text-[var(--color-ink-muted)]'
            : 'truncate text-[var(--color-amber-text)]'}
        >
          {r.escaped_reason ?? r.top_signal ?? '—'}
        </span>
      ),
    },
    {
      key: 'latency',
      header: 'Latency',
      width: '92px',
      numeric: true,
      sortable: true,
      value: (r) => r.latency_ms,
      render: (r) => <Latency ms={r.latency_ms} />,
    },
  ];

  return (
    <Panel
      title="Red team"
      label="Red team scoreboard"
      className="min-h-0 rule-t"
      actions={
        <>
          <span className="label-micro tabular">
            {board ? plural(board.runs, 'run') : '—'}
          </span>
          <Button
            size="sm"
            variant="minimal"
            disabled={busy}
            onClick={() => generate(true)}
            title="Invent new tradecraft and show it without executing it — one model call"
          >
            Invent only
          </Button>
          <Button
            size="sm"
            variant="outlined"
            tone="brass"
            disabled={busy}
            onClick={() => generate(false)}
            title="Invent and then run each attack through the real pipeline against the sandbox tenant — several model calls per attack"
          >
            {busy ? 'Running…' : 'Invent and attack'}
          </Button>
        </>
      }
      footer={
        <>
          <span className="label-micro">Sandbox</span>
          <MonoId>{latest?.tenant_id ?? '—'}</MonoId>
          <span className="flex-1" />
          <span className="label-micro">{`Last run (${LOCAL_ZONE})`}</span>
          <Timestamp>{latest ? clock(latest.started_at) : '—'}</Timestamp>
        </>
      }
    >
      <div className="flex flex-col">
        <Scoreboard board={board} />

        {error && (
          <div className="px-3 pb-3">
            <Callout compact tone="amber"
              icon={<Swords size={12} strokeWidth={1.75} aria-hidden />}>
              {error}
            </Callout>
          </div>
        )}

        {escaped.length > 0 && (
          <div className="px-3 pb-3">
            <Callout compact tone="amber" title={`${plural(escaped.length, 'attack')} got through`}>
              <ul className="flex flex-col gap-1">
                {escaped.map((t) => (
                  <li key={t.variant_id} className="text-mini leading-5">
                    <span className="text-[var(--color-ink)]">{t.variant_name}</span>
                    {' — '}
                    {t.escaped_reason ?? 'no reason recorded'}
                  </li>
                ))}
              </ul>
            </Callout>
          </div>
        )}

        <DataGrid
          label="Red team trials"
          density="dense"
          columns={columns}
          rows={trials}
          rowKey={(r) => r.variant_id}
          rowRail={(r) => (r.caught ? undefined : TONE_RAIL.amber)}
          loading={loading}
          skeletonRows={3}
          empty={
            latest && latest.trials.length === 0
              ? <GeneratedOnly variants={latest.variants} />
              : (
                <NonIdealState
                  visual={<Swords aria-hidden size={22} strokeWidth={1.75} />}
                  title="The fleet has not been attacked yet"
                  description="Red Team reads the threat library, invents tradecraft the fleet has never been shown, and runs it against a sandbox that holds no district's money."
                />
              )
          }
        />
      </div>
    </Panel>
  );
}

/* --- the claim ------------------------------------------------------------
   One figure at 28px, three supporting counts at the body step. §8's ceiling
   rule caps elements ABOVE 28px at two per screen and Registry spends neither,
   so this sits at 28 and is the single thing a muted viewer lands on here. */

function Scoreboard({ board }: { board: RedTeamScoreboard | null }) {
  const executed = (board?.trials ?? 0) > 0;

  return (
    <div className="flex flex-wrap items-end gap-x-8 gap-y-3 rule-b px-3 py-3">
      <div className="flex min-w-[132px] flex-col gap-1">
        <span className="label-brass">Caught</span>
        <span
          data-numeric=""
          className="font-mono tabular text-2xl leading-none text-[var(--color-ink)]"
        >
          {executed ? pct(board?.hit_rate ?? 0) : '—'}
        </span>
      </div>
      {/* Not a "stopped" count as well: that is the rate above times the runs beside
          it, and a third rendering of one number is chrome, not information. */}
      <Count label="Attacks run" value={board?.trials ?? 0} />
      <Count label="Got through" value={board?.escaped.length ?? 0} />
      <Count label="Invented" value={board?.variants_generated ?? 0} />
    </div>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex min-w-[92px] flex-col gap-1">
      <span className="label-micro">{label}</span>
      <span data-numeric="" className="font-mono tabular text-lg leading-none text-[var(--color-ink)]">
        {value}
      </span>
    </div>
  );
}

/**
 * A dry run produces attacks and no trials. Showing an empty grid would read as
 * a failed run, so the generated tradecraft is rendered instead — which is also
 * the only readable artifact a dry run has to offer.
 */
function GeneratedOnly({ variants }: { variants: AttackVariant[] }) {
  return (
    <div className="flex flex-col gap-3 px-3 py-4">
      <p className="max-w-[92ch] text-xs leading-5 text-[var(--color-ink-dim)]">
        Invented but not executed. Each of these is tradecraft the fleet's own matcher does not
        recognise from the threat library — that is the bar a variant has to clear before it is
        worth running.
      </p>
      {variants.map((v) => (
        <div key={v.variant_id} className="flex flex-col gap-1 rule-b pb-3 last:border-b-0">
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-sm font-medium text-[var(--color-ink)]">{v.name}</span>
            <MonoId>{v.reply_to_domain}</MonoId>
            {v.based_on_designation && (
              <Pill tone="neutral">Varies {v.based_on_designation}</Pill>
            )}
          </div>
          <p className="max-w-[92ch] text-mini leading-5 text-[var(--color-ink-muted)]">
            {v.technique}
          </p>
          <p className="max-w-[92ch] text-mini leading-5 text-[var(--color-ink-dim)]">
            {v.novelty}
          </p>
        </div>
      ))}
    </div>
  );
}
