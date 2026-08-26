import { useCallback, useEffect, useMemo, useState } from 'react';
import { Boxes, ChevronDown, Search, TriangleAlert } from 'lucide-react';
import { api } from '@/lib/api';
import type { RegistryEntry } from '@/lib/types';
import { classificationLabel } from '@/lib/format';
import { DataGrid, type Column } from '@/components/DataGrid';
import { RedTeamPanel } from './RedTeamPanel';
import {
  Button, cx, Divider, FieldRow, Input, KeyValue, MonoId, NonIdealState,
  Panel, Pill, ScopeManifest, SectionHeader, Tag,
} from '@/components/primitives';

/**
 * REGISTRY — discovery. The opening shot of the recording.
 *
 * An internal agent catalog: nine agents across three fleets, searchable and
 * filterable by department and data classification. A registry with one entry
 * is a demo; three fleets is a platform.
 *
 * Implemented from context/UI_SPEC.md:
 *   §14  catalog 1fr | agent detail 420px, divided by a single 1px rule.
 *   §3   28px rows, 30px sticky header, fixed table layout, every width declared.
 *   §8   record header — label above value, label smaller than value.
 *   §7   no oxblood on this surface. Nothing here stops money.
 *   §12  identifiers are mono, muted, full value in `title`.
 *
 * COLOUR BUDGET. The runtime binding is the only place a hue can appear here,
 * and it is verdigris ONLY when the platform actually publishes an engine id.
 * The REST contract returns `reasoning_engine_id: null` for every entry until
 * something calls `runtime.deploy()`, and today nothing does — so the honest
 * rendering of an absent binding is NEUTRAL ("Unbound"), not amber "Dormant".
 * Amber means held/awaiting/dormant — a state the system is asserting. An
 * absent field is not a state; painting nine amber pills would spend the whole
 * chroma budget of the opening shot claiming a live catalog is dead.
 *
 * The detail pane is a record home: a two-row record header, then Details,
 * Deployment, the scope manifest, and the version-history timeline. The scope
 * manifest is a security artifact — a procurement reviewer must be able to read
 * granted-versus-denied in one glance, without hovering anything.
 */

/** §3 minimum skeleton display. Local FastAPI answers in single-digit ms. */
const SKELETON_FLOOR_MS = 300;

