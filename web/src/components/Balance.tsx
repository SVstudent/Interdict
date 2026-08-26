import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Check, Minus, X } from 'lucide-react';
import type { CaseDetail, Finding } from '@/lib/types';
import { agentLabel, clock, outcomeWord, signalLabel } from '@/lib/format';
import {
  ConfidenceBar, Dot, Latency, OUTCOME_TONE, Pill, ProgressBar, SectionHeader,
  TONE_SOLID, TONE_TEXT, TONE_VAR, VERDICT_TONE, type Tone,
} from './primitives';

/* ============================================================================
   THE BALANCE

   Implemented from context/UI_SPEC.md. The active case renders as a literal
   balance: a column standing on a base, a fulcrum, a beam pivoting on it, and
   a pan hanging from each arm. Findings land in the pans as weights sized by
   confidence, and slot into the rail below as legible chips — contradicting
   left, supporting right, inconclusive in a neutral stack that touches
   neither pan.

   WHAT THE NUMBER MEANS. Exactly one arithmetic, and every term of it comes
   from the backend:

       against = SUM of confidence over contradicting findings NOT rebutted
       towards = SUM of confidence over supporting findings
       net     = against - towards

   Nothing is invented, nothing is scaled by a magic constant, and the two pan
   readouts sum to the index plate by construction. A judge who asks "what is
   +1.34?" gets an answer that can be checked against /api/cases/{id}.

   THE CHALLENGER. The steelman is an ARGUMENT, not a weight, so it does not
   stand on a pan — it acts through its rebuttals. A rebuttal that succeeds
   lifts its contradicting finding off the pan entirely (the bar leaves the
   pan, the chip is struck and marked "Rebutted", the beam tips toward
   release). A rebuttal that is defeated leaves the contradiction standing.
   That is the demo, and now it is also the truth.

   GEOMETRY (all fixed; nothing here resizes when an SSE frame lands)

     30px  section header — "Verification lanes"
     48px  lane strip, one cell per lane
     24px  pan captions (static; a caption that moves with the pan is noise)
    176px  the apparatus — beam, fulcrum, arms, pans, index plate
      1fr  the rail and the finding chips (the only thing that scrolls)
    128px  the verdict

   THE TIP. The beam rotates about the fulcrum; each arm carries its pan, and
   each pan counter-rotates about its own suspension point so it hangs level —
   which is what a real balance does and is why the numbers stay readable at
   exactly the moment they matter. Both transforms use the same 900ms
   var(--ease-tip), so they cannot desynchronise. Tilt saturates through a
   tanh, so a large net never clips to a hard stop: the instrument settles, it
   does not slam.

   COLOUR. --oxblood appears here on contradicting findings and on BLOCK, and
   nowhere else. The apparatus is brass throughout, because the apparatus is
   structure — and structure at 2.3:1 does not survive H.264, so the column,
   the fulcrum, the cords and the base plate are full brass and hierarchy is
   carried by WEIGHT (6px beam against a 1px column) rather than by a 2:1
   colour step.

   DEVIATION LEDGER (values off the §1 spacing ramp, all in this file).
   These are instrument geometry, not layout rhythm, and each is here because
   the ramp tops out at 48px while the apparatus is a drawing:
     176px  apparatus band     the minimum that fits beam + cord + pan + readout
     168px  arm span           2 x the 84px half-span the cord needs to clear
      56px  cord drop          the visible travel that makes a tip legible
     128px  pan width, verdict band
     104px  chip minimum column
   They need §16 rows in UI_SPEC.md; that file is not owned here.
   ============================================================================ */

/** The lanes the fleet always runs. Anything else the stream reports is
    appended rather than dropped, so the "N/M complete" caption can never lie. */
const BASE_LANES: string[] = ['provenance', 'ledger', 'registry-check', 'callback'];

/** Degrees. Five is an instrument settling; twelve is a playground see-saw. */
const MAX_TILT = 5;

/** Net is measured in confidence units, so the saturation scale is one unit:
    a single full-confidence unrebutted finding reads as 76% of full tilt. */
const TILT_SCALE = 1;

