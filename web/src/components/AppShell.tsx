import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Activity, BookOpen, Boxes, ShieldCheck, Command as CommandIcon,
} from 'lucide-react';
import type { Health } from '@/lib/types';
import { useTenant } from '@/lib/tenant';
import { Divider, Dot, Kbd } from './primitives';

/* ============================================================================
   GLOBAL CHROME

   Implemented from context/UI_SPEC.md §13. Four bands, all fixed, none of
   which scroll:

     24px  synthetic-data banner   (a standing disclosure, not a toast)
     50px  navbar                  (left group | right group, 1px x 20px dividers)
     56px  navigation rail         (four targets; the only persistent nav)
     26px  status bar              (the persistent proof of liveness)

   Total vertical chrome 100px. At a 900px content box that leaves 800px of
   pane — 28 rows at 28px inside a pane with a 30px header. The hard floor is
   20 visible rows; under 15 the console reads as a toy.

   The navbar carries elevation 1 (a hairline ring plus a 1px drop and the
   top-edge sheen) so it sits ON the field rather than being cut out of it.
   Everything below it is flat: panes are rectangles separated by 1px lines,
   not floating cards on a background.

   The status bar is disproportionately valuable in a muted recording. It is
   a persistent, always-truthful, tabular readout that proves the system is
   live and quantified. A monotonically ticking counter costs nothing and is
   unfakeable evidence of liveness on video.
   ============================================================================ */

export type Surface = 'console' | 'docket' | 'registry' | 'posture';

const NAV: { id: Surface; label: string; icon: typeof Activity; hint: string }[] = [
  { id: 'console', label: 'Console', icon: Activity, hint: 'Live interdiction queue' },
  { id: 'docket', label: 'Docket', icon: BookOpen, hint: 'Case file and reasoning' },
  { id: 'registry', label: 'Registry', icon: Boxes, hint: 'Agent catalog' },
  { id: 'posture', label: 'Posture', icon: ShieldCheck, hint: 'Security events' },
];

/* Every agent that runs inside a case, in the order it runs. Red Team is absent on
   purpose: it attacks the fleet rather than joining it, and its readout is the
   scoreboard on Registry. */
const FLEET = [
  'sentry', 'callback', 'ledger', 'provenance', 'registry-check', 'challenger',
  'precedent-clerk', 'adjudicator', 'scribe', 'attribution', 'hunter',
];

export function AppShell({
  surface, onNavigate, health, activeAgents, sessionCount, children, onCommand,
}: {
  surface: Surface;
  onNavigate: (s: Surface) => void;
  health: Health | null;
  activeAgents: Set<string>;
  sessionCount: number;
  children: ReactNode;
  onCommand: () => void;
}) {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-[var(--color-ground)]">
      <SyntheticBanner />
      <Navbar onCommand={onCommand} />
      <div className="flex min-h-0 w-full flex-1 overflow-hidden">
        <NavRail surface={surface} onNavigate={onNavigate} />
        <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>
      <StatusBar health={health} activeAgents={activeAgents} sessionCount={sessionCount} />
    </div>
  );
}

/* --- 24px: standing disclosure ------------------------------------------- */

function SyntheticBanner() {
  return (
    <div
      className="flex h-[24px] shrink-0 items-center justify-center gap-2 rule-b
        bg-[var(--color-surface)] px-3"
    >
      <span className="label-brass shrink-0">Demonstration environment</span>
      <span className="truncate text-micro leading-none text-[var(--color-ink-faint)]">
        Every vendor, payment and message is synthetic — no real company, person or bank.
      </span>
    </div>
  );
}

/* --- 50px: the navbar ----------------------------------------------------- */

function Navbar({
  onCommand,
}: { onCommand: () => void }) {
  return (
    <header
      className="relative z-10 flex h-[50px] w-full shrink-0 items-center gap-0 bg-[var(--color-surface)]
        px-4 shadow-[var(--shadow-elev-1)]"
    >
      {/* left group */}
      <div className="flex h-[50px] shrink-0 items-center gap-3">
        <span className="font-display text-lg leading-[22px] font-semibold tracking-[-0.01em] text-[var(--color-ink)]">
          Interdict
        </span>
        {/* The district IS the treasury context, so it stands where the static
            "Treasury Controls" label used to: a label that names nothing the value
            beside it does not already say has not earned its place (D-020a). */}
        <TenantSwitcher />
      </div>

      <Divider vertical />

      {/* The eleven-name fleet strip that used to live here is gone.

          It was not interactive, and its information was already on screen twice whenever it
          mattered: the status bar reports `Fleet n/11`, and the Balance's lane strip names each
          running lane with a state meter and a latency. During the fan-out exactly four of the
          eleven dots changed — four tokens of signal framed by seven of noise, in the most
          valuable real estate in the application. It also consumed ~700px of a 50px navbar and
          was the first thing to clip mid-word at a narrow viewport.

          Fleet breadth is established properly by the Registry, which is the surface the demo
          opens on: a sortable catalogue with owners, versions and scope manifests. */}
      <div className="min-w-0 flex-1" />

      {/* right group — minimal controls only. Only a commit action is filled. */}
      <div className="flex h-[50px] shrink-0 items-center">
        <Divider vertical />
        <button
          type="button"
          onClick={onCommand}
          title="Command palette"
          className="inline-flex h-[24px] items-center gap-1.5 rounded-[var(--radius-ctl)] px-2
            text-micro text-[var(--color-ink-dim)]
            transition-colors duration-100 ease-[var(--ease-ui)]
            hover:bg-[var(--color-fill-neutral-strong)] hover:text-[var(--color-ink)]"
        >
          <CommandIcon aria-hidden size={11} strokeWidth={1.75} />
          <span>Command</span>
          <Kbd>⌘K</Kbd>
        </button>
      </div>
    </header>
  );
}