export function Registry() {
  const [entries, setEntries] = useState<RegistryEntry[]>([]);
  // Never optimistic: the platform binding is a fetched fact, not a default.
  const [backend, setBackend] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [dept, setDept] = useState<string>('all');
  const [classification, setClassification] = useState<string>('all');
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    const startedAt = Date.now();
    setLoading(true);
    setError(null);
    void api.registry()
      .then((r) => {
        setEntries(r.entries);
        setBackend(r.backend);
        // The challenger is the agent the demo narrates; fall back to the first
        // published entry so the detail pane is never empty on arrival.
        setSelected(
          r.entries.find((e) => e.agent_id === 'interdict.challenger')?.agent_id
          ?? r.entries[0]?.agent_id
          ?? null,
        );
      })
      .catch((e: unknown) => {
        setEntries([]);
        setBackend(null);
        setSelected(null);
        setError(e instanceof Error ? e.message : 'The catalog service did not respond.');
      })
      .finally(() => {
        // A skeleton that flashes for 8ms is worse than no skeleton: it reads
        // as a repaint. Hold the reserved shape for at least 300ms.
        const wait = Math.max(0, SKELETON_FLOOR_MS - (Date.now() - startedAt));
        window.setTimeout(() => setLoading(false), wait);
      });
  }, []);

  useEffect(() => { load(); }, [load]);

  const departments = useMemo(
    () => ['all', ...Array.from(new Set(entries.map((e) => e.department))).sort()],
    [entries],
  );
  const classifications = useMemo(
    () => ['all', ...Array.from(new Set(entries.map((e) => e.data_classification))).sort()],
    [entries],
  );
  const fleetCount = useMemo(
    () => new Set(entries.map((e) => e.fleet)).size,
    [entries],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => {
      if (dept !== 'all' && e.department !== dept) return false;
      if (classification !== 'all' && e.data_classification !== classification) return false;
      if (!q) return true;
      return (
        e.agent_id.toLowerCase().includes(q) ||
        e.display_name.toLowerCase().includes(q) ||
        e.description.toLowerCase().includes(q)
      );
    });
  }, [entries, query, dept, classification]);

  const scopeTotals = useMemo(
    () => filtered.reduce(
      (acc, e) => ({
        granted: acc.granted + e.granted_scopes.length,
        denied: acc.denied + e.denied_scopes.length,
      }),
      { granted: 0, denied: 0 },
    ),
    [filtered],
  );

  const active = entries.find((e) => e.agent_id === selected) ?? null;
  const dirty = query !== '' || dept !== 'all' || classification !== 'all';
  const settled = !loading && !error;

  const clearFilters = () => {
    setQuery('');
    setDept('all');
    setClassification('all');
  };

  /* --- columns ---------------------------------------------------------
     EVERY width is declared (§3) — including Agent, which previously had
     none and therefore resolved to 0px under `table-layout: fixed` on any
     viewport under ~1450px. The declared sum is 952px, which fits the
     catalog pane at a 1440px viewport (1440 − 56 rail − 420 detail = 964)
     and scales proportionally at 1920. `Used by` is not a column: at 11px
     it truncated for a third of the catalog and its full value now lives in
     the detail pane, as tags, where it has room. ------------------------ */
  const columns: Column<RegistryEntry>[] = [
    {
      key: 'agent',
      header: 'Agent',
      width: '216px',
      sortable: true,
      value: (r) => r.display_name,
      title: (r) => `${r.display_name} — ${r.description}`,
      render: (r) => (
        <span className="truncate font-medium text-[var(--color-ink)]">{r.display_name}</span>
      ),
    },
    {
      // 184px holds the longest real id ("interdict.registry-check", 24ch at
      // 11px mono) without truncating, which is why this one is NOT passed
      // `truncate`: middle-truncating a readable dotted id costs more than it
      // buys. The `title` carries the full value regardless.
      key: 'id',
      header: 'Agent ID',
      width: '184px',
      sortable: true,
      value: (r) => r.agent_id,
      title: (r) => r.agent_id,
      render: (r) => <MonoId>{r.agent_id}</MonoId>,
    },
    {
      // A fleet is a category, not an identifier (§12) — sans, never mono.
      key: 'fleet',
      header: 'Fleet',
      width: '92px',
      sortable: true,
      value: (r) => r.fleet,
      title: (r) => `${r.fleet} fleet`,
      render: (r) => <span className="truncate text-[var(--color-ink-dim)]">{r.fleet}</span>,
    },
    {
      key: 'version',
      header: 'Version',
      width: '72px',
      sortable: true,
      value: (r) => r.version,
      render: (r) => <MonoId>v{r.version}</MonoId>,
    },
    {
      key: 'dept',
      header: 'Department',
      width: '140px',
      sortable: true,
      value: (r) => r.department,
      title: (r) => r.department,
      render: (r) => <span className="truncate text-[var(--color-ink-dim)]">{r.department}</span>,
    },
    {
      key: 'class',
      header: 'Data class',
      width: '112px',
      sortable: true,
      value: (r) => r.data_classification,
      render: (r) => (
        <Pill tone="neutral" minWidth={68}>{classificationLabel(r.data_classification)}</Pill>
      ),
    },
    {
      // The header says what the two numbers are. A ratio whose key lives only
      // in a tooltip is invisible on a muted recording (N3).
      key: 'scopes',
      header: 'Granted / denied',
      width: '136px',
      numeric: true,
      sortable: true,
      value: (r) => r.granted_scopes.length,
      headerTitle: 'Scopes granted to, and explicitly denied to, each agent',
      title: (r) => `${r.granted_scopes.length} granted, ${r.denied_scopes.length} denied`,
      render: (r) => (
        <span className="text-[var(--color-ink-dim)]">
          {r.granted_scopes.length}
          <span className="px-1 text-[var(--color-ink-faint)]">/</span>
          {r.denied_scopes.length}
        </span>
      ),
    },
  ];

  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_420px]">
      {/* ---- catalog, over the fleet's own score --------------------------
          The scoreboard is a claim about the agents in the list above it, so it
          shares their column. 240px is the reserved height: the catalog above it
          still clears the 20-row floor at 1080p, and the band does not resize when
          a run lands. */}
      <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_240px] rule-r">
        <Panel
          title="Agent catalog"
          actions={
            <span className="label-micro tabular">
              {settled ? `${filtered.length} of ${entries.length}` : '— of —'}
            </span>
          }
          scroll={false}
          footer={
            <>
              <span className="label-micro">Scopes</span>
              <span className="tabular text-mini text-[var(--color-ink-dim)]">
                {settled ? `${scopeTotals.granted} granted · ${scopeTotals.denied} denied` : '—'}
              </span>
              <Divider vertical />
              <span className="label-micro">Fleets</span>
              <span className="tabular text-mini text-[var(--color-ink-dim)]">
                {settled ? fleetCount : '—'}
              </span>
              <span className="flex-1" />
              <span className="label-micro">Platform</span>
              <span className="text-mini text-[var(--color-ink-dim)]">{backend ?? '—'}</span>
            </>
          }
        >
          <div className="flex h-full min-h-0 flex-col">
            {/* The search glyph is a sibling of the field, not an overlay with a
                padding override: `pl-6` on an `Input` whose base is `px-2` only
                wins by CSS emission order, and losing that race puts the glyph
                on top of the placeholder. */}
            <div className="flex h-[40px] shrink-0 items-center gap-2 rule-b px-3">
              <span className="flex shrink-0 items-center gap-1.5">
                <Search
                  aria-hidden
                  size={12}
                  strokeWidth={1.75}
                  className="shrink-0 text-[var(--color-ink-faint)]"
                />
                <span className="block w-[264px]">
                  <Input
                    value={query}
                    onChange={setQuery}
                    size="sm"
                    ariaLabel="Search agents"
                    placeholder="Search agents, descriptions…"
                  />
                </span>
              </span>

              <Divider vertical />

              <FilterSelect
                label="Department"
                value={dept}
                options={departments}
                onChange={setDept}
              />
              <FilterSelect
                label="Data class"
                value={classification}
                options={classifications}
                format={classificationLabel}
                onChange={setClassification}
              />

              <span className="flex-1" />

              <Button size="sm" variant="minimal" disabled={!dirty} onClick={clearFilters}>
                Clear filters
              </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto pane-scroll">
              {error
                ? (
                  // A fetch failure is not an empty filter set. Name the endpoint
                  // and offer the retry; never tell the operator to clear filters
                  // they never set.
                  <NonIdealState
                    visual={<TriangleAlert aria-hidden size={22} strokeWidth={1.75} />}
                    title="Catalog unavailable"
                    description={`/api/registry did not answer. ${error}`}
                    action={
                      <Button size="sm" variant="outlined" onClick={load}>
                        Retry
                      </Button>
                    }
                  />
                )
                : (
                  <DataGrid
                    label="Agent catalog"
                    columns={columns}
                    rows={filtered}
                    rowKey={(r) => r.agent_id}
                    onSelect={(r) => setSelected(r.agent_id)}
                    selectedKey={selected}
                    defaultSort={{ key: 'id', dir: 'asc' }}
                    loading={loading}
                    skeletonRows={9}
                    empty={
                      <NonIdealState
                        visual={<Boxes aria-hidden size={22} strokeWidth={1.75} />}
                        title="No agents match these filters"
                        description="Clear the search and the department and data-class filters to see the full catalog."
                      />
                    }
                  />
                )}
            </div>
          </div>
        </Panel>
        <RedTeamPanel />
      </div>

      {/* ---- record ------------------------------------------------------- */}
      <Panel title="Agent record">
        {active
          ? <AgentRecord entry={active} />
          : (
            <NonIdealState
              visual={<Boxes aria-hidden size={22} strokeWidth={1.75} />}
              title="Select an agent"
              description="Pick a row in the catalog to read its owner, scope manifest and version history."
            />
          )}
      </Panel>
    </div>
  );
}

