import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, Ban, Info, RefreshCw, ShieldCheck } from 'lucide-react';
import { api, ApiError } from '@/lib/api';
import type {
  GatewayDecision, Neutralization, PostureEvent, ScopeManifestRow,
} from '@/lib/types';
import {
  agentName, clockPrecise, LOCAL_ZONE, LOCAL_ZONE_LONG, locationLabel, plural, techniqueLabel,
} from '@/lib/format';
import {
  Button, Callout, cx, Divider, MonoId, NonIdealState, Panel, Pill, ScopeChip, ScopeManifest,
  SkeletonBar, Timestamp,
  TONE_RAIL,
} from '@/components/primitives';
import { DataGrid, type Column } from '@/components/DataGrid';
import { ExchangePanel } from './ExchangePanel';

/* ============================================================================
   POSTURE — trust the data handling.

   Implemented from context/UI_SPEC.md. Layout is §14: event feed 1fr |
   scope manifest 400px. Both columns split 1fr/1fr, so the two horizontal
   pane rules land on the same y and the surface reads as a deliberate grid
   rather than a pinwheel.

   THE SURFACE IS DELIBERATELY QUIET. Alarm styling everywhere makes the one
   real alarm meaningless, so nothing here is oxblood: a denial is the system
   working correctly, not money being stopped (§13, ScopeChip). Colour arrives
   only on deviation — the screened artifact and the denied call — and it
   arrives as a pill, a 2px rail and an icon, three redundant encodings of one
   fact (§7), so the frame survives desaturation and video compression. A
   PERMITTED hop is the non-deviant majority and is therefore neutral: every
   hop this system can produce is permitted, and painting all of them green
   would put colour on 100% of a pane at rest.

   THE ENTRY POINT is the neutralised-injection counter: one 28px display
   figure over a micro-label, the only type step above 13px on the surface.
   §8's ceiling discipline caps elements *above* 28px at two per screen; this
   sits at 28 and is the single anchor a muted viewer lands on.

   HONESTY. The screener REMOVES most techniques but only FLAGS homoglyphs —
   silently rewriting a lookalike character would destroy the evidence the
   Provenance agent has to cite. So a flagged span is NOT struck through. A
   strike here always means "this text never reached an agent".
   ============================================================================ */

const EM_DASH = '—';

/** §3: a skeleton that paints for one frame is worse than no skeleton. */
const MIN_SKELETON_MS = 300;

/** §13 Pill: a status column never jitters as values change. */
const PILL_MIN = 68;

/** Techniques the screener reports but does not rewrite. These are never struck. */
const FLAG_ONLY = new Set(['homoglyph']);

/**
 * Techniques whose evidence is a character, not a sentence. `zero_width`
 * excerpts arrive as the six-character escape `​` and `homoglyph`
 * excerpts as a single glyph; a strike drawn across either reads as a
 * rendering fault, so the human-readable detail leads and the raw character
 * follows as a labelled specimen.
 */
const CHARACTER_TECHNIQUES = new Set(['zero_width', 'homoglyph']);

/* Technique, location, agent and plural all come from `lib/format.ts`, so
   this feed and the case surfaces cannot spell one backend value two ways. */

const text = (value: unknown): string => {
  const s = value === null || value === undefined ? '' : String(value);
  return s.length > 0 ? s : EM_DASH;
};

const asArray = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

/* --- time ----------------------------------------------------------------
   §12: the zone is resolved once in `format.ts` and declared once per feed,
   in the column header. `clock` drops seconds, which is too coarse for a
   security-event feed, so this surface uses `clockPrecise`. */

const TZ_LONG = LOCAL_ZONE_LONG;
const TZ = LOCAL_ZONE;
const eventClock = clockPrecise;

interface PostureData {
  events: PostureEvent[];
  gateway_decisions: GatewayDecision[];
  scope_manifest: ScopeManifestRow[];
}

/* ==========================================================================
   COLUMNS

   Declared at module scope: they close over nothing, so the grid's sort
   memo is not invalidated on every render.
   ========================================================================== */