/**
 * WHICH DISTRICT. Two buttons, not a select: with a roster this small the whole
 * choice is readable at rest, and a muted recording shows both the district in
 * force and the one it could have been. A `select` would hide half of that behind
 * a click (N3).
 *
 * The control is 24px inside a 50px band and each option carries the district's
 * `short_name`, which the model caps at 12 characters for exactly this slot.
 */
function TenantSwitcher() {
  const { tenants, tenantId, select } = useTenant();
  if (tenants.length < 2) return null;

  return (
    <div
      role="radiogroup"
      aria-label="District"
      className="flex h-[24px] shrink-0 items-center rounded-[var(--radius-input)]
        bg-[var(--color-ground)] p-[2px] shadow-[var(--shadow-well)]"
    >
      {tenants.map((t) => {
        const active = t.tenant_id === tenantId;
        return (
          <button
            key={t.tenant_id}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => select(t.tenant_id)}
            title={`${t.display_name} — ${t.vendor_count} vendors`}
            className={`flex h-[20px] shrink-0 items-center rounded-[var(--radius-pill)] px-2
              text-micro font-semibold uppercase tracking-[0.08em]
              transition-colors duration-100 ease-[var(--ease-ui)]
              ${active
                ? 'bg-[var(--color-fill-brass-strong)] text-[var(--color-brass-text)]'
                : 'text-[var(--color-ink-faint)] hover:text-[var(--color-ink-dim)]'}`}
          >
            {t.short_name}
          </button>
        );
      })}
    </div>
  );
}

/* --- 56px: the rail ------------------------------------------------------- */

function NavRail({ surface, onNavigate }: { surface: Surface; onNavigate: (s: Surface) => void }) {
  return (
    <nav
      aria-label="Primary"
      className="flex w-[56px] shrink-0 flex-col items-stretch gap-px rule-r bg-[var(--color-surface)] py-2"
    >
      {NAV.map(({ id, label, icon: Icon, hint }) => {
        const active = surface === id;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onNavigate(id)}
            title={`${label} — ${hint}`}
            aria-current={active ? 'page' : undefined}
            className={`flex h-[50px] w-full flex-col items-center justify-center gap-1
              border-l-2 transition-colors duration-100 ease-[var(--ease-ui)]
              ${active
                ? 'border-[var(--color-brass)] bg-[var(--color-raised)] text-[var(--color-brass-text)]'
                : 'border-transparent text-[var(--color-ink-faint)] hover:bg-[var(--color-fill-neutral)] hover:text-[var(--color-ink-dim)]'}`}
          >
            <Icon aria-hidden size={16} strokeWidth={1.75} />
            <span className="text-micro font-medium leading-none tracking-[0.02em]">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}

/* --- 26px: the status bar ------------------------------------------------- */

function StatusBar({
  health, activeAgents, sessionCount,
}: { health: Health | null; activeAgents: Set<string>; sessionCount: number }) {
  const heartbeat = useHeartbeat(health);
  const running = activeAgents.size;

  return (
    <footer
      className="flex h-[26px] w-full shrink-0 items-center gap-3 rule-t bg-[var(--color-surface)] px-3"
      aria-label="System status"
    >
      <span className="flex shrink-0 items-center gap-1.5">
        <Dot tone={health?.ok ? 'verdigris' : 'amber'} live={!!health?.ok} />
        <span className="label-micro">{health?.ok ? 'Live' : 'Reconnecting'}</span>
      </span>

      <Divider vertical />

      {/* A monotonically counting number is unfakeable evidence of liveness on
          a muted video, and it costs nothing. */}
      <span className="font-mono text-mini text-[var(--color-ink-faint)]">{heartbeat}</span>
      <Stat label="Sessions" value={String(sessionCount)} />
      <Stat label="Fleet" value={`${running}/${FLEET.length}`} />

      <span className="min-w-0 flex-1" />

      {/* Was three labels for three single words. The values are self-describing in
          combination, so they run as one line and the labels come back only if that stops
          being true. */}
      <span className="font-mono text-mini text-[var(--color-ink-faint)]">
        {[health?.mode, health?.platform,
          health?.synthetic_data === false ? 'live data' : 'synthetic data']
          .filter(Boolean).join(' · ')}
      </span>
    </footer>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      <span className="label-micro">{label}</span>
      <span className="font-mono tabular text-mini leading-none text-[var(--color-ink-dim)]" data-numeric="">
        {value}
      </span>
    </span>
  );
}

/**
 * "updated 0.4s ago", ticking at 10Hz against the last successful health
 * read. Tabular figures, so the number never changes width as it counts.
 */
function useHeartbeat(health: Health | null): string {
  const stamp = useMemo(() => Date.now(), [health]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(id);
  }, []);

  const seconds = Math.max(0, (now - stamp) / 1000);
  return seconds < 60 ? `${seconds.toFixed(1)}s ago` : `${Math.floor(seconds / 60)}m ago`;
}

/**
 * ⌘K palette. Enterprise consoles are keyboard-first; this also keeps the
 * recording free of mouse hunting on camera. On a muted screen recording the
 * palette is the narrator — the typed query is readable text that explains
 * the operator's intent without audio.
 */
export function useCommandPalette() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return { open, setOpen };
}