/** The beam element is half the pane wide and centred, so each suspension
    point hangs at ±25% of the pane — which is the centre of each finding
    column, since the two columns split the pane down the rail. */
const BEAM_WIDTH = '50%';

const TIP_TRANSITION = 'transform 900ms var(--ease-tip)';

/** Timestamps are meaningless on an audit surface without a zone, and the
    zone is stated once per band rather than once per row (§12). */
/* The tone tables, the zone and every enum-to-prose map are imported, never
   restated. A second declaration site for the oxblood token is how a colour
   rule that is load-bearing quietly stops being true. */

/** elevation 0 plus a 2px rail on the edge that faces the balance rail.
    Drawn INSIDE the chip, so a rail can never change a chip's size. */
const chipShadow = (tone: Tone, side: ChipSide): string =>
  side === 'centre'
    ? 'var(--shadow-elev-0)'
    : `var(--shadow-elev-0), inset ${side === 'left' ? '-2px' : '2px'} 0 0 0 var(${TONE_VAR[tone]})`;

export interface LaneState {
  agent: string;
  status: 'idle' | 'running' | 'done' | 'failed';
  latencyMs?: number;
  /** The backend writes a human-readable reason on `lane_failed`. Showing a
      lane as failed without saying why is a dead end on a muted recording. */
  error?: string;
}

interface Props {
  detail: CaseDetail | null;
  lanes: Record<string, LaneState>;
  challengeLanded: boolean;
}

/** One thing standing on a pan. `bar` is how wide it draws; its weight is the
    finding's confidence, which is already summed into the pan readout. */
interface Load {
  id: string;
  bar: number;
  tone: Tone;
}

type ChipSide = 'left' | 'right' | 'centre';

/**
 * The whole arithmetic of the instrument, from backend values only.
 * Positive net tips toward BLOCK (left), negative toward RELEASE (right).
 */
function weigh(findings: Finding[], rebutted: Set<string>) {
  let against = 0;   // contradicts, not rebutted — pushes toward block
  let towards = 0;   // supports — pushes toward release

  for (const f of findings) {
    if (f.verdict === 'contradicts') {
      if (!rebutted.has(f.finding_id)) against += f.confidence;
    } else if (f.verdict === 'supports') {
      towards += f.confidence;
    }
  }
  return { against, towards, net: against - towards };
}