const DENIAL_COLUMNS: Column<PostureEvent>[] = [
  {
    key: 'time',
    header: `Time ${TZ}`,
    headerTitle: `Event time, ${TZ_LONG}`,
    width: '124px',
    numeric: true,
    sortable: true,
    value: (r) => r.occurred_at,
    render: (r) => <Timestamp>{eventClock(r.occurred_at)}</Timestamp>,
  },
  {
    key: 'agent',
    header: 'Agent',
    width: '108px',
    sortable: true,
    value: (r) => agentName(r.agent),
    title: (r) => agentName(r.agent),
    render: (r) => (
      <span className="text-[var(--color-ink)]">{agentName(r.agent)}</span>
    ),
  },
  {
    key: 'tool',
    header: 'Tool',
    width: '132px',
    sortable: true,
    value: (r) => text(r.tool),
    title: (r) => text(r.tool),
    render: (r) => <MonoId>{text(r.tool)}</MonoId>,
  },
  {
    key: 'scope',
    header: 'Scope attempted',
    width: '180px',
    sortable: true,
    value: (r) => text(r.scope),
    title: (r) => `${text(r.scope)} — denied by policy`,
    render: (r) => <ScopeChip scope={text(r.scope)} denied />,
  },
  {
    key: 'policy',
    header: 'Policy',
    width: '148px',
    sortable: true,
    value: (r) => text(r.policy_id),
    title: (r) => text(r.policy_id),
    render: (r) => <MonoId truncate>{text(r.policy_id)}</MonoId>,
  },
  {
    key: 'case',
    header: 'Case',
    width: 'auto',
    sortable: true,
    value: (r) => text(r.case_id),
    title: (r) => text(r.case_id),
    render: (r) => <MonoId truncate>{text(r.case_id)}</MonoId>,
  },
  {
    key: 'decision',
    header: 'Decision',
    width: '84px',
    align: 'right',
    render: () => <Pill tone="amber" minWidth={PILL_MIN}>denied</Pill>,
  },
];

const GATEWAY_COLUMNS: Column<GatewayDecision>[] = [
  {
    key: 'hop',
    header: 'Hop',
    width: 'auto',
    sortable: true,
    value: (d) => `${agentName(d.source)}→${agentName(d.target)}`,
    title: (d) => `${agentName(d.source)} → ${agentName(d.target)}`,
    render: (d) => (
      <span className="inline-flex items-baseline gap-1.5">
        <span className="text-[var(--color-ink)]">{agentName(d.source)}</span>
        <ArrowRight aria-hidden size={12} strokeWidth={1.75}
          className="shrink-0 self-center text-[var(--color-ink-dim)]" />
        <span className="text-[var(--color-ink)]">{agentName(d.target)}</span>
      </span>
    ),
  },
  {
    key: 'decision',
    header: 'Decision',
    width: '84px',
    align: 'right',
    sortable: true,
    value: (d) => (d.allowed ? 1 : 0),
    render: (d) => (
      // Colour on the deviation only. Every hop this fleet can emit is
      // permitted, so a green pill per row would be colour on the majority.
      <Pill tone={d.allowed ? 'neutral' : 'amber'} minWidth={PILL_MIN}>
        {d.allowed ? 'permitted' : 'refused'}
      </Pill>
    ),
  },
];

/* ==========================================================================
   THE SURFACE
   ========================================================================== */