/* ==========================================================================
   FILTER CONTROL

   A 24px filter token (§2). Native `select` so the keyboard and screen-reader
   behaviour is the platform's; the chrome is ours — a recessed well, a 3px
   radius, and one chevron at 10px.
   ========================================================================== */

function FilterSelect({
  label, value, options, onChange, format,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  format?: (v: string) => string;
}) {
  return (
    <label className="flex shrink-0 items-center gap-1.5">
      <span className="label-micro">{label}</span>
      <span className="relative inline-flex items-center">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-[24px] appearance-none rounded-[var(--radius-input)] border-0
            bg-[var(--color-ground)] pl-2 pr-6 text-mini text-[var(--color-ink)]
            shadow-[var(--shadow-well)] outline-none
            transition-shadow duration-100 ease-[var(--ease-ui)]"
        >
          {options.map((o) => (
            <option key={o} value={o}>{o === 'all' ? 'All' : format ? format(o) : o}</option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          size={10}
          strokeWidth={2}
          className="pointer-events-none absolute right-2 text-[var(--color-ink-faint)]"
        />
      </span>
    </label>
  );
}

/* ==========================================================================
   RECORD HOME

   Row 1 of the header is the entity label and the record title; row 2 is the
   highlights strip. Below it, four sections, each behind a 30px header:
   Details, Deployment, Scope manifest, Version history.
   ========================================================================== */

function AgentRecord({ entry }: { entry: RegistryEntry }) {
  const deployed = entry.reasoning_engine_id !== null;

  return (
    <div className="pb-6">
      <header className="rule-b px-3 py-3">
        <div className="flex items-center gap-2">
          <span className="label-brass truncate">Registered agent</span>
          <Divider vertical />
          <span className="label-micro truncate">{entry.fleet} fleet</span>
        </div>

        <h2 className="mt-1 truncate font-display text-lg leading-[22px] text-[var(--color-ink)]">
          {entry.display_name}
        </h2>

        <div className="mt-1 flex min-w-0 items-center gap-2">
          <MonoId copyable title={entry.agent_id}>{entry.agent_id}</MonoId>
        </div>

        {/* The box is reserved, the copy is clamped. Descriptions run one to
            four lines; an unclamped paragraph moves every section below it by
            up to 48px on each selection, which is the surface's primary
            on-camera interaction. */}
        <p
          title={entry.description}
          className="mt-2 line-clamp-2 h-8 overflow-hidden text-xs leading-4
            text-[var(--color-ink-muted)]"
        >
          {entry.description}
        </p>

        <div className="mt-3 grid grid-cols-3 gap-3">
          <KeyValue label="Data class">
            <Pill tone="neutral">{classificationLabel(entry.data_classification)}</Pill>
          </KeyValue>
          {/* The single deployment fact, in one vocabulary, rendered once.
              Fill + `-text` rather than a dot: a 5px circle is not a colour
              encoding that survives desaturation (§27). */}
          <KeyValue label="Deployment">
            <Pill tone={deployed ? 'verdigris' : 'neutral'}>
              {deployed ? 'Serving' : 'Unbound'}
            </Pill>
          </KeyValue>
        </div>
      </header>

      {/* ---- details ----------------------------------------------------- */}
      <SectionHeader title="Details" />
      <dl className="px-3 py-2">
        <FieldRow label="Owner">
          <MonoId title={entry.owner}>{entry.owner}</MonoId>
        </FieldRow>
        <FieldRow label="Department">{entry.department}</FieldRow>
        <FieldRow label="Used by">
          <span className="flex flex-wrap gap-1">
            {entry.used_by.length
              ? entry.used_by.map((d) => <Tag key={d} tone="neutral">{d}</Tag>)
              : <span className="text-[var(--color-ink-dim)]">—</span>}
          </span>
        </FieldRow>
      </dl>

      {/* ---- deployment --------------------------------------------------
          Both fields are contract fields and both are absent until something
          deploys the agent to a managed runtime. An em-dash is the correct
          rendering of an absent value (§15.22); the header pill carries the
          state, so the absence needs no prose. */}
      <SectionHeader title="Deployment" />
      <dl className="px-3 py-2">
        <FieldRow label="Reasoning engine">
          <MonoId truncate title={entry.reasoning_engine_id ?? 'No engine published'}>
            {entry.reasoning_engine_id ?? '—'}
          </MonoId>
        </FieldRow>
        <FieldRow label="Runtime revision">
          <MonoId title={entry.runtime_revision ?? 'No revision published'}>
            {entry.runtime_revision ?? '—'}
          </MonoId>
        </FieldRow>
      </dl>

      {/* ---- scope manifest ----------------------------------------------
          The security artifact. Granted and denied are two blocks, each with
          its own count and its own left rail, so the shape of an agent's
          authority is legible before a single chip is read. Denied is struck
          neutral, deliberately not oxblood: a denial is the system working.

          NOTE: no capability class is asserted here. The REST contract carries
          no `capability_class`, and deriving "write capable" from a scope-name
          regex mislabels `erp:journal:propose` as read-only. A procurement
          surface does not guess at a security claim. */}
      <SectionHeader title="Scope manifest" />
      <div className="flex flex-col gap-2 px-3 py-2">
        <ScopeManifest framed label="Granted scopes" scopes={entry.granted_scopes} />
        <ScopeManifest framed denied label="Denied scopes" scopes={entry.denied_scopes} />
      </div>

      {/* ---- version history --------------------------------------------- */}
      <SectionHeader title="Version history" />
      <div className="px-3 py-2">
        {entry.changelog.length
          ? <VersionTimeline changelog={entry.changelog} />
          : <p className="text-mini text-[var(--color-ink-dim)]">—</p>}
      </div>
    </div>
  );
}

/**
 * Version history as a timeline, not a bulleted list: a spine with a node per
 * release, newest first. The current release carries a brass node and a brass
 * label; superseded releases carry a neutral node. Nodes are 8px squares at a
 * 2px radius — the pill radius — because a circle here would read as a state
 * dot, and state dots mean something else in this system.
 *
 * Geometry: the node occupies y 4–12 and centres on x 4; the spine starts at
 * y 12 (flush with the node) and runs to 16px past the container — the 12px
 * row padding plus the next node's 4px offset — so it is continuous, not a
 * dashed sequence of 4px gaps. The spine is 2px at x 3–5 so it shares the
 * node's centre on a whole pixel and does not render smeared at 1080p.
 */
function VersionTimeline({
  changelog,
}: { changelog: { version: string; note: string }[] }) {
  return (
    <ol className="flex flex-col">
      {changelog.map((c, i) => {
        const current = i === 0;
        return (
          <li key={c.version} className="group grid grid-cols-[8px_1fr] gap-3 pb-3 last:pb-0">
            <span aria-hidden className="relative block">
              <span
                className={cx(
                  'absolute left-0 top-1 block h-2 w-2 rounded-[var(--radius-pill)]',
                  current ? 'bg-[var(--color-brass)]' : 'bg-[var(--color-rule-strong)]',
                )}
              />
              <span
                className="absolute left-[3px] top-3 -bottom-4 w-[2px] bg-[var(--color-rule)]
                  group-last:hidden"
              />
            </span>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className={cx(
                    'font-mono tabular text-mini',
                    current ? 'text-[var(--color-brass-text)]' : 'text-[var(--color-ink-dim)]',
                  )}
                >
                  v{c.version}
                </span>
                {current && <Pill tone="brass">Current</Pill>}
              </div>
              <p className="mt-[2px] text-mini leading-[15px] text-[var(--color-ink-muted)]">
                {c.note}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
