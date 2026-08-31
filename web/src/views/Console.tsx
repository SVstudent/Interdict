import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, Inbox, PlugZap } from 'lucide-react';
import { api, ApiError } from '@/lib/api';
import type { StreamEvent } from '@/lib/useEvents';
import type {
  CaseDetail, CaseState, CaseSummary, LedgerTotals, Payment, Scenario,
} from '@/lib/types';
import {
  caseRef, clock, holdCountdown, humanize, money, outcomeVerb, stateLabel,
  stateLabelShort,
} from '@/lib/format';
import { useTenant } from '@/lib/tenant';
import { Balance, type LaneState } from '@/components/Balance';
import { RecognitionStrip } from '@/components/ThreatIntel';
import { CallbackPanel } from '@/components/CallbackPanel';
import { InboxPanel } from '@/components/InboxPanel';
import { DataGrid, type Column } from '@/components/DataGrid';
import {
  Button, CasePath, Divider, Money, MonoId, NonIdealState, Panel, Pill, ProgressBar,
  SectionHeader, StateChip, Timestamp, STATE_TONE, TONE_RAIL, TONE_SOLID,
} from '@/components/primitives';

/* ============================================================================
   CONSOLE — the operating surface. Seventy seconds of the recording live here.

   Implemented from context/UI_SPEC.md §14: three panes, 440 | 1fr | 320, each
   scrolling independently, separated by single 1px rules with no decoration
   and no rounded corners.

     LEFT    the docket queue, exposure descending
     CENTRE  the record header, the Path, the Balance, the control bar
     RIGHT   the ledger

   The centre column is a stack of fixed bands around one scrolling region:

      30px  pane header    "Case record"  <- aligns with both flanking panes
      64px  record header  (identity, state, hold, the exposure figure)
      24px  requested change (the premise of the product, in one line)
      32px  the Path       (Opened -> Held -> Verifying -> ... -> Outcome)
       1fr  the Balance
      40px  the control bar

   Every band's height is declared, so an arriving SSE frame repaints values in
   place and moves nothing. That is the whole discipline of this file.

   DEVIATION LEDGER (values off the §1 spacing ramp, all in this file):
     64px  record header   the 44px exposure figure plus its 14px label
     104px inject button, runner readout — fixed control widths that stop the
           control bar reflowing when /api/demo/scenarios resolves
     56/92/144/148px queue column widths (sum 440)
   These need §16 rows in UI_SPEC.md; that file is not owned here.
   ============================================================================ */

/** Non-terminal states. `released` and `blocked` are closed and their money is
    no longer at risk, so they are not "open exposure" — the ledger's own
    `held` total is the number they must agree with. */
const OPEN_STATES: ReadonlySet<CaseState> = new Set<CaseState>([
  'opened', 'held', 'verifying', 'awaiting_callback', 'challenging', 'adjudicating', 'escalated',
]);

const describeError = (err: unknown): string => {
  if (err instanceof ApiError) return `${err.status} on ${err.path}`;
  if (err instanceof Error) return err.message;
  return 'Unreachable';
};

/** What the runner is doing, in words. `busy` also carries the raw token so a
    button can show itself as the active one without the token being copy. */
interface Running { token: string; label: string }

