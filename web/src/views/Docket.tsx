import {
  useCallback, useEffect, useMemo, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent, type ReactNode,
} from 'react';
import {
  ArrowRight, Bot, ChevronRight, Database, Download, FolderOpen, History, Inbox, Link2,
  PlugZap, RefreshCw, ScrollText, Wrench,
} from 'lucide-react';
import { api } from '@/lib/api';
import type {
  AuditRecord, BankingDetails, CaseDetail, CaseSummary, Checkpoint,
  Decision, Effect, Finding, Payment, Rebuttal, Span,
} from '@/lib/types';
import {
  agentLabel, caseRef, clock, eventKindLabel, holdCountdown, humanize, money, ms,
  LOCAL_ZONE, LOCAL_ZONE_LONG, outcomeLabel, shortHash, signalLabel, stateLabel,
  stateLabelShort,
} from '@/lib/format';
import { useTenant } from '@/lib/tenant';
import { DataGrid, type Column } from '@/components/DataGrid';
import { DossierPanel } from '@/components/ThreatIntel';
import { PrecedentPanel } from './PrecedentPanel';
import {
  Button, CasePath, ConfidenceBar, Dot, FieldRow, Input, KeyValue, Latency, LoadBar, MonoId,
  NonIdealState, Money, OUTCOME_TONE, Panel, Pill, Region, SectionHeader,
  SkeletonBar, STATE_TONE,
  Tabs, Tag, Timestamp, TONE_RAIL, VERDICT_TONE,
} from '@/components/primitives';

/* ============================================================================
   DOCKET — the case file. Named for the file, not the log.

   This is the AUDIT surface: every claim on the Console must be traceable to a
   span, an excerpt, a checkpoint and a hash from here. The structure follows
   the reference record-home pattern: a two-row record header (title + record
   id, the stage path, a fixed grid of key/value detail fields) over a 30px tab
   strip, with a 380px case queue to its left (UI_SPEC §14).

   Nothing here invents data. Every field is a value the REST contract already
   returns; where a value can be absent it renders an em-dash rather than
   collapsing, so the layout never moves when the fetch lands (N4).

   THE SIX TABS SHARE ONE SHELL — LoadBar (2px, always present) → SectionHeader
   → scroll region — so switching tabs never moves the body by a pixel, and all
   six panels stay mounted once visited so a return visit never re-skeletons
   (§3: "a refetch never re-skeletons").
   ============================================================================ */

type Tab = 'reasoning' | 'evidence' | 'memory' | 'precedent' | 'durability' | 'audit';

/* Tabs name the operator's question, not the implementation property. Precedent sits
   beside Memory because the two are one faculty pointed at two things: memory remembers
   the attacker, precedent remembers what this organisation decided about one. */
const TABS: { id: Tab; label: string }[] = [
  { id: 'reasoning', label: 'Reasoning chain' },
  { id: 'evidence', label: 'Evidence chain' },
  { id: 'memory', label: 'Memory & threat intel' },
  { id: 'precedent', label: 'Precedent' },
  { id: 'durability', label: 'Crash safety' },
  { id: 'audit', label: 'Audit record' },
];

/** One reading measure for the whole surface. */
const MEASURE = 'max-w-[92ch]';

/** One gutter for the whole surface: 12px (§1 `--spacing-md`). */
const GUT = 'px-3';

const DASH = <span className="text-[var(--color-ink-faint)]">—</span>;

/* Every enum-to-prose map this surface needs now lives in `lib/format.ts`,
   beside STATE_LABELS, so Console/Docket/Registry/Posture cannot drift into
   four vocabularies for one backend value. `humanize` is the shared fallback
   for a value the backend adds later — it de-underscores, it never guesses. */

const PAYMENT_TONE = {
  scheduled: 'neutral',
  held: 'amber',
  released: 'verdigris',
  blocked: 'oxblood',
} as const;

/* --- view-local compositions ---------------------------------------------
   Compositions of sanctioned tokens, not re-implementations of an inventory
   component (§13). They exist so that the six tab shells and their section
   headers stay identical to each other. */

/**
 * An inline label/value pair. The label is the one sanctioned uppercase
 * treatment; the VALUE is content and therefore never renders in the chrome
 * ink ramp (§6: ink-faint is for micro-labels and column headers, never for
 * content), and numeric values are tabular with the slot pre-reserved.
 */
function Metric({
  label, value, numeric = true,
}: { label: string; value: ReactNode; numeric?: boolean }) {
  return (
    <span className="inline-flex shrink-0 items-baseline gap-1.5">
      <span className="label-micro">{label}</span>
      <span
        data-numeric={numeric ? '' : undefined}
        className={numeric
          ? 'min-w-[5ch] text-right font-mono tabular text-mini text-[var(--color-ink-dim)]'
          : 'text-xs text-[var(--color-ink)]'}
      >
        {value}
      </span>
    </span>
  );
}

/** Mounted panels stay mounted; only their visibility toggles (§3, N4). */
function TabPanel({
  id, active, children,
}: { id: Tab; active: boolean; children: ReactNode }) {
  return (
    <div
      role="tabpanel"
      id={`panel-${id}`}
      aria-labelledby={`tab-${id}`}
      hidden={!active}
      className={active ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}
    >
      {children}
    </div>
  );
}

/* --- object rendering ----------------------------------------------------
   Two payload columns in this file carry an object whose shape the contract
   does not pin down. An audit tool does not print `{"payment_id":"PAY-0031"}`
   into a 24px grid cell: we name the first fields, count the rest, and keep
   the full value in `title`. */

const entriesOf = (value: unknown): [string, unknown][] =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? Object.entries(value as Record<string, unknown>)
    : [];

const scalarText = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === 'object') return `${Object.keys(value).length} fields`;
  return String(value);
};

function ObjectSummary({ value, keys = 2 }: { value: unknown; keys?: number }) {
  const entries = entriesOf(value);
  if (entries.length === 0) return DASH;
  const shown = entries.slice(0, keys);
  const rest = entries.length - shown.length;
  return (
    <span className="flex min-w-0 items-baseline gap-3 text-mini">
      {shown.map(([k, v]) => (
        <span key={k} className="min-w-0 truncate">
          <span className="text-[var(--color-ink-dim)]">{k}</span>{' '}
          <span className="font-mono text-[var(--color-ink)]">{scalarText(v)}</span>
        </span>
      ))}
      {rest > 0 && (
        <span
          data-numeric=""
          className="shrink-0 font-mono tabular text-[var(--color-ink-dim)]"
        >
          +{rest}
        </span>
      )}
    </span>
  );
}