export function Balance({ detail, lanes, challengeLanded }: Props) {
  const findings = detail?.findings ?? [];
  const challenge = detail?.challenge ?? null;
  const decision = detail?.decision ?? null;

  const rebutted = useMemo(
    () => new Set((challenge?.rebuttals ?? []).filter((r) => r.succeeds).map((r) => r.finding_id)),
    [challenge],
  );

  const { against, towards, net } = useMemo(
    () => weigh(findings, rebutted),
    [findings, rebutted],
  );

  // tanh saturates instead of clipping, so the beam never reads as jammed
  // against a hard stop — it eases toward its limit the way a damped arm does.
  const tilt = MAX_TILT * Math.tanh(net / TILT_SCALE);

  // One frame at level, then the settle. Selecting a case therefore plays the
  // instrument finding its balance rather than snapping to an answer.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    setSettled(false);
    let inner = 0;
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => setSettled(true));
    });
    return () => {
      window.cancelAnimationFrame(outer);
      window.cancelAnimationFrame(inner);
    };
  }, [detail?.case_id]);

  const contradicting = findings.filter((f) => f.verdict === 'contradicts');
  const supporting = findings.filter((f) => f.verdict === 'supports');
  const inconclusive = findings.filter((f) => f.verdict === 'inconclusive');

  // Only what is actually weighed stands on a pan. A rebutted contradiction
  // has been lifted off the instrument; an inconclusive finding never got on.
  const leftLoad: Load[] = contradicting
    .filter((f) => !rebutted.has(f.finding_id))
    .map((f) => ({
      id: f.finding_id,
      bar: 40 + Math.round(f.confidence * 64),
      tone: VERDICT_TONE[f.verdict],
    }));

  const rightLoad: Load[] = supporting.map((f) => ({
    id: f.finding_id,
    bar: 40 + Math.round(f.confidence * 64),
    tone: VERDICT_TONE[f.verdict],
  }));

  const laneRows = useMemo(() => {
    const extra = Object.keys(lanes).filter((a) => !BASE_LANES.includes(a)).sort();
    return [...BASE_LANES, ...extra].map(
      (agent) => lanes[agent] ?? { agent, status: 'idle' as const },
    );
  }, [lanes]);
  const laneDone = laneRows.filter((l) => l.status === 'done').length;
  const laneRunning = laneRows.some((l) => l.status === 'running');

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto pane-scroll">
      <SectionHeader
        title="Verification lanes"
        actions={
          <>
            {/* THE one indeterminate sweep on this surface: the fan-out as a
                whole, not one per lane. The slot is always reserved. */}
            <span className="inline-block h-[2px] w-16 shrink-0">
              {laneRunning && (
                <ProgressBar indeterminate tone="brass" label="Verification fan-out in flight" />
              )}
            </span>
            <span className="text-mini text-[var(--color-ink-dim)]">
              <span data-numeric="" className="font-mono">{laneDone}</span>
              <span className="text-[var(--color-ink-faint)]">/</span>
              <span data-numeric="" className="font-mono">{laneRows.length}</span>
              {' complete'}
            </span>
          </>
        }
      />

      <LaneStrip rows={laneRows} />

      {/* Captions are static. A label that travels with its pan is unreadable
          at exactly the moment the pan is moving — and these two words are the
          only thing that tells a muted viewer what the beam means, so they are
          brass (6.5:1), not micro-faint (3.4:1). */}
      <div className="relative h-[24px] shrink-0" aria-hidden>
        <span className="absolute left-0 top-[6px] w-1/2 text-center label-brass">Contradicts</span>
        <span className="absolute right-0 top-[6px] w-1/2 text-center label-brass">Supports</span>
      </div>

      <Apparatus
        tilt={settled ? tilt : 0}
        net={net}
        against={against}
        towards={towards}
        leftLoad={leftLoad}
        rightLoad={rightLoad}
      />

      <div className="relative shrink-0">
        {/* The rail: the column the beam stands on, running the full drop. */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2
            bg-[var(--color-brass)]"
          style={{ minHeight: '120px' }}
        />
        <span
          aria-hidden
          className="pointer-events-none absolute bottom-0 left-1/2 h-[2px] w-12 -translate-x-1/2
            bg-[var(--color-brass)]"
        />

        <div className="px-4 pb-4 pt-3">
          <div className="grid grid-cols-2 gap-x-8">
            <div className="flex min-w-0 flex-col items-end gap-2">
              {contradicting.map((f) => (
                <FindingChip
                  key={f.finding_id}
                  finding={f}
                  side="left"
                  rebutted={rebutted.has(f.finding_id)}
                />
              ))}
              {contradicting.length === 0 && (
                <PanNote>{detail ? 'Nothing contradicting' : 'No case selected'}</PanNote>
              )}
            </div>

            <div className="flex min-w-0 flex-col items-start gap-2">
              {supporting.map((f) => (
                <FindingChip key={f.finding_id} finding={f} side="right" rebutted={false} />
              ))}
              {challengeLanded && challenge && <SteelmanBlock challenge={challenge} />}
              {supporting.length === 0 && !challengeLanded && (
                <PanNote>{detail ? 'Nothing supporting' : 'No case selected'}</PanNote>
              )}
            </div>

            {/* Inconclusive findings touch neither pan. They are reported in
                full and weigh nothing, which is exactly what the number above
                already says. */}
            {inconclusive.length > 0 && (
              <div className="col-span-2 mt-3 flex flex-col items-center gap-2">
                <span className="label-micro">Inconclusive</span>
                {inconclusive.map((f) => (
                  <FindingChip key={f.finding_id} finding={f} side="centre" rebutted={false} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <Verdict decision={decision} />
    </div>
  );
}

/** A pan that has taken no load still has to say so. Silence on one side of a
    balance is information, and on a muted recording it must be written down.
    A note is a sentence, not an object: no ring, no fill — panes are
    rectangles separated by rules, not floating cards (§4). */
function PanNote({ children }: { children: ReactNode }) {
  return (
    <span className="flex h-[24px] items-center text-mini text-[var(--color-ink-dim)]">
      {children}
    </span>
  );
}

/* --- lanes ---------------------------------------------------------------
   Fixed cardinality: one cell per lane, changing state IN PLACE. Nothing
   mounts or unmounts for the whole run, so the strip has zero layout shift.
   The meter is a four-step STATE meter, not a measured fraction: idle draws
   nothing, running is half, failed stops short, complete fills. That way
   running and complete are still distinguishable in grayscale, and a failed
   lane can never be mistaken for a finished one. */

const LANE_TONE: Record<LaneState['status'], Tone> = {
  idle: 'neutral',
  running: 'brass',
  done: 'verdigris',
  failed: 'amber',
};

const LANE_TEXT: Record<LaneState['status'], string> = {
  idle: 'Idle',
  running: 'Verifying…',
  done: 'Complete',
  failed: 'Lane failed',
};

const LANE_METER: Record<LaneState['status'], string> = {
  idle: '0%',
  running: '50%',
  failed: '25%',
  done: '100%',
};

function LaneStrip({ rows }: { rows: LaneState[] }) {
  return (
    <div
      className="grid shrink-0 rule-b"
      style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}
    >
      {rows.map((lane, i) => {
        const tone = LANE_TONE[lane.status];
        const failed = lane.status === 'failed';
        const note = failed ? (lane.error ?? LANE_TEXT.failed) : LANE_TEXT[lane.status];
        return (
          <div
            key={lane.agent}
            className={`relative flex h-[48px] min-w-0 flex-col justify-center gap-[2px] px-3
              ${i < rows.length - 1 ? 'rule-r' : ''}`}
          >
            <span className="flex min-w-0 items-center gap-2">
              {/* A fixed 16px glyph slot, so the lane name never moves when the
                  status changes. Failed gets its own glyph — amber alone is
                  indistinguishable from held/awaiting at 1080p. */}
              <span className="flex w-4 shrink-0 items-center">
                {failed
                  ? <X aria-hidden size={11} strokeWidth={2.5} className={TONE_TEXT[tone]} />
                  : <Dot tone={tone} />}
              </span>
              <span className="truncate text-mini font-medium text-[var(--color-ink)]">
                {agentLabel(lane.agent)}
              </span>
              <span className="ml-auto shrink-0">
                {lane.status === 'done' && lane.latencyMs !== undefined
                  ? <Latency ms={lane.latencyMs} />
                  : (
                    <span
                      data-numeric=""
                      className="inline-block min-w-[6ch] text-right font-mono text-mini
                        text-[var(--color-ink-disabled)]"
                    >
                      —
                    </span>
                  )}
              </span>
            </span>

            <span
              title={note}
              className={`truncate text-mini ${
                failed ? TONE_TEXT[tone] : 'text-[var(--color-ink-dim)]'
              }`}
            >
              {note}
            </span>

            {/* 2px state meter. The track is transparent: a filled track sitting
                on the strip's own bottom rule draws a 3px double rule at rest. */}
            <span aria-hidden className="absolute inset-x-0 bottom-0 h-[2px] overflow-hidden">
              <span
                className={`block h-full transition-[width] duration-200 ease-[var(--ease-ui)]
                  ${TONE_SOLID[tone]}`}
                style={{ width: LANE_METER[lane.status] }}
              />
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* --- the apparatus -------------------------------------------------------
   Geometry, top-down inside the 176px band:
     y=32  beam top (6px deep) — so the centre of rotation is y=35
     y=35  fulcrum apex, exactly under the centre of rotation
     y=44  the column starts, running to the base of the band
   The pivot dot is a CHILD of the beam at its own centre, which is the one
   point of the beam that does not move — so there is no second absolute
   offset one pixel away from the fulcrum's. */

function Apparatus({
  tilt, net, against, towards, leftLoad, rightLoad,
}: {
  tilt: number;
  net: number;
  against: number;
  towards: number;
  leftLoad: Load[];
  rightLoad: Load[];
}) {
  // The beam turns one way; each pan turns back the same amount about its own
  // suspension point, so it hangs level. Same duration, same curve, no drift.
  const beam: CSSProperties = {
    width: BEAM_WIDTH,
    transform: `translateX(-50%) rotate(${-tilt}deg)`,
    transformOrigin: 'center',
    transition: TIP_TRANSITION,
  };
  const upright: CSSProperties = {
    transform: `translateX(-50%) rotate(${tilt}deg)`,
    transformOrigin: 'top center',
    transition: TIP_TRANSITION,
  };

  const reading = net > 0.15 ? 'Tipping to block'
    : net < -0.15 ? 'Tipping to release'
      : 'In balance';

  return (
    <div className="relative h-[176px] shrink-0 no-shift">
      <div
        role="img"
        aria-label={`Balance. Contradicting weight ${against.toFixed(2)} from ${leftLoad.length} findings, supporting weight ${towards.toFixed(2)} from ${rightLoad.length} findings. ${reading}.`}
        className="absolute inset-0"
      >
        {/* the column, standing under the fulcrum */}
        <span
          aria-hidden
          className="absolute bottom-0 left-1/2 top-[44px] w-px -translate-x-1/2 bg-[var(--color-brass)]"
        />
        {/* the fulcrum: a knife edge, apex under the beam's centre of rotation */}
        <span
          aria-hidden
          style={{ clipPath: 'polygon(50% 0, 100% 100%, 0 100%)' }}
          className="absolute left-1/2 top-[35px] h-[12px] w-[20px] -translate-x-1/2 bg-[var(--color-brass)]"
        />

        {/* The beam. Tapered rather than a plain rule: a balance beam is deep at
            the fulcrum and fines away to a point at each suspension, and that
            silhouette is what makes the instrument read as an instrument. */}
        <div aria-hidden style={beam} className="absolute left-1/2 top-[32px] h-[6px]">
          {/* the beam's own silhouette; kept as a child so its clip-path cannot
              crop the arms hanging off the ends */}
          <span
            style={{ clipPath: 'polygon(0 50%, 12px 0, calc(100% - 12px) 0, 100% 50%, calc(100% - 12px) 100%, 12px 100%)' }}
            className="absolute inset-0 bg-[var(--color-brass)]"
          />
          {/* the pivot, riding the one point of the beam that never travels */}
          <span
            className="absolute left-1/2 top-1/2 h-[3px] w-[3px] -translate-x-1/2 -translate-y-1/2
              rounded-[var(--radius-pill)] bg-[var(--color-ink)]"
          />
          <Arm side="left" style={upright} load={leftLoad} weight={against} />
          <Arm side="right" style={upright} load={rightLoad} weight={towards} />
        </div>
      </div>

      {/* The index plate, sitting on the column. It states the definition of
          its own number, because a headline figure whose derivation is not on
          screen is a figure nobody can check. */}
      <div
        role="status"
        className="absolute bottom-0 left-1/2 flex -translate-x-1/2 flex-col items-center
          bg-[var(--color-ground)] px-2"
      >
        <span className="flex items-center gap-2">
          <span className="label-brass whitespace-nowrap">{reading}</span>
          <span data-numeric="" className="font-mono text-mini text-[var(--color-ink)]">
            {net > 0 ? '+' : ''}{net.toFixed(2)}
          </span>
        </span>
      </div>
    </div>
  );
}

/**
 * One arm: a suspension point on the beam, a cord, the load standing on the
 * pan, the pan itself, and the readout under it. The whole group counter-
 * rotates about the suspension point, which is what keeps the pan level.
 *
 * The readout counts exactly what the number above it sums, so "3 weighed"
 * and "2.41" can never disagree, and the two arms sum to the index plate.
 */
function Arm({
  side, style, load, weight,
}: { side: 'left' | 'right'; style: CSSProperties; load: Load[]; weight: number }) {
  return (
    <div className={`absolute top-1/2 ${side === 'left' ? 'left-0' : 'right-0'}`}>
      {/* suspension pivot */}
      <span
        aria-hidden
        className="absolute left-0 top-0 h-[6px] w-[6px] -translate-x-1/2 -translate-y-1/2 rotate-45
          bg-[var(--color-brass)]"
      />

      <div style={style} className="absolute left-0 top-0 w-[168px]">
        {/* cord, with the load standing on the pan in front of it */}
        <div className="relative h-[56px]">
          <span
            aria-hidden
            className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-[var(--color-brass)]"
          />
          <div className="absolute bottom-0 left-0 flex w-full flex-col-reverse items-center gap-[2px]">
            {load.map((l) => (
              <span
                key={l.id}
                className={`animate-slot block h-[4px] shrink-0 rounded-[var(--radius-pill)]
                  ${TONE_SOLID[l.tone]}`}
                style={{ width: `${l.bar}px` }}
              />
            ))}
          </div>
        </div>

        {/* the pan: a shallow dish seen edge-on, so the load visibly rests IN it */}
        <div aria-hidden className="relative h-[6px]">
          <span
            style={{ clipPath: 'polygon(0 0, 100% 0, calc(100% - 6px) 100%, 6px 100%)' }}
            className="absolute left-1/2 top-0 h-[6px] w-[128px] -translate-x-1/2 bg-[var(--color-brass)]"
          />
        </div>

        <div className="mt-2 flex flex-col items-center gap-[2px]">
          <span
            data-numeric=""
            className="font-mono text-xl font-medium leading-none text-[var(--color-ink)]"
          >
            {weight.toFixed(2)}
          </span>
          <span className="whitespace-nowrap text-mini text-[var(--color-ink-dim)]">
            <span data-numeric="" className="font-mono">{load.length}</span> weighed
          </span>
        </div>
      </div>
    </div>
  );
}

/* --- chips ---------------------------------------------------------------
   A chip is sized by confidence, so a 0.94 finding is visibly heavier than a
   0.60 one before a single character is read. It carries a 2px rail on the
   edge facing the balance rail plus a 16px tick joining it, so the slot it
   occupies is unambiguous even in grayscale.

   The body is the agent's WRITTEN finding. The signal enum is a field label
   above it, never the sentence itself. */

function FindingChip({
  finding, side, rebutted,
}: { finding: Finding; side: ChipSide; rebutted: boolean }) {
  const tone = VERDICT_TONE[finding.verdict];
  const Icon = finding.verdict === 'contradicts' ? X
    : finding.verdict === 'supports' ? Check : Minus;

  const width = 62 + Math.round(finding.confidence * 38);
  const mirror = side === 'left';

  return (
    <article
      style={side === 'centre' ? undefined : { width: `${width}%`, boxShadow: chipShadow(tone, side) }}
      className={`animate-slot relative rounded-[var(--radius-ctl)] bg-[var(--color-surface)] px-3 py-2
        ${side === 'centre'
          ? 'w-full max-w-[520px] shadow-[var(--shadow-elev-0)]'
          : `after:absolute after:top-4 after:h-px after:w-4 after:bg-[var(--color-rule-strong)]
             after:content-[''] ${mirror ? 'after:right-[-16px]' : 'after:left-[-16px]'}`}`}
    >
      <header className={`flex min-w-0 items-center gap-2 ${mirror ? 'flex-row-reverse' : ''}`}>
        <Icon aria-hidden size={11} strokeWidth={2.5} className={`shrink-0 ${TONE_TEXT[tone]}`} />
        <span className="min-w-0 truncate text-mini font-semibold text-[var(--color-ink)]">
          {agentLabel(finding.agent)}
        </span>
        {/* Rebutted is a state, so it is a token — never a dimming. At 50%
            opacity the beat that matters most becomes the least readable
            thing on the surface. */}
        {rebutted && <Pill tone="neutral" minWidth={68}>Rebutted</Pill>}
        <span className={mirror ? 'mr-auto' : 'ml-auto'}>
          <ConfidenceBar value={finding.confidence} tone={tone} />
        </span>
      </header>

      {/* The signal reads as a subtitle. It does not need a "Signal ·" label to say so. */}
      <p className={`mt-[2px] truncate text-mini text-[var(--color-ink-dim)] ${mirror ? 'text-right' : ''}`}>
        {signalLabel(finding.signal)}
      </p>

      <p
        className={`mt-1 line-clamp-2 text-xs text-[var(--color-ink-muted)]
          ${mirror ? 'text-right' : ''}
          ${rebutted ? 'line-through decoration-[var(--color-ink-faint)]' : ''}`}
      >
        {finding.reasoning}
      </p>
    </article>
  );
}

/**
 * The steelman — the strongest legitimate explanation for the change. It is an
 * ARGUMENT, not a weight: it never stands on a pan. It acts through its
 * rebuttals, and a rebuttal that lands lifts a contradiction off the
 * contradicting pan, which is what tips the beam.
 *
 * A rebuttal that is defeated is struck through in neutral ink — a defeated
 * argument is not money being stopped, and --oxblood may not appear here.
 */
function SteelmanBlock({ challenge }: { challenge: NonNullable<CaseDetail['challenge']> }) {
  const upheld = challenge.rebuttals.filter((r) => r.succeeds).length;
  const defeated = challenge.rebuttals.length - upheld;
  return (
    <article
      style={{ boxShadow: chipShadow('brass', 'right') }}
      className="animate-slot relative w-full rounded-[var(--radius-ctl)] bg-[var(--color-surface)] px-3 py-2
        after:absolute after:left-[-16px] after:top-4 after:h-px after:w-4
        after:bg-[var(--color-rule-strong)] after:content-['']"
    >
      <header className="flex items-center gap-2">
        <span className="label-brass truncate">Challenger · steelman</span>
        <span className="ml-auto shrink-0">
          <Pill tone={challenge.survived ? 'verdigris' : 'neutral'} minWidth={68}>
            {challenge.survived ? 'Survived' : 'Defeated'}
          </Pill>
        </span>
      </header>

      <p className="mt-1 line-clamp-3 text-xs text-[var(--color-ink-muted)]">
        {challenge.strongest_legitimate_explanation}
      </p>

      {/* A tally, not a transcript. Every rebuttal in full is one click away in the Docket. */}
      <p className="mt-1.5 text-mini text-[var(--color-ink-dim)]">
        {challenge.rebuttals.length} rebuttal{challenge.rebuttals.length === 1 ? '' : 's'}
        {upheld > 0 && (
          <>
            {' · '}
            <span className="text-[var(--color-verdigris-text)]">{upheld} upheld</span>
          </>
        )}
        {defeated > 0 && <>{' · '}{defeated} defeated</>}
      </p>

    </article>
  );
}

/* --- verdict --------------------------------------------------------------
   128px reserved whether or not a decision exists, so the adjudication landing
   moves nothing. Fifty-two pixels of display type is one of exactly two
   elements on this screen permitted above 28px. */

function Verdict({ decision }: { decision: CaseDetail['decision'] }) {
  if (!decision) {
    return (
      <div
        aria-live="polite"
        className="rule-t mt-2 flex shrink-0 flex-col items-center justify-center gap-2 py-6 no-shift"
      >
        <span className="label-micro">Awaiting adjudication</span>
        <span className="font-display text-2xl leading-none text-[var(--color-ink-dim)]">
          Pending
        </span>
      </div>
    );
  }

  const tone = OUTCOME_TONE[decision.outcome];
  const who = decision.decided_by === 'human'
    ? (decision.human_reviewer ?? 'a human reviewer')
    : 'the agent fleet';

  return (
    <div
      aria-live="polite"
      className="rule-t mt-2 flex shrink-0 flex-col items-center justify-center gap-2 px-4 py-6 no-shift"
    >
      <span
        className={`font-display text-verdict leading-none tracking-[-0.02em] ${TONE_TEXT[tone]}`}
      >
        {outcomeWord(decision.outcome)}
      </span>
      <p className="line-clamp-2 max-w-[72ch] text-center text-xs text-[var(--color-ink-muted)]">
        {decision.rationale}
      </p>
      {/* One quiet provenance line. The four labelled stats that were here competed with a
          52px verdict for the same glance; the detail lives on the Docket, which is where an
          auditor goes for it. */}
      <p className="text-mini text-[var(--color-ink-faint)]">
        {who} · {Math.round(decision.confidence * 100)}% confidence
        {decision.dissenting_findings.length > 0 &&
          ` · ${decision.dissenting_findings.length} dissenting`}
        {' · '}{clock(decision.decided_at)}
      </p>
    </div>
  );
}