export function Console({
  events, selectedCase, onSelectCase,
}: {
  events: StreamEvent[];
  selectedCase: string | null;
  onSelectCase: (id: string | null) => void;
}) {
  // The district in force. Every money figure on this surface is scoped to it — an
  // operator acting on a queue that merged two districts could release money that is
  // not theirs to release.
  const { tenantId, active, ready, epoch } = useTenant();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [ledger, setLedger] = useState<LedgerTotals | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [busy, setBusy] = useState<Running | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A refetch never re-skeletons; only the very first load reserves rows.
  const [loaded, setLoaded] = useState(false);
  // The operator's two lists. Starts on cases: that is where a hold fires and where the
  // fan-out lands, and opening on the inbox put the surface's whole point behind a click.
  const [leftTab, setLeftTab] = useState<'inbox' | 'cases'>('cases');

  /* A fan-out burst fires refreshes faster than they can return. Without a
     ticket, a slow early response can land after a fast later one and the
     queue walks backwards on camera. Late responses are dropped; a refresh
     asked for while one is in flight collapses into a single trailing run. */
  const ticket = useRef(0);
  const inFlight = useRef(false);
  const trailing = useRef(false);

  const refresh = async (): Promise<void> => {
    if (inFlight.current) { trailing.current = true; return; }
    inFlight.current = true;
    const mine = (ticket.current += 1);
    try {
      const scope = tenantId ?? undefined;
      const [rows, totals] = await Promise.all([api.cases(scope), api.ledger(scope)]);
      if (mine !== ticket.current) return;
      setCases(rows);
      setLedger(totals);
      setError(null);
      // After a reset the previous case_id is gone. Without this the centre
      // pane stays empty for the rest of the session.
      if (!selectedCase || !rows.some((r) => r.case_id === selectedCase)) {
        onSelectCase(rows[0]?.case_id ?? null);
      }
    } catch (err) {
      if (mine === ticket.current) setError(describeError(err));
    } finally {
      inFlight.current = false;
      setLoaded(true);
      if (trailing.current) { trailing.current = false; void refresh(); }
    }
  };

  useEffect(() => {
    void refresh();
    void api.demo.scenarios().then(setScenarios).catch(() => setScenarios([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Switching district reloads the queue and the ledger together, so the two panes
  // are never one district's cases beside the other's totals.
  useEffect(() => {
    if (!ready) return;
    setLoaded(false);
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, tenantId, epoch]);

  /* The stream drives the surface; nothing here polls. The buffer in
     useEvents is CAPPED, so `events.length` stops changing once it is full and
     an effect keyed on the length goes permanently deaf mid-demo. Key on the
     identity of the newest event instead, and publish a tick the fetches can
     depend on. */
  const seen = useRef<StreamEvent | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const newest = events.length > 0 ? events[events.length - 1] ?? null : null;
    if (newest === seen.current) return;
    seen.current = newest;
    setTick((t) => t + 1);
  }, [events]);

  useEffect(() => {
    if (tick === 0) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  /* FOLLOW THE CASE THAT JUST OPENED.

     Without this the console is a queue that fills up while the centre pane stays on whatever
     was selected before — so injecting a scenario advanced a row from `verifying` to `blocked`
     in the list while the fan-out, the balance and the verdict all played out off screen. The
     entire point of the surface happened somewhere the operator was not looking.

     Bound to `case_opened` rather than to the injection request, because that request does not
     return until the fleet has also written its dossier and run its sweep — a minute after the
     case exists. The event lands about two seconds in, which is when there is something to
     watch. Following the newest case is also just what a live interdiction queue should do. */
  const followed = useRef<string | null>(null);
  useEffect(() => {
    for (let i = events.length - 1; i >= 0; i -= 1) {
      const e = events[i];
      if (e?.event !== 'case_opened') continue;
      const id = typeof e.data?.case_id === 'string' ? e.data.case_id : null;
      if (id && id !== followed.current) {
        followed.current = id;
        onSelectCase(id);
      }
      return;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  useEffect(() => {
    if (!selectedCase) { setDetail(null); return; }
    void api.case(selectedCase).then(setDetail).catch(() => setDetail(null));
  }, [selectedCase, tick]);

  const lanes = useMemo(() => deriveLanes(events, selectedCase), [events, selectedCase]);
  const laneRunning = useMemo(
    () => Object.values(lanes).some((l) => l.status === 'running'),
    [lanes],
  );
  const challengeLanded = Boolean(detail?.challenge);

  const summary = useMemo(
    () => cases.find((c) => c.case_id === selectedCase) ?? null,
    [cases, selectedCase],
  );

  const openCases = useMemo(() => cases.filter((c) => OPEN_STATES.has(c.state)), [cases]);
  const openExposure = useMemo(
    () => openCases.reduce((sum, c) => sum + (Number(c.exposure_amount) || 0), 0),
    [openCases],
  );

  const run = async (token: string, label: string, fn: () => Promise<unknown>) => {
    if (busy) return;                       // the bar stays live; the guard is here
    setBusy({ token, label });
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(null);
    }
  };

  /* THE CASE QUEUE. This column set is shared, value for value, with the queue
     on Docket — same widths, same renderers, same vocabulary — because it is
     the same grid of the same rows and an operator must not have to re-learn
     it between surfaces. Change it here and there together.

     Widths are sized to the widest value each column can render, in the face
     that renders it, plus the grid's 12/8px cell padding:
       case      6 mono glyphs (ids are CASE- + 6 hex) ≈ 40 + 20 → 72px
       exposure 10 mono glyphs                         ≈ 66 + 16 → 84px
       state    'ADJUDICATING', a 10px tracked pill with a dot
                                    ≈ 84 + 23 chrome  + 20 → 132px
     Vendor is the one flexible column: it absorbs the remainder, so the
     stable 9px scrollbar gutter comes out of the truncating name and never
     out of a column that would shear a value. Nothing here reflows on data. */
  const columns: Column<CaseSummary>[] = [
    {
      key: 'case', header: 'Case', width: '72px', sortable: true,
      value: (r) => r.case_id,
      title: (r) => r.case_id,
      render: (r) => <MonoId>{caseRef(r.case_id)}</MonoId>,
    },
    {
      key: 'vendor', header: 'Vendor', sortable: true,
      value: (r) => r.vendor_name,
      title: (r) => r.vendor_name,
      render: (r) => (
        <span className="block truncate text-[var(--color-ink)]">{r.vendor_name}</span>
      ),
    },
    {
      // One format per column, always. $1.3M above $284K cannot decimal-align,
      // and the pane footer shows the same quantity in full.
      key: 'exposure', header: 'Exposure', width: '84px', numeric: true, sortable: true,
      value: (r) => Number(r.exposure_amount),
      title: (r) => money(r.exposure_amount, true),
      render: (r) => (
        <span className="text-[var(--color-ink)]">{money(r.exposure_amount)}</span>
      ),
    },
    {
      key: 'state', header: 'State', width: '132px', sortable: true,
      value: (r) => r.state,
      title: (r) => `${stateLabel(r.state)} — hold ${holdCountdown(r.hold_remaining_hours)}`,
      render: (r) => (
        <Pill tone={STATE_TONE[r.state]} dot minWidth={68}>{stateLabelShort(r.state)}</Pill>
      ),
    },
  ];

  return (
    <div className="grid h-full grid-cols-[368px_minmax(0,1fr)_312px]">
      {/* LEFT — the docket queue, exposure descending -------------------- */}
      <Panel
        title={
          /* The operator's two lists, not two surfaces: what arrived, and what is being
             worked. A segmented control keeps them one glance apart. */
          <span className="flex items-center gap-0">
            {(['inbox', 'cases'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setLeftTab(t)}
                aria-current={leftTab === t ? 'true' : undefined}
                className={`h-[22px] border-b-2 px-2 text-mini font-semibold uppercase
                  tracking-[0.08em] transition-colors
                  ${leftTab === t
                    ? 'border-[var(--color-brass)] text-[var(--color-brass)]'
                    : 'border-transparent text-[var(--color-ink-faint)] hover:text-[var(--color-ink-dim)]'}`}
              >
                {t === 'inbox' ? 'Inbox' : 'Cases'}
              </button>
            ))}
          </span>
        }
        label="Inbox and case queue"
        className="rule-r"
        actions={
          leftTab === 'cases' ? (
            <span className="text-mini text-[var(--color-ink-dim)]">
              <span data-numeric="" className="font-mono">{cases.length}</span> cases
            </span>
          ) : undefined
        }
        footer={
          <>
            <span className="label-micro">Open exposure</span>
            <span data-numeric="" className="font-mono text-mini text-[var(--color-ink-dim)]">
              {openCases.length} open
            </span>
            <span className="ml-auto">
              <Money value={openExposure} size="sm" />
            </span>
          </>
        }
      >
        {error && cases.length === 0 ? (
          <NonIdealState
            tone="amber"
            visual={<PlugZap aria-hidden size={22} strokeWidth={1.75} />}
            title="The case service did not answer"
            description={`The request failed with ${error}. Nothing on this surface is stale —
              there is simply nothing to show until the service answers.`}
            action={
              <Button size="sm" variant="default" onClick={() => { void refresh(); }}>
                Retry
              </Button>
            }
          />
        ) : leftTab === 'inbox' ? (
          <InboxPanel
            /* Deliberately does NOT jump to the Cases tab: the triage summary — how many
               messages were settled without a model call — is the payoff of the run, and
               switching away discards the evidence the operator just earned. The new cases
               are one click away and the queue count updates behind the tab. */
            onCaseOpened={() => { void refresh(); }}
          />
        ) : (
          <DataGrid
            label="Open interdiction cases"
            columns={columns}
            rows={cases}
            rowKey={(r) => r.case_id}
            onSelect={(r) => onSelectCase(r.case_id)}
            selectedKey={selectedCase}
            defaultSort={{ key: 'exposure', dir: 'desc' }}
            loading={!loaded}
            skeletonRows={14}
            density="compact"
            /* Redundant encoding: severity is colour AND a 2px position rail. */
            rowRail={(r) => TONE_RAIL[STATE_TONE[r.state]]}
            empty={
              <NonIdealState
                visual={<Inbox aria-hidden size={22} strokeWidth={1.75} />}
                title={active ? `No cases open at ${active.display_name}` : 'No cases open'}
                description="A district with an empty queue has not been attacked, not lost its
                  data. Inject a scenario from the control bar, or process the inbox, to open one."
              />
            }
          />
        )}
      </Panel>

      {/* CENTRE — the record header, the Path, the Balance --------------- */}
      <div className="flex min-h-0 flex-col">
        <CaseHeader detail={detail} summary={summary} />
        {/* A COLUMN, not a block. Anything that renders above the Balance — the recognition
            strip, the callback panel — is a sibling of it, and `Balance` sizes itself to this
            box. As a plain block the Balance took `h-full` (the whole box) while the strip
            above it added another 115px, so the Balance's own bottom edge, and with it the
            verdict, hung below the fold with nothing able to scroll to it: its internal
            scrollbar only moves content inside a box that was itself off-screen.

            As a flex column the strips are `shrink-0` and the Balance takes what is left, so
            its scrollbar always reaches the verdict no matter what sits above it. */}
        <div className="flex min-h-0 flex-1 flex-col">
          <>
            {/* The fleet recognising a known operation is the highest-value signal available,
                so it sits above the balance rather than inside the finding list. */}
            {(() => {
              const hit = detail?.findings.find((f) => f.agent === 'attribution');
              if (!hit) return null;
              const locator = hit.evidence[0]?.locator ?? '';
              const m = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(locator);
              return (
                <div className="shrink-0">
                  <RecognitionStrip
                    finding={hit}
                    designation={m?.[1] ?? 'Known operation'}
                    priorCaseId={m?.[2] ?? '—'}
                  />
                </div>
              );
            })()}
            {detail?.state === 'awaiting_callback' && (
              <div className="shrink-0">
                <CallbackPanel caseId={detail.case_id} onResolved={() => void refresh()} />
              </div>
            )}
            <Balance detail={detail} lanes={lanes} challengeLanded={challengeLanded} />
          </>
        </div>
        <DemoBar
          scenarios={scenarios}
          busy={busy}
          run={run}
          caseId={selectedCase}
          /* At most one indeterminate sweep exists on this surface: the
             Balance owns it while lanes are running, the bar owns it when a
             command is in flight and no lane is. */
          showSweep={busy !== null && !laneRunning}
        />
      </div>

      {/* RIGHT — the ledger ---------------------------------------------- */}
      <Panel
        title="Ledger"
        label="Ledger totals"
        className="rule-l"
        footer={
          <>
            <span className="ml-auto">
              <Timestamp>{ledger ? clock(ledger.as_of) : '—'}</Timestamp>
            </span>
          </>
        }
      >
        <LedgerPanel ledger={ledger} detail={detail} />
      </Panel>
    </div>
  );
}

/* --- case header (record-header pattern) ----------------------------------
   Four bands under one 30px pane header, so the first rule in the centre lands
   at y=30 exactly as it does in both flanking panes. Identity and the one
   figure that matters on top; then the change that opened the case; then the
   state machine as a Path, so the case's position in the process is legible
   without audio and without a click. */

const MASK = '••••';

function CaseHeader({
  detail, summary,
}: { detail: CaseDetail | null; summary: CaseSummary | null }) {
  const from = detail?.vendor?.banking;
  const to = detail?.request?.proposed_banking;

  return (
    <div className="shrink-0">
      <SectionHeader title="Case record" />

      <header className="flex h-[64px] items-center gap-6 px-4">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline gap-3">
            <h1 className="truncate font-display text-xl text-[var(--color-ink)]">
              {detail?.vendor?.legal_name ?? (detail ? 'Unresolved vendor' : 'No case selected')}
            </h1>
            {/* Always copyable, so the node count never changes with the data. */}
            <MonoId dim truncate copyable>
              {detail?.case_id ?? '—'}
            </MonoId>
          </div>

          <div className="mt-1 flex min-w-0 items-center gap-3">
            {/* The header has room for the full operator phrase, so it uses it:
                "Waiting on vendor callback", not "Awaiting callback". */}
            {detail
              ? <StateChip state={detail.state} minWidth={68} />
              : <Pill tone="neutral" dot minWidth={68}>—</Pill>}
            <Divider vertical />
            <span className="label-micro shrink-0">Payments held</span>
            <span data-numeric="" className="font-mono text-mini text-[var(--color-ink-dim)]">
              {detail ? detail.held_payments.length : '—'}
            </span>
            <span className="label-micro shrink-0">Hold</span>
            <span data-numeric="" className="font-mono text-mini text-[var(--color-ink-dim)]">
              {/* One figure, one clock: the queue's server-computed countdown,
                  never a second one computed against the browser's. */}
              {summary ? holdCountdown(summary.hold_remaining_hours) : '—'}
            </span>
          </div>
        </div>

        {/* The exposure figure. One of exactly two elements on this screen
            permitted above 28px; the verdict is the other. It steps down to
            22px below 1536px, where the centre pane is too narrow to hold
            $1,284,000.00 at 44px without overflowing the header. */}
        <div className="flex shrink-0 flex-col items-end justify-center">
          <span className="label-micro">Exposure</span>
          <Money
            value={detail?.exposure_amount ?? Number.NaN}
            size="lg"
            cents
            className="2xl:text-figure"
          />
        </div>
      </header>

      {/* The premise of the product, written down. A muted viewer is otherwise
          never told that a payee account was changed. The old value is struck
          in NEUTRAL ink — a superseded number is not money being stopped. */}
      <div className="flex h-[24px] min-w-0 items-center gap-2 overflow-hidden px-4">
        <span className="label-micro shrink-0">Requested change</span>
        <span
          data-numeric=""
          className="shrink-0 font-mono text-mini text-[var(--color-ink-dim)]
            line-through decoration-[var(--color-ink-faint)]"
        >
          {from ? `${MASK}${from.account_last4}` : '—'}
        </span>
        <ArrowRight aria-hidden size={11} strokeWidth={1.75}
          className="shrink-0 text-[var(--color-ink-faint)]" />
        <span data-numeric="" className="shrink-0 font-mono text-mini text-[var(--color-ink)]">
          {to ? `${MASK}${to.account_last4}` : '—'}
        </span>
        <span className="truncate text-mini text-[var(--color-ink-muted)]">
          {to?.bank_name ?? '—'}
        </span>
        <span className="label-micro shrink-0">Bank / vendor country</span>
        <span className="shrink-0 text-mini text-[var(--color-ink-dim)]">
          {to?.bank_country ?? '—'}
        </span>
        <span className="shrink-0 text-mini text-[var(--color-ink-dim)]">
          {detail?.vendor?.operating_country ?? '—'}
        </span>
      </div>

      {/* The Path. Six stages over the CaseState machine; a terminal outcome
          recolours the whole track. The rules sit on the wrapper so the
          chevrons stay exactly 30px inside a 32px band. */}
      <div className="rule-t rule-b">
        {detail
          ? <CasePath state={detail.state} />
          : (
            <div className="flex h-[30px] items-center px-4">
              <span className="label-micro">Case progress — select a case</span>
            </div>
          )}
      </div>
    </div>
  );
}

/* --- ledger ---------------------------------------------------------------
   Label above value, label smaller than value. One encoding per row, not
   three: the 2px tone rail and the share meter carry the hue, the money is
   plain ink. 48px rows leave room for the thing the operator actually needs
   next to the totals — the payments this case is holding.
   --oxblood appears on exactly one row: blocked. */

const LEDGER_ROWS = [
  { key: 'held', label: 'Held', tone: 'amber' },
  { key: 'blocked', label: 'Blocked', tone: 'oxblood' },
  { key: 'escalated', label: 'Escalated', tone: 'amber' },
  { key: 'released', label: 'Released', tone: 'verdigris' },
] as const;

function LedgerPanel({
  ledger, detail,
}: { ledger: LedgerTotals | null; detail: CaseDetail | null }) {
  const amounts = LEDGER_ROWS.map(({ key }) => Number(ledger?.totals[key] ?? 0) || 0);
  // Share of the TOTAL, not of the largest row — a meter normalised by the max
  // always has one row at 100% and nothing says what 100% means.
  const total = amounts.reduce((a, b) => a + b, 0);
  const held: Payment[] = detail?.held_payments ?? [];

  return (
    <div className="flex flex-col">
      {LEDGER_ROWS.map(({ key, label, tone }, i) => {
        const amount = amounts[i] ?? 0;
        const share = total > 0 ? amount / total : 0;
        return (
          <div
            key={key}
            className={`flex h-[48px] flex-col justify-center gap-1 rule-b px-3 ${TONE_RAIL[tone]}`}
          >
            <div className="flex items-baseline gap-2">
              <span className="label-micro shrink-0">{label}</span>
              <span data-numeric="" className="font-mono text-mini text-[var(--color-ink-dim)]">
                {ledger?.counts[key] ?? 0}
              </span>
              <span className="ml-auto">
                <Money value={ledger?.totals[key] ?? '0'} size="sm" />
              </span>
            </div>

            <span aria-hidden className="block h-[3px] w-full bg-[var(--color-rule)]">
              <span
                className={`block h-full transition-[width] duration-200 ease-[var(--ease-ui)]
                  ${TONE_SOLID[tone]}`}
                style={{ width: `${Math.round(share * 100)}%` }}
              />
            </span>
          </div>
        );
      })}

      <p className="px-3 py-2 text-mini text-[var(--color-ink-dim)]">
        Blocked funds stay with the originator; released funds settle on the next payment run.
      </p>

      <SectionHeader title="Payments held" className="rule-t" />

      {held.length === 0 ? (
        <p className="px-3 py-3 text-xs text-[var(--color-ink-dim)]">
          {detail ? 'This case is holding no payments.' : 'Select a case to see what it is holding.'}
        </p>
      ) : (
        held.map((p) => (
          <div key={p.payment_id} className="flex h-[28px] items-center gap-2 rule-b-muted px-3">
            <MonoId dim truncate>{p.payment_id}</MonoId>
            <span className="ml-auto shrink-0">
              <Money value={p.amount} size="sm" />
            </span>
          </div>
        ))
      )}
    </div>
  );
}

/* --- demo control bar -----------------------------------------------------
   40px, on the ladder. Toolbars are minimal buttons; only the commit action
   (Reset, which rebuilds the world) is filled.

   NOTHING here disables on `busy`. A disabled Button drops to 2.4:1, and
   disabling the whole bar the instant the operator injects S1 greys out the
   surface at exactly the moment being recorded. Re-entry is guarded in `run`
   instead, and the button that is working shows itself as active.

   The inject group is a FIXED-WIDTH container with a fixed slot count, so the
   bar does not reflow when /api/demo/scenarios resolves. Slots render a
   disabled placeholder until the catalog arrives. */

/* The inject group used to be a FIXED 536px box (5 x 104px + gaps) marked `shrink-0`, so that
   the bar could not reflow when /api/demo/scenarios resolved. It achieved that and caused a
   worse bug: the centre column is 704px at a 1440px viewport, the bar's content needs 976px,
   and because the widest child refused to shrink and nothing clipped, `+4 days`, `Kill run`
   and `Resume` were pushed clean out of the column and painted on top of the Ledger.

   The no-reflow guarantee never depended on a fixed WIDTH — it depends on a fixed slot COUNT.
   So the count stays at five (empty slots render a real placeholder, not `null`, which is what
   made a fixed width necessary in the first place) and the slots became elastic: 104px where
   there is room, down to a 76px floor where there is not. At the recording viewport every
   label is full width; while rehearsing at 1440 they truncate and the `title` carries the rest.
   `overflow-x-auto` on the row is the backstop — a control may end up scrolled, never escaped. */
const INJECT_SLOTS = 5;

/* On the WRAPPER, never on the Button. `Button` bakes `shrink-0` into its own class list, and a
   `flex-1` appended after it does not win — both set `flex-shrink`, and which one applies comes
   down to Tailwind's stylesheet order rather than the order of the strings. The first attempt at
   this fix put the sizing on the Button and the two rules cancelled, which let the controls
   collapse under their own labels and overlap. The wrapper owns the geometry; the Button fills
   it. */
const SLOT_W = 'min-w-[70px] flex-1 basis-[104px] overflow-hidden';
/* `overflow-hidden` is load-bearing, not tidying. Without it the slot's min-content width
   is the button's own un-wrappable label, so the group could never shrink past the sum of
   its five labels (~456px) however small `min-w` was — the explicit min-width sets a floor,
   not a ceiling. Hiding the overflow collapses that intrinsic contribution and lets the
   truncation the labels were written for actually happen. */

/** The scenario's own slug, as a sentence. `S1` is a handle, not a label, and
    a label that only exists in `title` does not exist on a muted recording. */
const scenarioLabel = (s: Scenario): string => SCENARIO_LABEL[s.slug] ?? humanize(s.slug);

/* The slug names the FIXTURE; the button names the ATTACK.

   These used to read Block / Injection / Escalate / Release / Crash — three of the five naming
   the verdict the fleet had not computed yet. Watching someone press "Block" and then wait forty
   seconds for the fleet to announce BLOCK makes the reasoning look decorative, which is the
   opposite of the claim. Naming the input leaves the outcome to be earned on screen.

   Kept short because the slot truncates: the humanised slugs ("Poisoned artifact", "Genuine but
   thin", "Delayed release") all clipped. The full headline is on the button's title. */
const SCENARIO_LABEL: Record<string, string> = {
  clean_hit: 'Lookalike',
  poisoned_artifact: 'Poisoned PDF',
  genuine_but_thin: 'Thin evidence',
  delayed_release: 'Late callback',
  crash_resume: 'Crash',
};

function DemoBar({
  scenarios, busy, run, caseId, showSweep,
}: {
  scenarios: Scenario[];
  busy: Running | null;
  run: (token: string, label: string, fn: () => Promise<unknown>) => Promise<void>;
  caseId: string | null;
  showSweep: boolean;
}) {
  const slots = Array.from(
    { length: Math.max(INJECT_SLOTS, scenarios.length) },
    (_, i) => scenarios[i] ?? null,
  );

  return (
    <div className="relative h-[40px] shrink-0 rule-t bg-[var(--color-surface)]">
      <div className="absolute inset-x-0 top-0 h-[2px]">
        {showSweep && busy && (
          <ProgressBar indeterminate tone="brass" label={`Running ${busy.label}`} />
        )}
      </div>

      <div
        className="flex h-[40px] min-w-0 items-center gap-1.5 overflow-x-auto overflow-y-hidden
          px-3 pane-scroll"
      >

        <Button
          size="sm"
          variant="minimal"
          active={busy?.token === 'reset'}
          onClick={() => run('reset', 'Reset world', api.demo.reset)}
          title="Rebuild the demonstration world from seed"
        >
          Reset
        </Button>

        <Divider vertical />
        {/* Asks for its natural 536px and gives width back as the column narrows, down to a
            floor of 366px (5 x 70px + four 4px gaps) stated explicitly rather than left to
            `min-width: auto`. Auto resolved to the sum of the five un-wrappable labels — 456px —
            so the group stopped shrinking 70px early and pushed `Kill run` and `Resume` out of
            the column. Below the floor the row scrolls; nothing is ever painted outside it. */}
        <div className="flex min-w-[366px] flex-[0_1_536px] items-center gap-1">
          {slots.map((s, i) => (s ? (
            <span key={s.scenario_id} className={SLOT_W}>
              <Button
                size="sm"
                variant="minimal"
                tone="brass"
                fill
                className="min-w-0"
                active={busy?.token === s.scenario_id}
                title={`${s.scenario_id} — ${s.headline}. Expected to ${
                  outcomeVerb(s.expected_outcome)}.`}
                onClick={() => run(
                  s.scenario_id, scenarioLabel(s), () => api.demo.inject(s.scenario_id),
                )}
              >
                <span className="min-w-0 truncate">{scenarioLabel(s)}</span>
              </Button>
            </span>
          ) : (
            /* A real placeholder, not `null`. This is what holds the geometry steady between
               first paint and /api/demo/scenarios resolving; rendering nothing was why the
               container previously needed a hard-coded width to stop the bar reflowing. */
            <span key={`slot-${i}`} aria-hidden className={`h-[24px] ${SLOT_W}`} />
          )))}
        </div>

        <Divider vertical />

        <Button
          size="sm"
          variant="minimal"
          active={busy?.token === 'clock'}
          title="Advance the demonstration clock four days — wakes the dormant case"
          onClick={() => run('clock', 'Advance clock', () => api.demo.advanceClock(4))}
        >
          +4 days
        </Button>
        <Button
          size="sm"
          variant="minimal"
          disabled={!caseId}
          active={busy?.token === 'kill'}
          title="Cancel the in-flight runner for the open case"
          onClick={() => run('kill', 'Kill runner', () => api.demo.kill(caseId ?? undefined))}
        >
          Kill run
        </Button>
        <Button
          size="sm"
          variant="minimal"
          disabled={!caseId}
          active={busy?.token === 'resume'}
          title="Resume the open case from its last durable checkpoint"
          onClick={() => run('resume', 'Resume runner', () => api.demo.resume(caseId ?? undefined))}
        >
          Resume
        </Button>

        {/* Named only while something is actually running: a permanent "Idle" readout spends
            104px saying nothing for most of a take, and the sweep above the bar already carries
            the in-flight signal.

            `flex-[0_1_104px]` rather than a hard `w-[104px]`: it asks for 104px and keeps it
            wherever the bar has room — including the recording viewport, so nothing reflows
            there when a run starts — but yields it to the scenario buttons on a narrow screen
            instead of shoving three controls out of the column. */}
        <span className="ml-auto flex h-[18px] min-w-0 flex-[0_1_104px] items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-right text-mini text-[var(--color-brass-text)]">
            {busy?.label ?? ''}
          </span>
        </span>
      </div>
    </div>
  );
}

/* --- lane derivation ------------------------------------------------------ */

function deriveLanes(events: StreamEvent[], caseId: string | null): Record<string, LaneState> {
  const lanes: Record<string, LaneState> = {};
  for (const e of events) {
    const data = e.data as Record<string, unknown>;
    if (caseId && data.case_id && data.case_id !== caseId) continue;
    const agent = String(data.agent ?? '');
    if (!agent) continue;
    if (e.event === 'lane_started') lanes[agent] = { agent, status: 'running' };
    if (e.event === 'lane_failed') {
      // The backend writes a sentence here. Discarding it leaves a failed lane
      // with no stated reason, which is the one thing a degraded state owes.
      const why = typeof data.error === 'string' ? data.error : undefined;
      lanes[agent] = { agent, status: 'failed', error: why };
    }
    if (e.event === 'finding_added') {
      // Absent latency renders as an em-dash, never as a confident 0ms.
      const raw = data.latency_ms;
      const latencyMs = typeof raw === 'number' && Number.isFinite(raw) ? raw : undefined;
      lanes[agent] = { agent, status: 'done', latencyMs };
    }
  }
  return lanes;
}