export function Docket({
  selectedCase, onSelectCase,
}: { selectedCase: string | null; onSelectCase: (id: string) => void }) {
  const { tenantId, active, ready, epoch } = useTenant();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [casesLoading, setCasesLoading] = useState(true);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  const [tab, setTab] = useState<Tab>('reasoning');
  const [query, setQuery] = useState('');
  // Bumped by the header's refresh action; every panel takes it as a dependency.
  const [nonce, setNonce] = useState(0);
  // A panel mounts on its first visit and then stays mounted, so leaving and
  // returning to a tab never re-runs its fetch and never re-skeletons (§3).
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set<Tab>(['reasoning']));

  useEffect(() => {
    setVisited((prev) => (prev.has(tab) ? prev : new Set(prev).add(tab)));
  }, [tab]);

  useEffect(() => {
    if (!ready) return undefined;
    let live = true;
    void api.cases(tenantId ?? undefined)
      .then((rows) => { if (live) setCases(rows); })
      .catch(() => { if (live) setCases([]); })
      .finally(() => { if (live) setCasesLoading(false); });
    return () => { live = false; };
  }, [nonce, ready, tenantId, epoch]);

  // A new case must not show the previous case's record for a frame. A REFRESH
  // of the same case must not blank it — which is why this is keyed on the id
  // alone and the fetch below is not.
  useEffect(() => {
    setDetail(null);
    setDetailFailed(false);
  }, [selectedCase]);

  useEffect(() => {
    if (!selectedCase) return;
    let live = true;
    void api.case(selectedCase)
      .then((d) => { if (live) { setDetail(d); setDetailFailed(false); } })
      .catch(() => { if (live) { setDetail(null); setDetailFailed(true); } });
    return () => { live = false; };
  }, [selectedCase, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return cases;
    return cases.filter((c) =>
      c.vendor_name.toLowerCase().includes(q)
      || c.case_id.toLowerCase().includes(q)
      || c.state.includes(q));
  }, [cases, query]);

  /* The premise of the product is a deadline. The queue is 380px and cannot
     carry a sixth column, so the pressure is stated once, in the pane footer,
     where it is always visible rather than hover-only (N3). */
  const soonest = useMemo(() => {
    if (filtered.length === 0) return null;
    return filtered.reduce(
      (min, c) => Math.min(min, c.hold_remaining_hours),
      Number.POSITIVE_INFINITY,
    );
  }, [filtered]);

  /* THE CASE QUEUE. This column set is shared, value for value, with the queue
     on Console — same widths, same renderers, same vocabulary — because it is
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
      key: 'case',
      header: 'Case',
      width: '72px',
      sortable: true,
      value: (r) => r.case_id,
      title: (r) => r.case_id,
      render: (r) => <MonoId>{caseRef(r.case_id)}</MonoId>,
    },
    {
      key: 'vendor',
      header: 'Vendor',
      sortable: true,
      value: (r) => r.vendor_name,
      title: (r) => r.vendor_name,
      render: (r) => (
        <span className="block truncate text-[var(--color-ink)]">{r.vendor_name}</span>
      ),
    },
    {
      key: 'exposure',
      header: 'Exposure',
      width: '84px',
      numeric: true,
      sortable: true,
      value: (r) => Number(r.exposure_amount),
      title: (r) => money(r.exposure_amount, true),
      render: (r) => (
        <span className="text-[var(--color-ink)]">{money(r.exposure_amount)}</span>
      ),
    },
    {
      key: 'state',
      header: 'State',
      width: '132px',
      sortable: true,
      value: (r) => r.state,
      title: (r) => `${stateLabel(r.state)} — hold ${holdCountdown(r.hold_remaining_hours)}`,
      render: (r) => (
        <Pill tone={STATE_TONE[r.state]} dot minWidth={68}>
          {stateLabelShort(r.state)}
        </Pill>
      ),
    },
  ];

  return (
    <div className="grid h-full grid-cols-[380px_minmax(0,1fr)]">
      <Panel
        title="Case queue"
        label="Case queue"
        className="rule-r"
        actions={
          <div className="w-[136px]">
            <Input
              size="sm"
              value={query}
              onChange={setQuery}
              placeholder="Filter cases"
              ariaLabel="Filter cases"
            />
          </div>
        }
        footer={
          <>
            <span className="label-micro">Soonest hold expiry</span>
            <span className="ml-auto">
              <span
                data-numeric=""
                className="font-mono tabular text-mini text-[var(--color-ink-dim)]"
              >
                {casesLoading || soonest === null || !Number.isFinite(soonest)
                  ? '—'
                  : holdCountdown(soonest)}
              </span>
            </span>
          </>
        }
      >
        <DataGrid
          label="Case queue"
          columns={columns}
          rows={filtered}
          rowKey={(r) => r.case_id}
          onSelect={(r) => onSelectCase(r.case_id)}
          selectedKey={selectedCase}
          loading={casesLoading}
          /* 1080p, 100px of fixed chrome, a 30px pane header, a 30px column
             header and a 26px footer leave ~890px of body: 28 rows at 28px. */
          skeletonRows={28}
          defaultSort={{ key: 'exposure', dir: 'desc' }}
          /* Redundant encoding: severity is colour AND a 2px position rail. */
          rowRail={(r) => TONE_RAIL[STATE_TONE[r.state]]}
          empty={
            <NonIdealState
              visual={<Inbox aria-hidden size={22} strokeWidth={1.75} />}
              title={
                query
                  ? 'No case matches this filter'
                  : active ? `No cases at ${active.display_name}` : 'No cases yet'
              }
              description={
                query
                  ? 'Clear the filter to see the full docket.'
                  : 'The docket is one district at a time. Open a case from the Console; cases persist across a restart.'
              }
            />
          }
        />
      </Panel>

      {selectedCase ? (
        <div className="flex min-h-0 flex-col">
          <CaseHeader detail={detail} caseId={selectedCase} onRefresh={refresh} />
          <Tabs tabs={TABS} value={tab} onChange={setTab} label="Case file sections" />
          {detailFailed ? (
            <div
              role="tabpanel"
              id={`panel-${tab}`}
              aria-labelledby={`tab-${tab}`}
              className="flex min-h-0 flex-1 flex-col"
            >
              {/* An error is not an empty state. Amber + a visual + a retry,
                  identical to the failure states on Console, Registry and
                  Posture, so "nothing happened" never reads as "nothing here". */}
              <NonIdealState
                tone="amber"
                visual={<PlugZap aria-hidden size={22} strokeWidth={1.75} />}
                title="Case file unavailable"
                description="The record did not load. Nothing on this tab is stale — there is
                  simply nothing to show until the service answers."
                action={
                  <Button size="sm" variant="default" onClick={refresh}>Retry</Button>
                }
              />
            </div>
          ) : (
            <>
              <TabPanel id="reasoning" active={tab === 'reasoning'}>
                {visited.has('reasoning') && (
                  <ReasoningChain caseId={selectedCase} nonce={nonce} />
                )}
              </TabPanel>
              <TabPanel id="evidence" active={tab === 'evidence'}>
                {visited.has('evidence') && <EvidenceChain detail={detail} />}
              </TabPanel>
              <TabPanel id="memory" active={tab === 'memory'}>
                {visited.has('memory') && (
                  <MemoryPanel caseId={selectedCase} nonce={nonce} tenantId={tenantId} />
                )}
              </TabPanel>
              <TabPanel id="precedent" active={tab === 'precedent'}>
                {visited.has('precedent') && (
                  <PrecedentPanel
                    caseId={selectedCase}
                    detail={detail}
                    nonce={nonce}
                    tenantId={tenantId}
                    onResolved={refresh}
                  />
                )}
              </TabPanel>
              <TabPanel id="durability" active={tab === 'durability'}>
                {visited.has('durability') && (
                  <DurabilityPanel caseId={selectedCase} nonce={nonce} />
                )}
              </TabPanel>
              <TabPanel id="audit" active={tab === 'audit'}>
                {visited.has('audit') && <AuditPanel caseId={selectedCase} nonce={nonce} />}
              </TabPanel>
            </>
          )}
        </div>
      ) : (
        <NonIdealState
          visual={<FolderOpen aria-hidden size={22} strokeWidth={1.75} />}
          title="Select a case"
          description="Pick a case in the queue to open its file."
        />
      )}
    </div>
  );
}

/* --- the record header ----------------------------------------------------
   Three bands, per the reference record-home pattern: an eyebrow + entity
   title + record id with the actions right-aligned, the stage path, then a
   GRID (never a wrap) of label-above-value detail fields. Every band renders
   at a fixed height whether or not the record has arrived, so the header
   never jumps and never reflows as the window narrows. */