export function Posture() {
  const [data, setData] = useState<PostureData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [landed, setLanded] = useState<string | null>(null);

  const first = useRef(true);
  const landTimer = useRef<number | null>(null);

  useEffect(() => () => {
    if (landTimer.current !== null) window.clearTimeout(landTimer.current);
  }, []);

  const load = useCallback(async (): Promise<PostureData | null> => {
    // §3: 300ms floor on the FIRST paint only. Against a localhost backend the
    // fetch resolves in single-digit ms, and a skeleton that flashes for one
    // frame reads as a glitch on a screen recording. A refetch never
    // re-skeletons, so the floor never delays an update.
    const floor = first.current
      ? new Promise<void>((resolve) => { window.setTimeout(resolve, MIN_SKELETON_MS); })
      : Promise.resolve();
    try {
      const [next] = await Promise.all([api.posture(), floor]);
      setData(next);
      setError(null);
      return next;
    } catch (e) {
      // A failed fetch must never render as "no denials recorded". An empty
      // system and an unreachable one are opposite facts on a compliance
      // surface.
      setError(e instanceof ApiError ? `HTTP ${e.status}` : 'no response');
      return null;
    } finally {
      first.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const probe = () => {
    setBusy(true);
    setProbeError(null);
    void api.demo.forceScopeViolation()
      .then(() => load())
      .then((next) => {
        // §10: the new row lands at full height and its background decays over
        // 700ms. Without it, a muted viewer cannot tell the click did anything.
        const newest = next?.events.find((e) => e.kind === 'identity_denial');
        if (!newest) return;
        setLanded(newest.event_id);
        if (landTimer.current !== null) window.clearTimeout(landTimer.current);
        landTimer.current = window.setTimeout(() => setLanded(null), 900);
      })
      .catch((e: unknown) => {
        setProbeError(
          e instanceof ApiError
            ? `The probe was refused (HTTP ${e.status}). Reset the demo corpus, then try again.`
            : 'The probe could not reach the backend.',
        );
      })
      .finally(() => setBusy(false));
  };

  const events = data?.events ?? [];
  const guardrails = events.filter((e) => e.kind === 'guardrail_screening');
  const denials = events.filter((e) => e.kind === 'identity_denial');
  const decisions = data?.gateway_decisions ?? [];
  const manifest = data?.scope_manifest ?? [];

  const removals = guardrails.reduce(
    (sum, e) => sum + asArray<Neutralization>(e.neutralizations).length, 0,
  );

  const refused = decisions.filter((d) => !d.allowed);
  const policies = new Set(decisions.map((d) => d.policy_id));
  const hopPolicy = policies.size === 1
    ? [...policies][0] ?? EM_DASH
    : policies.size === 0 ? EM_DASH : `${policies.size} policies`;

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_440px]">
      {/* ---------------------------------------------------------------- the feed */}
      <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] rule-r">
        <Panel
          title="Guardrail screening"
          className="min-h-0"
          actions={<FeedMeta parts={[
            plural(guardrails.length, 'artifact'),
            `times ${TZ}`,
          ]} />}
        >
          <div className="flex flex-col">
            {/* The anchor and the explanation are rendered in EVERY state —
                loading, empty and loaded — so nothing below them moves when
                the feed arrives (N4). */}
            <div className="flex items-start gap-3 rule-b-muted p-3">
              <div className="flex shrink-0 flex-col">
                <span data-numeric="" className="font-display tabular text-figure leading-[32px]
                  text-[var(--color-ink)]">
                  {removals}
                </span>
                <span className="label-micro">Injections neutralized</span>
              </div>
              <Callout compact className="flex-1"
                icon={<Info size={12} strokeWidth={1.75} aria-hidden />}>
                Removed spans are reproduced verbatim below, struck through. None of it ever
                reached an agent.
              </Callout>
            </div>

            {error ? (
              <FeedError status={error} onRetry={() => { void load(); }} />
            ) : loading ? (
              <GuardrailSkeleton />
            ) : guardrails.length === 0 ? (
              <NonIdealState
                visual={<ShieldCheck size={22} strokeWidth={1.75} aria-hidden />}
                title="No artifacts screened yet"
                description="Every inbound artifact is screened before any agent parses it. Run scenario S2 to watch a poisoned document be neutralized."
              />
            ) : (
              <ol className="flex flex-col">
                {guardrails.map((e) => <GuardrailEvent key={e.event_id} event={e} />)}
              </ol>
            )}
          </div>
        </Panel>

        <Panel
          title="Identity denials"
          className="min-h-0 rule-t"
          actions={
            <>
              <FeedMeta parts={[plural(denials.length, 'denial')]} />
              <Button
                onClick={probe}
                disabled={busy}
                tone="brass"
                variant="outlined"
                size="sm"
                title="Make the callback agent attempt a banking read; the tool boundary must refuse it"
              >
                Probe callback → banking read
              </Button>
            </>
          }
        >
          {error ? (
            <FeedError status={error} />
          ) : (
            <div className="flex flex-col">
              {probeError && (
                <div className="p-3 pb-0">
                  <Callout compact tone="amber"
                    icon={<AlertTriangle size={12} strokeWidth={1.75} aria-hidden />}>
                    {probeError}
                  </Callout>
                </div>
              )}
              <DataGrid
                label="Identity denials"
                density="dense"
                columns={DENIAL_COLUMNS}
                rows={denials}
                rowKey={(r) => r.event_id}
                rowRail={(r) => (r.event_id === landed ? 'animate-land' : undefined)}
                loading={loading}
                // Calibrated to the real feed: a probe produces one denial, a
                // full run a handful. A skeleton far taller than the data
                // merely relocates the collapse.
                skeletonRows={3}
                empty={
                  <NonIdealState
                    visual={<Ban size={22} strokeWidth={1.75} aria-hidden />}
                    title="No denials recorded"
                    description="Scopes are enforced at the tool boundary, not asserted in a prompt. Use the probe to make the callback agent attempt a banking read."
                  />
                }
              />
            </div>
          )}
        </Panel>
      </div>

      {/* ------------------------------------------------------ policy, fleet-wide
          Three rows here against the left column's two, so the horizontal rules no
          longer land on a shared y. That alignment held while both columns carried
          two claims about the fleet; the exchange is a third, and it belongs beside
          the other fleet-wide boundaries rather than interleaved with the case feed. */}
      <div className="grid min-h-0 grid-rows-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <ExchangePanel />
        <Panel
          title="Gateway routing"
          className="min-h-0 rule-t"
          actions={<FeedMeta parts={[plural(decisions.length, 'hop')]} />}
          footer={
            <>
              <span className="label-micro shrink-0">Hop policy</span>
              <MonoId truncate>{hopPolicy}</MonoId>
            </>
          }
        >
          {error ? (
            <FeedError status={error} />
          ) : (
            <div className="flex flex-col">
              {refused.length > 0 && (
                // The refusal is the only interesting string this pane can
                // produce, so it is rendered in full rather than truncated
                // into a cell and gated behind a hover title (N3).
                <div className="p-3 pb-0">
                  <Callout compact tone="amber"
                    icon={<Ban size={12} strokeWidth={1.75} aria-hidden />}
                    title={`${plural(refused.length, 'hop')} refused`}>
                    <ul className="flex flex-col gap-1">
                      {refused.map((d) => (
                        <li key={d.request_id} className="text-mini leading-[15px]">
                          {text(d.reason)}
                        </li>
                      ))}
                    </ul>
                  </Callout>
                </div>
              )}
              <DataGrid
                label="Gateway routing"
                density="dense"
                columns={GATEWAY_COLUMNS}
                rows={decisions}
                rowKey={(d) => d.request_id}
                rowRail={(d) => (d.allowed ? undefined : TONE_RAIL.amber)}
                loading={loading}
                skeletonRows={8}
                empty={
                  <NonIdealState
                    visual={<ArrowRight size={22} strokeWidth={1.75} aria-hidden />}
                    title="No routing decisions yet"
                    description="Specialists are leaves: the orchestrator may reach any of them, and none of them may reach each other."
                  />
                }
              />
            </div>
          )}
        </Panel>

        <Panel
          title="Fleet scope manifest"
          className="min-h-0 rule-t"
          actions={<FeedMeta parts={[plural(manifest.length, 'agent')]} />}
        >
          <div className="flex flex-col">
            {error ? (
              <FeedError status={error} />
            ) : loading ? (
              <ManifestSkeleton />
            ) : (
              manifest.map((row) => <ManifestRow key={row.agent} row={row} />)
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* ==========================================================================
   GUARDRAIL SCREENING — the frame this surface exists for.

   The event is a ROW, not a floating card: square left corners so the 2px
   amber rail terminates square and lands flush at the pane edge, and a
   hairline rule to the next row (§4).
   ========================================================================== */

function GuardrailEvent({ event }: { event: PostureEvent }) {
  const neutralizations = asArray<Neutralization>(event.neutralizations);
  const techniques = asArray<string>(event.techniques);

  // The de-duplicated technique list only tells you something the per-span
  // labels do not when it actually collapses two spans into one technique.
  const summarises = techniques.length > 0 && techniques.length !== neutralizations.length;

  return (
    <li className="rule-b-muted">
      <Callout
        className={cx(TONE_RAIL.amber, 'rounded-none!')}
        icon={<ShieldCheck size={16} strokeWidth={1.75} aria-hidden
          className="text-[var(--color-amber-text)]" />}
        title={
          <div className="flex flex-wrap items-baseline gap-2">
            <Pill tone="amber" minWidth={PILL_MIN}>neutralized</Pill>
            <span className="text-sm font-semibold text-[var(--color-ink)]">
              Inbound artifact screened
            </span>
            <span className="ml-auto flex items-baseline gap-2">
              <span className="label-micro">Scenario</span>
              <MonoId>{text(event.scenario_id)}</MonoId>
              <Divider vertical className="self-center" />
              <span className="label-micro">Artifact</span>
              <MonoId truncate>{text(event.request_id)}</MonoId>
              <Divider vertical className="self-center" />
              <Timestamp>{eventClock(event.occurred_at)}</Timestamp>
            </span>
          </div>
        }
      >
        <div className="mt-2 flex flex-col gap-3">
          {summarises && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="label-micro shrink-0">Techniques</span>
              {techniques.map((t) => (
                <Pill key={t} tone="neutral">{techniqueLabel(t)}</Pill>
              ))}
            </div>
          )}

          <ol className="flex flex-col gap-3">
            {neutralizations.map((n, i) => (
              <Evidence key={`${n.technique}-${n.location}-${n.offset}-${i}`} n={n} />
            ))}
          </ol>
        </div>
      </Callout>
    </li>
  );
}

/**
 * One removed span, reproduced verbatim.
 *
 * VERBATIM MEANS VERBATIM. The hidden-text payload carries a literal newline;
 * without `pre-wrap` the break collapses to a space and the artifact's actual
 * shape is destroyed on the one surface whose entire claim is fidelity. There
 * is no `ch` cap either — the pane is the constraint, and a magic cap was the
 * only thing forcing the wrap the strike then had to survive.
 *
 * The excerpt sits in a recess cut into the row — the specimen under glass —
 * at the same ink step as the rest of the record. Quotation marks sit OUTSIDE
 * the struck element, so the strike crosses the injected text and nothing
 * else, and `box-decoration-clone` keeps it drawn on every wrapped fragment.
 * `<del>` carries the "this was removed" meaning to assistive technology and
 * to anything that never renders the gradient (§7).
 */
function Evidence({ n }: { n: Neutralization }) {
  const flagged = FLAG_ONLY.has(n.technique);
  const character = CHARACTER_TECHNIQUES.has(n.technique);
  const Body = flagged ? 'span' : 'del';

  return (
    <li className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-xs text-[var(--color-ink)]">{techniqueLabel(n.technique)}</span>
        <span className="flex items-baseline gap-1.5">
          <span className="label-micro shrink-0">Location</span>
          <span className="text-mini text-[var(--color-ink-dim)]">
            {locationLabel(n.location)}
          </span>
        </span>
        <span className="flex items-baseline gap-1.5">
          <span className="label-micro shrink-0">Offset</span>
          <span data-numeric="" className="inline-block min-w-[6ch] text-right font-mono tabular
            text-mini text-[var(--color-ink-dim)]">
            {n.offset >= 0 ? `+${n.offset}` : EM_DASH}
          </span>
        </span>
        <span className="ml-auto">
          <Pill tone={flagged ? 'neutral' : 'amber'} minWidth={PILL_MIN}>
            {flagged ? 'flagged' : 'removed'}
          </Pill>
        </span>
      </div>

      {character ? (
        <>
          <p className="text-sm leading-[18px] text-[var(--color-ink)]">{text(n.detail)}</p>
          <span className="flex items-baseline gap-2">
            <span className="label-micro shrink-0">Character</span>
            <code className="rounded-[var(--radius-input)] bg-[var(--color-ground)] px-1.5
              font-mono text-sm leading-[18px] text-[var(--color-ink)]
              shadow-[var(--shadow-well)]">
              {n.excerpt}
            </code>
          </span>
        </>
      ) : (
        <>
          <blockquote className="rounded-[var(--radius-input)] bg-[var(--color-ground)] px-3 py-2
            shadow-[var(--shadow-well)]">
            <p className="whitespace-pre-wrap font-mono text-sm leading-[18px]
              text-[var(--color-ink)] [overflow-wrap:anywhere]">
              <span aria-hidden className="text-[var(--color-ink-faint)]">&ldquo;</span>
              <Body className={cx('no-underline box-decoration-clone', !flagged && 'struck')}>
                {n.excerpt}
              </Body>
              <span aria-hidden className="text-[var(--color-ink-faint)]">&rdquo;</span>
            </p>
          </blockquote>
          <p className="text-mini leading-[15px] text-[var(--color-ink-dim)]">{text(n.detail)}</p>
        </>
      )}
    </li>
  );
}

/* ==========================================================================
   SCOPE MANIFEST — rows, not cards (§4). Registry owns the agent record;
   this pane is the fleet-wide roll-up of the same grants.
   ========================================================================== */

function ManifestRow({ row }: { row: ScopeManifestRow }) {
  return (
    <div className="flex flex-col gap-2 rule-b-muted px-3 py-2">
      <div className="flex items-baseline gap-2">
        <span className="truncate text-xs font-medium text-[var(--color-ink)]">
          {agentName(row.agent)}
        </span>
        <span className="ml-auto shrink-0">
          <MonoId truncate>{row.policy_id}</MonoId>
        </span>
      </div>

      <ScopeManifest label="Granted" scopes={row.granted} />
      <ScopeManifest denied label="Denied" scopes={row.denied} />
    </div>
  );
}


/* ==========================================================================
   LOCAL CHROME

   `FeedMeta` and the two skeletons are local to this view: the inventory has
   no inline count-strip, and a skeleton can only be a geometric clone of the
   thing it stands in for, which is view-specific by definition. Noted in the
   report.
   ========================================================================== */

/**
 * Counts in the 30px pane header. These are VALUES, not labels, so they are
 * mono/tabular ink-dim rather than uppercase micro-labels (§8: the uppercase
 * treatment belongs to column headers, field labels and group headings, and
 * nowhere else).
 */
function FeedMeta({ parts }: { parts: string[] }) {
  return (
    <span className="flex items-center truncate">
      {parts.map((p, i) => (
        <span key={p} className="flex items-center">
          {i > 0 && <Divider vertical />}
          <span data-numeric=""
            className="font-mono tabular text-micro whitespace-nowrap text-[var(--color-ink-dim)]">
            {p}
          </span>
        </span>
      ))}
    </span>
  );
}

/**
 * The empty state and the ERROR state are different facts. An unreachable
 * backend must never render as "nothing to report" on a compliance surface.
 */
function FeedError({ status, onRetry }: { status: string; onRetry?: () => void }) {
  return (
    <NonIdealState
      tone="amber"
      visual={<AlertTriangle size={22} strokeWidth={1.75} aria-hidden />}
      title="Posture feed unavailable"
      description={`The posture API did not answer (${status}). Nothing on this surface is a statement about the fleet until it does.`}
      action={onRetry && (
        <Button size="sm" variant="outlined" tone="amber" onClick={onRetry}
          icon={<RefreshCw size={12} strokeWidth={1.75} aria-hidden />}>
          Retry
        </Button>
      )}
    />
  );
}

/**
 * Geometric clone of one GuardrailEvent carrying one Evidence row. Bar heights
 * are LINE BOXES, not spacing values, so the loading and loaded states occupy
 * the same pixels (§3, N4).
 */
function GuardrailSkeleton() {
  return (
    <div aria-hidden className="flex flex-col">
      <div className="flex flex-col gap-3 rule-b-muted p-4 pl-10">
        <div className="flex items-center gap-2">
          <SkeletonBar height={18} width="68px" />
          <SkeletonBar height={16} width="180px" />
          <span className="ml-auto flex items-center gap-2">
            <SkeletonBar height={16} width="96px" />
            <SkeletonBar height={16} width="128px" />
          </span>
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-3">
            <SkeletonBar height={16} width="132px" />
            <SkeletonBar height={14} width="148px" />
            <SkeletonBar height={14} width="72px" />
            <span className="ml-auto"><SkeletonBar height={18} width="68px" /></span>
          </div>
          <div className="rounded-[var(--radius-input)] bg-[var(--color-ground)] px-3 py-2
            shadow-[var(--shadow-well)]">
            <SkeletonBar height={18} width="86%" />
          </div>
          <SkeletonBar height={15} width="52%" />
        </div>
      </div>
    </div>
  );
}

/** Geometric clone of the manifest rows: name line, then two scope groups. */
function ManifestSkeleton() {
  return (
    <div aria-hidden className="flex flex-col">
      {Array.from({ length: 5 }, (_, i) => (
        <div key={i} className="flex flex-col gap-2 rule-b-muted px-3 py-2">
          <div className="flex items-center gap-2">
            <SkeletonBar height={16} width="112px" />
            <span className="ml-auto"><SkeletonBar height={16} width="120px" /></span>
          </div>
          <div className="flex flex-col gap-1">
            <SkeletonBar height={14} width="56px" />
            <div className="flex flex-wrap gap-1">
              <SkeletonBar height={18} width="164px" />
              <SkeletonBar height={18} width="96px" />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <SkeletonBar height={14} width="48px" />
            <div className="flex flex-wrap gap-1">
              <SkeletonBar height={18} width="132px" />
              <SkeletonBar height={18} width="108px" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