function CaseHeader({
  detail, caseId, onRefresh,
}: { detail: CaseDetail | null; caseId: string; onRefresh: () => void }) {
  const outcome = detail?.outcome ?? null;
  const current = detail?.vendor?.banking ?? null;
  const proposed = detail?.request?.proposed_banking ?? null;

  return (
    <header className={`shrink-0 rule-b ${GUT}`}>
      <div className="flex items-start gap-3 pt-3">
        <div className="min-w-0 flex-1">
          <div className="label-micro">Case file</div>
          <div className="flex min-w-0 items-baseline gap-2">
            <h1
              title={detail?.vendor?.legal_name ?? undefined}
              className="min-w-0 truncate font-display text-xl leading-[26px] text-[var(--color-ink)]"
            >
              {detail?.vendor?.legal_name ?? 'Unresolved vendor'}
            </h1>
            {/* Always present, so the header's node count does not change when
                the record lands. */}
            <span className="min-w-0 truncate text-xs text-[var(--color-ink-dim)]">
              {detail?.vendor?.dba_name ? `dba ${detail.vendor.dba_name}` : ''}
            </span>
            <span className="shrink-0">
              <MonoId copyable>{caseId}</MonoId>
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-3">
          <Button
            size="sm"
            variant="minimal"
            onClick={onRefresh}
            title="Refresh case file"
            icon={<RefreshCw size={12} strokeWidth={1.75} />}
          />
        </div>
      </div>

      {/* The stage machine. 30px, reserved whether or not the record has
          landed; a check glyph on completed stages carries the encoding
          through grayscale. */}
      <div className="mt-3 h-[30px]">
        {detail && <CasePath state={detail.state} />}
      </div>

      {/* Declared columns, not flex-wrap: the strip cannot grow a row when the
          window narrows or when a value arrives. */}
      <div
        className="grid grid-cols-3 gap-x-6 gap-y-2 py-3
          2xl:grid-cols-[1fr_1.2fr_1.4fr_1fr_1fr]"
      >
        <HeaderField label="Exposure">
          {detail ? <Money value={detail.exposure_amount} size="sm" cents /> : DASH}
        </HeaderField>
        <HeaderField label="Outcome">
          {outcome ? <Pill tone={OUTCOME_TONE[outcome]}>{outcomeLabel(outcome)}</Pill> : DASH}
        </HeaderField>
        <HeaderField label="Banking change">
          {current && proposed ? (
            <>
              <MonoId>{`••${current.account_last4}`}</MonoId>
              <ArrowRight
                aria-hidden
                size={11}
                strokeWidth={1.75}
                className="shrink-0 text-[var(--color-ink-faint)]"
              />
              <MonoId>{`••${proposed.account_last4}`}</MonoId>
            </>
          ) : DASH}
        </HeaderField>
        <HeaderField label={`Opened (${LOCAL_ZONE})`}>
          {detail ? <Timestamp>{clock(detail.opened_at)}</Timestamp> : DASH}
        </HeaderField>
        <HeaderField label={`Hold expires (${LOCAL_ZONE})`}>
          {detail ? <Timestamp>{clock(detail.deadline_at)}</Timestamp> : DASH}
        </HeaderField>
      </div>
    </header>
  );
}

/** A header cell whose value line is exactly 18px tall — the height of a pill —
    so an arriving value can never change the strip's height. */
function HeaderField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <KeyValue label={label}>
      <span className="inline-flex h-[18px] max-w-full items-center gap-1.5">{children}</span>
    </KeyValue>
  );
}

/* ==========================================================================
   REASONING CHAIN — the span tree.

   Tree conventions from the reference system: one 30px node per span, a
   chevron only where there are children (leaves keep the same 18px gutter so
   labels stay on a single left edge), a 1px indentation guide per ancestor
   level, and the wall-clock pinned to the right.

   The tree is a REAL tree: roving tabIndex (exactly one node is tabbable),
   Up/Down to move, Left to collapse or step to the parent, Right to expand or
   step to the first child, Home/End to the ends. A 30px row cannot carry a
   2px outline offset without overlapping its neighbour, so focus is the inset
   brass ring (§9).
   ========================================================================== */

const INDENT = 16;
const GUTTER = 12;

/** Depth and bar width of the reserve tree. Shaped like a real trace so the
    transition to data moves nothing. */
const SKELETON_TREE: [number, string][] = [
  [0, '32%'], [1, '24%'], [2, '18%'], [2, '20%'], [1, '26%'], [2, '16%'],
  [1, '22%'], [2, '19%'], [2, '17%'], [1, '25%'], [1, '21%'], [0, '28%'],
];

interface FlatSpan {
  span: Span;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
}

const attrText = (attrs: Record<string, unknown>, key: string): string | null => {
  const v = attrs[key];
  if (v === undefined || v === null || v === '') return null;
  return String(v);
};

const attrNumber = (attrs: Record<string, unknown>, key: string): number | null => {
  const v = attrs[key];
  if (v === undefined || v === null || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

function ReasoningChain({ caseId, nonce }: { caseId: string; nonce: number }) {
  const [spans, setSpans] = useState<Span[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [focusId, setFocusId] = useState<string | null>(null);
  const treeRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    void api.trace(caseId)
      .then((r) => { if (live) setSpans(r.spans); })
      .catch(() => { if (live) setSpans([]); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [caseId, nonce]);

  // A refetch keeps the previous tree on screen; only the first load reserves.
  const first = loading && spans === null;
  const list = useMemo(() => spans ?? [], [spans]);

  const byParent = useMemo(() => {
    const map = new Map<string | null, Span[]>();
    for (const s of list) {
      const kids = map.get(s.parent_id) ?? [];
      kids.push(s);
      map.set(s.parent_id, kids);
    }
    return map;
  }, [list]);

  const rows = useMemo(() => {
    const out: FlatSpan[] = [];
    const walk = (parent: string | null, depth: number) => {
      for (const span of byParent.get(parent) ?? []) {
        const kids = byParent.get(span.span_id) ?? [];
        const expanded = !collapsed.has(span.span_id);
        out.push({ span, depth, hasChildren: kids.length > 0, expanded });
        if (kids.length > 0 && expanded) walk(span.span_id, depth + 1);
      }
    };
    walk(null, 0);
    return out;
  }, [byParent, collapsed]);

  const longest = useMemo(
    () => list.reduce((max, s) => Math.max(max, s.duration_ms), 1),
    [list],
  );

  const toggle = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const ids = useMemo(() => rows.map((r) => r.span.span_id), [rows]);
  const tabId = focusId !== null && ids.includes(focusId) ? focusId : ids[0] ?? null;

  const focusAt = useCallback((index: number) => {
    const clamped = Math.max(0, Math.min(ids.length - 1, index));
    const id = ids[clamped];
    if (id === undefined) return;
    setFocusId(id);
    treeRef.current
      ?.querySelector<HTMLDivElement>(`[data-span-id="${CSS.escape(id)}"]`)
      ?.focus();
  }, [ids]);

  const onRowKeyDown = useCallback((
    e: ReactKeyboardEvent<HTMLDivElement>, row: FlatSpan, index: number,
  ) => {
    switch (e.key) {
      case 'ArrowDown': case 'j': e.preventDefault(); focusAt(index + 1); break;
      case 'ArrowUp': case 'k': e.preventDefault(); focusAt(index - 1); break;
      case 'Home': e.preventDefault(); focusAt(0); break;
      case 'End': e.preventDefault(); focusAt(ids.length - 1); break;
      case 'ArrowRight':
        e.preventDefault();
        if (row.hasChildren && !row.expanded) toggle(row.span.span_id);
        else if (row.hasChildren) focusAt(index + 1);
        break;
      case 'ArrowLeft':
        e.preventDefault();
        if (row.hasChildren && row.expanded) { toggle(row.span.span_id); break; }
        for (let i = index - 1; i >= 0; i -= 1) {
          const above = rows[i];
          if (above && above.depth < row.depth) { focusAt(i); break; }
        }
        break;
      case 'Enter': case ' ':
        if (row.hasChildren) { e.preventDefault(); toggle(row.span.span_id); }
        break;
      default: break;
    }
  }, [focusAt, ids.length, rows, toggle]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <LoadBar loading={loading} />
      <SectionHeader
        title="Reasoning chain"
        actions={
          <span className="flex items-baseline gap-3">
            <Metric label="spans" value={first ? '—' : list.length} />
            <Metric label="longest" value={first ? '—' : ms(longest)} />
          </span>
        }
      />
      <Region label="Reasoning chain">
        {first ? (
          <div className="py-1">
            {SKELETON_TREE.map(([depth, width], i) => (
              <div
                key={i}
                className="flex h-[30px] items-center gap-2 pr-3"
                style={{ paddingLeft: `${GUTTER + depth * INDENT}px` }}
              >
                <span aria-hidden className="h-[18px] w-[18px] shrink-0" />
                <SkeletonBar width={width} />
                <span className="ml-auto"><SkeletonBar width="64px" /></span>
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <NonIdealState
            visual={<Bot aria-hidden size={22} strokeWidth={1.75} />}
            title="No spans recorded"
            description="Spans are emitted as the fleet runs. Run a scenario from the Console."
          />
        ) : (
          <div ref={treeRef} role="tree" aria-label="Reasoning chain" className="py-1">
            {rows.map((row, index) => (
              <SpanRow
                key={row.span.span_id}
                row={row}
                index={index}
                longest={longest}
                tabbable={row.span.span_id === tabId}
                onToggle={toggle}
                onFocusRow={setFocusId}
                onKeyDown={onRowKeyDown}
              />
            ))}
          </div>
        )}
      </Region>
    </div>
  );
}

const KIND_ICON = {
  case: FolderOpen,
  agent: Bot,
  tool: Wrench,
} as const;

function SpanRow({
  row, index, longest, tabbable, onToggle, onFocusRow, onKeyDown,
}: {
  row: FlatSpan;
  index: number;
  longest: number;
  tabbable: boolean;
  onToggle: (id: string) => void;
  onFocusRow: (id: string) => void;
  onKeyDown: (e: ReactKeyboardEvent<HTMLDivElement>, row: FlatSpan, index: number) => void;
}) {
  const { span, depth, hasChildren, expanded } = row;
  const attrs = span.attributes;
  const verdict = attrText(attrs, 'interdict.verdict');
  const tone = verdict && verdict in VERDICT_TONE
    ? VERDICT_TONE[verdict as keyof typeof VERDICT_TONE]
    : 'neutral';
  const confidence = attrNumber(attrs, 'interdict.confidence');
  const evidenceCount = attrNumber(attrs, 'interdict.evidence_count');
  const model = attrText(attrs, 'interdict.model');
  const Icon = KIND_ICON[span.kind];
  const share = Math.max(0.02, Math.min(1, span.duration_ms / longest));

  return (
    <div
      role="treeitem"
      data-span-id={span.span_id}
      aria-level={depth + 1}
      aria-expanded={hasChildren ? expanded : undefined}
      tabIndex={tabbable ? 0 : -1}
      onFocus={() => onFocusRow(span.span_id)}
      onKeyDown={(e) => onKeyDown(e, row, index)}
      className="relative flex h-[30px] items-center gap-2 pr-3 outline-none
        transition-colors duration-100 ease-[var(--ease-ui)] hover:bg-[var(--color-raised)]
        focus-visible:shadow-[var(--shadow-focus-inset)]"
      style={{ paddingLeft: `${GUTTER + depth * INDENT}px` }}
    >
      {/* Indentation guides: one hairline per ancestor level, aligned to the
          chevron centre of that level. */}
      {Array.from({ length: depth }, (_, i) => (
        <span
          key={i}
          aria-hidden
          className="absolute top-0 bottom-0 w-px bg-[var(--color-rule-muted)]"
          style={{ left: `${GUTTER + i * INDENT + 9}px` }}
        />
      ))}

      {hasChildren ? (
        <button
          type="button"
          tabIndex={-1}
          onClick={() => onToggle(span.span_id)}
          title={expanded ? `Collapse ${span.name}` : `Expand ${span.name}`}
          aria-label={expanded ? `Collapse ${span.name}` : `Expand ${span.name}`}
          className="z-[1] inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center
            rounded-[var(--radius-input)] text-[var(--color-ink-dim)]
            transition-colors duration-100 hover:bg-[var(--color-fill-neutral-strong)]
            hover:text-[var(--color-ink)]"
        >
          <ChevronRight
            size={12}
            strokeWidth={1.75}
            className="transition-transform duration-200 ease-[var(--ease-ui)]"
            style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}
          />
        </button>
      ) : (
        <span aria-hidden className="h-[18px] w-[18px] shrink-0" />
      )}

      <Icon
        aria-hidden
        size={12}
        strokeWidth={1.75}
        className="z-[1] shrink-0 text-[var(--color-ink-faint)]"
      />

      <span
        title={span.name}
        className={`min-w-0 flex-1 truncate font-mono text-mini ${
          span.kind === 'tool' ? 'text-[var(--color-ink-dim)]' : 'text-[var(--color-ink)]'
        }`}
      >
        {span.name}
      </span>

      {verdict ? <Pill tone={tone}>{verdict}</Pill> : null}

      {/* The meter is the confidence meter. There is exactly one 3px x 64px bar
          on this row and it always means confidence (§12). */}
      {confidence !== null ? <ConfidenceBar value={confidence} /> : null}

      {evidenceCount !== null ? <Metric label="evidence" value={evidenceCount} /> : null}

      <span className="flex shrink-0 items-center gap-3">
        <span
          title={model ?? undefined}
          className="w-[120px] truncate text-right font-mono text-mini text-[var(--color-ink-dim)]"
        >
          {span.kind === 'agent' ? (model ?? '—') : ''}
        </span>
        {/* Where the wall-clock went. A VERTICAL tick, deliberately not a
            second 3px x 64px bar: two identical meters on one row cannot be
            told apart on a muted recording. Neutral by design — a duration is
            not a severity, so it never carries a semantic hue. */}
        <span
          aria-hidden
          className="relative block h-[18px] w-[2px] shrink-0 bg-[var(--color-rule)]"
        >
          <span
            className="absolute bottom-0 left-0 w-full bg-[var(--color-rule-strong)]"
            style={{ height: `${share * 100}%` }}
          />
        </span>
        <Latency ms={span.duration_ms} />
      </span>
    </div>
  );
}

/* ==========================================================================
   EVIDENCE CHAIN — what was requested, what is at stake, what was found.

   The agent's prose and the source it cites are two different kinds of text
   and are typeset as such: reasoning is 14px/1.5 interface prose, an excerpt
   is monospace inside a recessed well one ramp step ABOVE the field it sits
   on, so the recess is visible after H.264. A reader must never have to guess
   which words the model wrote and which words it found.
   ========================================================================== */

function EvidenceChain({ detail }: { detail: CaseDetail | null }) {
  const challenge = detail?.challenge ?? null;
  const rebuttalFor = useMemo(() => {
    const map = new Map<string, Rebuttal>();
    for (const r of challenge?.rebuttals ?? []) map.set(r.finding_id, r);
    return map;
  }, [challenge]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <LoadBar loading={!detail} />
      <SectionHeader
        title="Evidence chain"
        actions={
          <Metric
            label="excerpts"
            value={detail
              ? detail.findings.reduce((n, f) => n + f.evidence.length, 0)
              : '—'}
          />
        }
      />
      <Region label="Evidence chain">
        {!detail ? (
          <div aria-hidden>
            {[0, 1, 2].map((i) => (
              <div key={i} className={`flex flex-col gap-2 rule-b py-3 ${GUT}`}>
                <SkeletonBar width="24%" />
                <SkeletonBar width="72%" />
                <SkeletonBar width="61%" />
              </div>
            ))}
          </div>
        ) : (
          <>
            <RequestBlock detail={detail} />
            <HeldPayments payments={detail.held_payments} />

            <SectionHeader
              title="Findings"
              actions={<Metric label="recorded" value={detail.findings.length} />}
            />
            {detail.findings.length === 0 ? (
              <p className={`py-3 text-xs leading-4 text-[var(--color-ink-dim)] ${GUT}`}>
                No findings yet. Each lane appends one as it completes.
              </p>
            ) : (
              detail.findings.map((f) => (
                <FindingBlock
                  key={f.finding_id}
                  finding={f}
                  rebuttal={rebuttalFor.get(f.finding_id)}
                />
              ))
            )}

            <SectionHeader
              title="Adversarial review"
              actions={
                <Tag>
                  {challenge
                    ? (challenge.survived ? 'Findings survived' : 'Findings rebutted')
                    : 'Not yet run'}
                </Tag>
              }
            />
            <div className={`flex flex-col gap-3 py-3 ${GUT}`}>
              <div className="flex flex-col gap-[2px]">
                <span className="label-micro">Strongest legitimate explanation</span>
                <p className={`prose-agent ${MEASURE}`}>
                  {challenge ? challenge.strongest_legitimate_explanation : '—'}
                </p>
              </div>
              <div className="flex flex-col gap-[2px]">
                <span className="label-micro">Reviewer reasoning</span>
                <p className={`prose-agent ${MEASURE}`}>{challenge ? challenge.reasoning : '—'}</p>
              </div>
            </div>

            <DecisionBlock decision={detail.decision} />
          </>
        )}
      </Region>
    </div>
  );
}

/* --- the thing being adjudicated -----------------------------------------
   The contract carries the change request itself — the artifact, the channel,
   the claimed reason, and the account it proposes. Without it a viewer can see
   THAT the fleet reasoned and not WHAT ABOUT. */

function RequestBlock({ detail }: { detail: CaseDetail }) {
  const request = detail.request;
  const current = detail.vendor?.banking ?? null;

  return (
    <>
      <SectionHeader
        title="The change request"
        actions={
          request
            ? <Metric label="channel" value={humanize(request.channel)} numeric={false} />
            : DASH
        }
      />
      <div className={`flex flex-col gap-3 py-3 ${GUT}`}>
        <dl className={MEASURE}>
          <FieldRow label="Request id">
            {request ? <MonoId truncate>{request.request_id}</MonoId> : DASH}
          </FieldRow>
          <FieldRow label={`Received (${LOCAL_ZONE})`}>
            {request ? <Timestamp>{clock(request.received_at)}</Timestamp> : DASH}
          </FieldRow>
          <FieldRow label="Claimed reason">
            {request?.claimed_reason ? request.claimed_reason : DASH}
          </FieldRow>
        </dl>

        <BankingCompare current={current} proposed={request?.proposed_banking ?? null} />

        {/* The artifact exactly as it arrived. Quoted material is set as
            quoted material: recessed, monospace, attributed. */}
        <figure
          className={`rounded-[var(--radius-ctl)] bg-[var(--color-surface)] px-3 py-2
            shadow-[var(--shadow-well)] ${MEASURE}`}
        >
          <figcaption className="flex items-baseline gap-2">
            <span className="label-brass truncate">Artifact as received</span>
            {request && (
              <span className="text-mini text-[var(--color-ink-dim)]">
                {humanize(request.channel)}
              </span>
            )}
          </figcaption>
          <blockquote
            className="mt-1 whitespace-pre-wrap font-mono text-mini leading-[15px]
              text-[var(--color-ink)]"
          >
            {request ? request.raw_artifact : '—'}
          </blockquote>
        </figure>

        <div className={MEASURE}>
          <span className="label-micro">Artifact metadata</span>
          <dl className="mt-1">
            {entriesOf(request?.artifact_metadata).map(([k, v]) => (
              <FieldRow key={k} label={humanize(k)}>
                <span className="font-mono text-mini text-[var(--color-ink)]">
                  {scalarText(v)}
                </span>
              </FieldRow>
            ))}
            {entriesOf(request?.artifact_metadata).length === 0 && (
              <FieldRow label="Metadata">{DASH}</FieldRow>
            )}
          </dl>
        </div>
      </div>
    </>
  );
}

/**
 * The account of record beside the account being proposed — the comparison the
 * whole case exists to make. A changed field is marked with a text token, not
 * a colour: amber and oxblood mean held and stopped, never "different".
 */
function BankingCompare({
  current, proposed,
}: { current: BankingDetails | null; proposed: BankingDetails | null }) {
  const rows: { label: string; read: (b: BankingDetails) => string; mono?: boolean }[] = [
    { label: 'Account name', read: (b) => b.account_name },
    { label: 'Account', read: (b) => `••${b.account_last4}`, mono: true },
    { label: 'Routing', read: (b) => `••${b.routing_last4}`, mono: true },
    { label: 'Bank', read: (b) => b.bank_name },
    { label: 'Country', read: (b) => b.bank_country, mono: true },
  ];

  return (
    <div className={MEASURE}>
      <div className="grid grid-cols-[132px_minmax(0,1fr)_minmax(0,1fr)] items-baseline gap-3 rule-b pb-[6px]">
        <span className="label-micro">Banking</span>
        <span className="label-micro truncate">Account of record</span>
        <span className="label-micro flex items-center gap-1.5 truncate">
          <ArrowRight aria-hidden size={10} strokeWidth={1.75} className="shrink-0" />
          Proposed in this request
        </span>
      </div>
      {rows.map(({ label, read, mono }) => {
        const a = current ? read(current) : null;
        const b = proposed ? read(proposed) : null;
        const changed = a !== null && b !== null && a !== b;
        return (
          <div
            key={label}
            className="grid grid-cols-[132px_minmax(0,1fr)_minmax(0,1fr)] items-baseline gap-3 py-[6px]"
          >
            <span className="label-micro">{label}</span>
            <span
              className={`min-w-0 truncate text-xs text-[var(--color-ink-dim)] ${
                mono ? 'font-mono tabular' : ''
              }`}
            >
              {a ?? '—'}
            </span>
            <span className="flex min-w-0 items-baseline gap-2">
              <span
                className={`min-w-0 truncate text-xs text-[var(--color-ink)] ${
                  mono ? 'font-mono tabular' : ''
                }`}
              >
                {b ?? '—'}
              </span>
              {changed && <Tag>changed</Tag>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The money actually stopped: one row per payment, not a count. */
function HeldPayments({ payments }: { payments: Payment[] }) {
  const columns: Column<Payment>[] = [
    {
      key: 'payment', header: 'Payment', width: '132px',
      sortable: true, value: (r) => r.payment_id,
      title: (r) => r.payment_id,
      render: (r) => <MonoId>{r.payment_id}</MonoId>,
    },
    {
      key: 'invoice', header: 'Invoice',
      sortable: true, value: (r) => r.invoice_id ?? '',
      title: (r) => r.invoice_id ?? '',
      render: (r) => (r.invoice_id ? <MonoId dim>{r.invoice_id}</MonoId> : DASH),
    },
    {
      key: 'status', header: 'Status', width: '104px',
      sortable: true, value: (r) => r.status,
      render: (r) => (
        <Pill tone={PAYMENT_TONE[r.status]} minWidth={68}>{humanize(r.status)}</Pill>
      ),
    },
    {
      key: 'scheduled', header: `Scheduled (${LOCAL_ZONE})`, width: '132px',
      headerTitle: `Local time — ${LOCAL_ZONE_LONG}`,
      sortable: true, value: (r) => r.scheduled_for,
      render: (r) => <Timestamp>{clock(r.scheduled_for)}</Timestamp>,
    },
    {
      key: 'amount', header: 'Amount', width: '132px', numeric: true,
      sortable: true, value: (r) => Number(r.amount),
      render: (r) => money(r.amount, true),
    },
  ];

  return (
    <>
      <SectionHeader
        title="Payments held"
        actions={<Metric label="held" value={payments.length} />}
      />
      <div className="py-2">
        <DataGrid
          label="Payments held by this case"
          density="dense"
          columns={columns}
          rows={payments}
          rowKey={(r) => r.payment_id}
          empty={
            <p className={`py-3 text-xs leading-4 text-[var(--color-ink-dim)] ${GUT}`}>
              No payment is being held by this case.
            </p>
          }
        />
      </div>
    </>
  );
}

function FindingBlock({
  finding: f, rebuttal,
}: { finding: Finding; rebuttal: Rebuttal | undefined }) {
  const tone = VERDICT_TONE[f.verdict];
  return (
    <article className={`rule-b py-3 ${GUT} ${TONE_RAIL[tone]}`}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">
          {agentLabel(f.agent)}
        </h3>
        <MonoId dim>{`v${f.agent_version}`}</MonoId>
        <Pill tone={tone}>{humanize(f.verdict)}</Pill>
        <Metric label="signal" value={signalLabel(f.signal)} numeric={false} />
        {/* Pinned to brass: a scalar meter never wears a severity hue (§7).
            The verdict is already carried by the pill beside it. */}
        <ConfidenceBar value={f.confidence} />
        <span className="ml-auto flex items-center gap-2">
          <span className="label-micro">latency</span>
          <Latency ms={f.latency_ms} />
        </span>
      </header>

      <p className={`prose-agent mt-1.5 ${MEASURE}`}>{f.reasoning}</p>

      {/* The literal observed value, not a summary. */}
      {f.evidence.length > 0 && (
        <div className={`mt-2 flex flex-col gap-2 ${MEASURE}`}>
          <span className="label-micro">Evidence — verbatim</span>
          {f.evidence.map((e, i) => (
            <figure
              key={`${f.finding_id}-${i}`}
              className="rounded-[var(--radius-ctl)] bg-[var(--color-surface)] px-3 py-2
                shadow-[var(--shadow-well)]"
            >
              <figcaption className="flex items-baseline gap-2">
                <span className="label-brass truncate">{e.source}</span>
                <MonoId dim>{e.locator}</MonoId>
              </figcaption>
              <blockquote
                className="mt-1 whitespace-pre-wrap font-mono text-mini leading-[15px]
                  text-[var(--color-ink)]"
              >
                {`“${e.excerpt}”`}
              </blockquote>
            </figure>
          ))}
        </div>
      )}

      {rebuttal && (
        <div className={`mt-2 rule-t pt-2 ${MEASURE}`}>
          <div className="flex items-baseline gap-2">
            <span className="label-brass">Rebuttal</span>
            <Tag tone={rebuttal.succeeds ? 'verdigris' : 'neutral'} minWidth={68}>
              {rebuttal.succeeds ? 'Upheld' : 'Defeated'}
            </Tag>
          </div>
          {/* Identical to the Balance steelman list on Console: a defeated
              argument is struck in NEUTRAL ink. `.struck` is the amber
              guardrail strike and means a neutralized injection, which is a
              different fact. One concept, one rendering, on both surfaces. */}
          <p
            className={`mt-[2px] text-xs leading-4 ${
              rebuttal.succeeds
                ? 'text-[var(--color-ink-dim)]'
                : 'text-[var(--color-ink-dim)] line-through decoration-[var(--color-ink-faint)]'
            }`}
          >
            {rebuttal.argument}
          </p>
        </div>
      )}
    </article>
  );
}

/** The decision itself: who decided, on what reasoning, over what dissent. */
function DecisionBlock({ decision }: { decision: Decision | null }) {
  return (
    <>
      <SectionHeader
        title="Decision"
        actions={
          decision
            ? <Pill tone={OUTCOME_TONE[decision.outcome]}>{outcomeLabel(decision.outcome)}</Pill>
            : <Tag>Not yet decided</Tag>
        }
      />
      <div className={`py-3 ${GUT}`}>
        <dl className={MEASURE}>
          <FieldRow label="Decided by">
            {decision ? humanize(decision.decided_by) : DASH}
          </FieldRow>
          <FieldRow label="Human reviewer">
            {decision?.human_reviewer ? decision.human_reviewer : DASH}
          </FieldRow>
          <FieldRow label={`Decided (${LOCAL_ZONE})`}>
            {decision ? <Timestamp>{clock(decision.decided_at)}</Timestamp> : DASH}
          </FieldRow>
          <FieldRow label="Confidence">
            {decision ? <ConfidenceBar value={decision.confidence} /> : DASH}
          </FieldRow>
          <FieldRow label="Dissenting signals">
            {decision && decision.dissenting_findings.length > 0 ? (
              <span className="flex flex-wrap items-center gap-1.5">
                {decision.dissenting_findings.map((s) => (
                  <Tag key={s}>{signalLabel(s)}</Tag>
                ))}
              </span>
            ) : DASH}
          </FieldRow>
          <FieldRow label="Rationale">
            <span className="block leading-[1.5]">
              {decision ? decision.rationale : DASH}
            </span>
          </FieldRow>
        </dl>
      </div>
    </>
  );
}

/* ==========================================================================
   SESSION MEMORY — what the case remembers across dormancy.
   ========================================================================== */

type MemoryData = Awaited<ReturnType<typeof api.memory>>;
type MemoryEvent = MemoryData['events'][number];

function MemoryPanel({
  caseId, nonce, tenantId,
}: { caseId: string; nonce: number; tenantId: string | null }) {
  // The threat library is district-wide, not per-case: this panel answers both "what did the
  // district know coming into this case" and "what did it write back out". Scoped, because
  // another district's library names their case ids and their victims.
  const [library, setLibrary] = useState<Awaited<ReturnType<typeof api.threatLibrary>> | null>(null);
  useEffect(() => {
    void api.threatLibrary(tenantId ?? undefined).then(setLibrary).catch(() => setLibrary(null));
  }, [caseId, nonce, tenantId]);

  const [data, setData] = useState<MemoryData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    void api.memory(caseId)
      .then((d) => { if (live) setData(d); })
      .catch(() => { if (live) setData(null); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [caseId, nonce]);

  const first = loading && data === null;

  const columns: Column<MemoryEvent>[] = [
    {
      key: 'kind',
      header: 'Event',
      width: '200px',
      sortable: true,
      value: (r) => r.kind,
      title: (r) => r.kind,
      render: (r) => (
        <span className="text-[var(--color-ink)]">{eventKindLabel(r.kind)}</span>
      ),
    },
    {
      key: 'at',
      header: `Occurred (${LOCAL_ZONE})`,
      width: '132px',
      headerTitle: `Local time — ${LOCAL_ZONE_LONG}`,
      sortable: true,
      value: (r) => r.occurred_at,
      render: (r) => <Timestamp>{clock(r.occurred_at)}</Timestamp>,
    },
    {
      key: 'fields',
      header: 'Fields',
      width: '72px',
      numeric: true,
      sortable: true,
      value: (r) => entriesOf(r.payload).length,
      render: (r) => entriesOf(r.payload).length,
    },
    {
      key: 'payload',
      header: 'Payload',
      title: (r) => JSON.stringify(r.payload),
      render: (r) => <ObjectSummary value={r.payload} />,
    },
  ];

  const events = data?.events ?? [];
  const noSession = !loading && !data?.session_id;

  // What the fleet knows about the adversary, above what it recorded about this case.
  const dossiers = (library?.operations ?? []).filter((o) => o.dossier?.designation);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {dossiers.length > 0 && (
        <div className="flex flex-col gap-2 px-3 pt-3">
          {dossiers.map((op) => (
            <DossierPanel key={op.case_id} dossier={op.dossier} />
          ))}
        </div>
      )}
      <LoadBar loading={loading} />
      {/* The counters live in the strip below; the same number twice in one
          frame is noise. */}
      <SectionHeader title="Session memory" />
      <Region label="Session memory">
        <div className={`flex flex-wrap items-start gap-x-6 gap-y-2 rule-b py-3 ${GUT}`}>
          <KeyValue label="Session" className="min-w-[240px]">
            {data?.session_id ? <MonoId truncate copyable>{data.session_id}</MonoId> : DASH}
          </KeyValue>
          <KeyValue label="Age" className="min-w-[112px]">
            {data?.age_days === null || data?.age_days === undefined ? DASH : (
              <span>
                <span data-numeric="" className="font-mono tabular">{data.age_days}</span>
                {` day${data.age_days === 1 ? '' : 's'}`}
              </span>
            )}
          </KeyValue>
          <KeyValue label="Events" className="min-w-[80px]">
            {first
              ? DASH
              : <span data-numeric="" className="font-mono tabular">{events.length}</span>}
          </KeyValue>
        </div>
        <p className={`py-2 text-xs leading-4 text-[var(--color-ink-dim)] ${MEASURE} ${GUT}`}>
          One session per case, opened on the first run and surviving dormancy.
        </p>
        {noSession ? (
          <NonIdealState
            visual={<Database aria-hidden size={22} strokeWidth={1.75} />}
            title="No session opened"
          />
        ) : (
          <DataGrid
            label="Session events"
            density="dense"
            columns={columns}
            rows={events}
            rowKey={(r) => r.event_id}
            loading={first}
            skeletonRows={8}
            empty={
              <NonIdealState
                visual={<Database aria-hidden size={22} strokeWidth={1.75} />}
                title="No events on this session"
                description="Events are appended as the fleet acts on the case."
              />
            }
          />
        )}
      </Region>
    </div>
  );
}

/* ==========================================================================
   CRASH SAFETY — two dense ledgers: what was checkpointed, what was actually
   done. Together they are the proof that a crash cannot double-pay.
   ========================================================================== */

const CHECKPOINT_TONE = {
  completed: 'verdigris',
  failed: 'amber',
  started: 'neutral',
} as const;

function DurabilityPanel({ caseId, nonce }: { caseId: string; nonce: number }) {
  const [data, setData] = useState<{ checkpoints: Checkpoint[]; effects: Effect[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    void api.checkpoints(caseId)
      .then((d) => { if (live) setData(d); })
      .catch(() => { if (live) setData(null); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [caseId, nonce]);

  const first = loading && data === null;

  const checkpointColumns: Column<Checkpoint>[] = [
    {
      key: 'seq', header: 'Seq', width: '52px', numeric: true,
      sortable: true, value: (r) => r.seq,
      render: (r) => <span className="text-[var(--color-ink-dim)]">{r.seq}</span>,
    },
    {
      key: 'step', header: 'Step', sortable: true, value: (r) => r.step,
      title: (r) => r.step,
      render: (r) => <span className="font-mono text-[var(--color-ink)]">{r.step}</span>,
    },
    {
      key: 'status', header: 'Status', width: '104px',
      sortable: true, value: (r) => r.status,
      render: (r) => (
        <Pill tone={CHECKPOINT_TONE[r.status]} minWidth={68}>{humanize(r.status)}</Pill>
      ),
    },
    {
      key: 'from', header: 'From', width: '128px',
      title: (r) => stateLabel(r.state_before),
      render: (r) => (
        <span className="text-[var(--color-ink-dim)]">{stateLabelShort(r.state_before)}</span>
      ),
    },
    {
      key: 'to', header: 'To', width: '128px',
      title: (r) => (r.state_after ? stateLabel(r.state_after) : ''),
      render: (r) => (r.state_after
        ? <span className="text-[var(--color-ink-dim)]">{stateLabelShort(r.state_after)}</span>
        : DASH),
    },
    {
      key: 'attempt', header: 'Attempt', width: '68px', numeric: true,
      sortable: true, value: (r) => r.attempt,
      render: (r) => r.attempt,
    },
    {
      key: 'input', header: 'Input hash', width: '116px',
      title: (r) => r.input_hash,
      render: (r) => <MonoId dim>{shortHash(r.input_hash)}</MonoId>,
    },
    {
      key: 'output', header: 'Output hash', width: '116px',
      title: (r) => r.output_hash ?? '',
      render: (r) => (r.output_hash ? <MonoId dim>{shortHash(r.output_hash)}</MonoId> : DASH),
    },
  ];

  const effectColumns: Column<Effect>[] = [
    {
      key: 'key', header: 'Idempotency key', width: '280px',
      sortable: true, value: (r) => r.idempotency_key,
      title: (r) => r.idempotency_key,
      render: (r) => <span className="font-mono text-[var(--color-ink)]">{r.idempotency_key}</span>,
    },
    {
      key: 'action', header: 'Action', width: '176px',
      sortable: true, value: (r) => r.action,
      title: (r) => r.action,
      // A backend identifier gets ONE treatment on this surface, and it is
      // mono — the same treatment `step` gets in the grid above.
      render: (r) => <span className="font-mono text-[var(--color-ink)]">{r.action}</span>,
    },
    {
      key: 'fields', header: 'Fields', width: '72px', numeric: true,
      sortable: true, value: (r) => entriesOf(r.result).length,
      render: (r) => entriesOf(r.result).length,
    },
    {
      key: 'result', header: 'Result',
      title: (r) => JSON.stringify(r.result),
      render: (r) => <ObjectSummary value={r.result} />,
    },
    {
      key: 'recorded', header: `Recorded (${LOCAL_ZONE})`, width: '132px',
      headerTitle: `Local time — ${LOCAL_ZONE_LONG}`,
      sortable: true, value: (r) => r.recorded_at,
      render: (r) => <Timestamp>{clock(r.recorded_at)}</Timestamp>,
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <LoadBar loading={loading} />
      {/* The two counters live on the two ledgers below; repeating them here
          would put the same number on screen twice. */}
      <SectionHeader title="Crash safety" />
      <Region label="Crash safety">
        <SectionHeader
          title="Checkpoint log"
          actions={<Metric label="steps" value={first ? '—' : data?.checkpoints.length ?? 0} />}
        />
        <p className={`py-2 text-xs leading-4 text-[var(--color-ink-dim)] ${MEASURE} ${GUT}`}>
          Written before each step; a resumed runner skips any step already completed.
        </p>
        <DataGrid
          label="Checkpoint log"
          density="dense"
          columns={checkpointColumns}
          rows={data?.checkpoints ?? []}
          rowKey={(r) => `${r.seq}-${r.step}`}
          loading={first}
          skeletonRows={8}
          empty={<NonIdealState
            visual={<History aria-hidden size={22} strokeWidth={1.75} />}
            title="No checkpoints written" />}
        />

        <SectionHeader
          title="Effects ledger"
          actions={<Metric label="effects" value={first ? '—' : data?.effects.length ?? 0} />}
          className="mt-6"
        />
        <p className={`py-2 text-xs leading-4 text-[var(--color-ink-dim)] ${MEASURE} ${GUT}`}>
          One row per side effect, claimed atomically by idempotency key.
        </p>
        <DataGrid
          label="Effects ledger"
          density="dense"
          columns={effectColumns}
          rows={data?.effects ?? []}
          rowKey={(r) => r.idempotency_key}
          loading={first}
          skeletonRows={4}
          empty={<NonIdealState
            visual={<ScrollText aria-hidden size={22} strokeWidth={1.75} />}
            title="No effects recorded" />}
        />
      </Region>
    </div>
  );
}

/* ==========================================================================
   AUDIT RECORD — the hash-chained compliance record.

   The chain is drawn as a chain: the inherited hash above, this record in
   brass below it, on one spine. The connector states the relationship in words
   as well as in geometry, because the surface is judged muted.
   ========================================================================== */

function AuditPanel({ caseId, nonce }: { caseId: string; nonce: number }) {
  const [record, setRecord] = useState<AuditRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setFailed(false);
    void api.auditRecord(caseId)
      .then((r) => { if (live) setRecord(r); })
      .catch(() => { if (live) { setRecord(null); setFailed(true); } })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [caseId, nonce]);

  const screening = entriesOf(record?.guardrail_screening);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <LoadBar loading={loading} />
      <SectionHeader
        title="Compliance record"
        actions={
          /* An inventory gap, flagged not absorbed: `Button` has no `href`
             escape hatch, so a download link cannot be one. The skin below is
             `Button variant="outlined" size="sm"` token for token. */
          <a
            href={api.auditDownloadUrl(caseId)}
            download
            title="Download the record as JSON"
            aria-disabled={!record}
            className={`inline-flex h-[24px] items-center gap-1.5 rounded-[var(--radius-ctl)]
              border border-[var(--color-rule-strong)] px-2 text-mini font-medium
              text-[var(--color-ink-dim)] transition-colors duration-100 ease-[var(--ease-ui)]
              hover:bg-[var(--color-fill-neutral)] hover:text-[var(--color-ink)]
              ${record ? '' : 'pointer-events-none text-[var(--color-ink-disabled)]'}`}
          >
            <Download aria-hidden size={11} strokeWidth={1.75} />
            Download JSON
          </a>
        }
      />
      <Region label="Compliance record" className={`py-3 ${GUT}`}>
        {failed || (!record && !loading) ? (
          <NonIdealState
            visual={<ScrollText aria-hidden size={22} strokeWidth={1.75} />}
            title="No audit record"
            description="A record is emitted when the case reaches a terminal decision."
          />
        ) : (
          <>
            <div className="flex items-baseline gap-3">
              <h3 className="font-display text-lg leading-[22px] text-[var(--color-ink)]">
                {record ? record.framework : '—'}
              </h3>
              {record ? <MonoId copyable>{record.record_id}</MonoId> : DASH}
            </div>

            {/* Rendered at full height whether or not the record has landed:
                every value is an em-dash until it is a value (assertion 22). */}
            <dl className={`mt-2 ${MEASURE}`}>
              <FieldRow label="Control objective">
                {record ? record.control_objective : DASH}
              </FieldRow>
              <FieldRow label="Vendor">
                {record ? <MonoId>{record.vendor_ref}</MonoId> : DASH}
              </FieldRow>
              <FieldRow label="Exposure">
                {record ? <Money value={record.exposure_amount} size="sm" cents /> : DASH}
              </FieldRow>
              <FieldRow label="Outcome">
                {record
                  ? (
                    <Pill tone={OUTCOME_TONE[record.outcome]}>
                      {outcomeLabel(record.outcome)}
                    </Pill>
                  )
                  : DASH}
              </FieldRow>
              <FieldRow label="Decided by">
                {record ? humanize(record.decided_by) : DASH}
              </FieldRow>
              <FieldRow label="Rationale">
                <span className="block leading-[1.5]">
                  {record ? record.decision_rationale : DASH}
                </span>
              </FieldRow>
              <FieldRow label="Signals evaluated">
                {record
                  ? (
                    <span data-numeric="" className="font-mono tabular">
                      {record.risk_signals_evaluated.length}
                    </span>
                  )
                  : DASH}
              </FieldRow>
              <FieldRow label="Evidence items">
                {record
                  ? (
                    <span data-numeric="" className="font-mono tabular">
                      {record.evidence_chain.length}
                    </span>
                  )
                  : DASH}
              </FieldRow>
              <FieldRow label="Session">
                {record?.session_id ? <MonoId truncate>{record.session_id}</MonoId> : DASH}
              </FieldRow>
              <FieldRow label="Reasoning trace">
                {record ? <MonoId truncate>{record.reasoning_trace_uri}</MonoId> : DASH}
              </FieldRow>
              <FieldRow label={`Emitted (${LOCAL_ZONE})`}>
                {record ? <Timestamp>{clock(record.emitted_at)}</Timestamp> : DASH}
              </FieldRow>
            </dl>

            <div className={`mt-6 rule-t pt-3 ${MEASURE}`}>
              <h4 className="label-brass mb-2">Guardrail screening</h4>
              <dl>
                {screening.map(([k, v]) => (
                  <FieldRow key={k} label={humanize(k)}>
                    <span className="font-mono text-mini text-[var(--color-ink)]">
                      {scalarText(v)}
                    </span>
                  </FieldRow>
                ))}
                {screening.length === 0 && <FieldRow label="Screening">{DASH}</FieldRow>}
              </dl>
            </div>

            <div className={`mt-6 rule-t pt-3 ${MEASURE}`}>
              <h4 className="label-brass mb-2">Hash chain</h4>
              <p className={`mb-3 text-xs leading-4 text-[var(--color-ink-dim)] ${MEASURE}`}>
                Each record hashes the record before it, so the chain verifies end to end or
                not at all.
              </p>
              <ChainLink
                label="Previous record"
                caption="Inherited from the record before this one"
                hash={record?.prev_record_hash ?? null}
                tone="faint"
              />
              <ChainConnector label="hashed into" />
              <ChainLink
                label="This record"
                caption={record?.record_id ?? '—'}
                hash={record?.record_hash ?? null}
                tone="brass"
              />
            </div>
          </>
        )}
      </Region>
    </div>
  );
}

type ChainTone = 'faint' | 'brass' | 'dormant';

/** One link of the chain: a 5px marker on the spine, a label, and the hash at
    the §12 length — 10 characters, mono, with the full value in `title`. */
function ChainLink({
  label, caption, hash, tone,
}: { label: string; caption: ReactNode; hash: string | null; tone: ChainTone }) {
  return (
    <div className="flex items-start gap-3">
      {/* Centre lands at 8 + 2.5 = 10.5px, on the connector spine below. */}
      <span className="mt-3 ml-2 shrink-0">
        <Dot tone={tone === 'brass' ? 'brass' : 'neutral'} />
      </span>
      <div
        className={`min-w-0 flex-1 rounded-[var(--radius-ctl)] px-3 py-2
          shadow-[var(--shadow-elev-0)] ${
            tone === 'brass' ? 'bg-[var(--color-raised)]' : 'bg-[var(--color-surface)]'
          }`}
      >
        <div className="flex items-baseline justify-between gap-3">
          <span className={tone === 'brass' ? 'label-brass' : 'label-micro'}>{label}</span>
          <span className="truncate text-mini text-[var(--color-ink-dim)]">{caption}</span>
        </div>
        <div className="mt-1">
          {hash
            ? <MonoId dim={tone === 'dormant'} title={hash}>{shortHash(hash, 10)}</MonoId>
            : DASH}
        </div>
      </div>
    </div>
  );
}

/** The spine between two links: a real vertical line, labelled in words. */
function ChainConnector({ label, dormant = false }: { label: string; dormant?: boolean }) {
  return (
    <div className="flex items-center gap-2 pl-2">
      <span
        aria-hidden
        className={`ml-0.5 h-6 w-px shrink-0 ${
          dormant ? 'bg-[var(--color-rule)]' : 'bg-[var(--color-brass-dim)]'
        }`}
      />
      <Link2
        aria-hidden
        size={11}
        strokeWidth={1.75}
        className={dormant ? 'text-[var(--color-ink-disabled)]' : 'text-[var(--color-brass)]'}
      />
      <span className="label-micro">{label}</span>
    </div>
  );
}
