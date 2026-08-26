import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { Surface } from './AppShell';

interface Command {
  id: string;
  label: string;
  group: string;
  run: () => void | Promise<unknown>;
}

/** ⌘K palette. Enterprise consoles are keyboard-first, and it keeps the recording
    free of mouse hunting. */
export function CommandPalette({
  onClose, onNavigate,
}: { onClose: () => void; onNavigate: (s: Surface) => void }) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const commands: Command[] = useMemo(() => [
    { id: 'go-console', group: 'Navigate', label: 'Go to Console', run: () => onNavigate('console') },
    { id: 'go-docket', group: 'Navigate', label: 'Go to Docket', run: () => onNavigate('docket') },
    { id: 'go-registry', group: 'Navigate', label: 'Go to Registry', run: () => onNavigate('registry') },
    { id: 'go-posture', group: 'Navigate', label: 'Go to Posture', run: () => onNavigate('posture') },
    { id: 'reset', group: 'Demo', label: 'Reset environment', run: api.demo.reset },
    { id: 's1', group: 'Demo', label: 'Inject S1 — lookalike domain, vendor denies', run: () => api.demo.inject('S1') },
    { id: 's2', group: 'Demo', label: 'Inject S2 — poisoned PDF', run: () => api.demo.inject('S2') },
    { id: 's3', group: 'Demo', label: 'Inject S3 — genuine but thin', run: () => api.demo.inject('S3') },
    { id: 's4', group: 'Demo', label: 'Inject S4 — delayed release', run: () => api.demo.inject('S4') },
    { id: 's5', group: 'Demo', label: 'Inject S5 — crash and resume', run: () => api.demo.inject('S5') },
    { id: 'clock', group: 'Demo', label: 'Advance clock 4 days', run: () => api.demo.advanceClock(4) },
    { id: 'kill', group: 'Demo', label: 'Kill in-flight runner', run: () => api.demo.kill() },
    { id: 'resume', group: 'Demo', label: 'Resume all non-terminal cases', run: () => api.demo.resume() },
    { id: 'scope', group: 'Security', label: 'Probe scope enforcement', run: api.demo.forceScopeViolation },
  ], [onNavigate]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? commands.filter((c) => c.label.toLowerCase().includes(q)) : commands;
  }, [commands, query]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, filtered.length - 1)); }
    if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    if (e.key === 'Enter') {
      e.preventDefault();
      const cmd = filtered[cursor];
      if (cmd) { void cmd.run(); onClose(); }
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-[rgb(17_24_39_/_0.28)] pt-[14vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-[540px] rounded-[var(--radius-overlay)] bg-[var(--color-overlay)]
          shadow-[var(--shadow-elev-3)]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Command palette"
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setCursor(0); }}
          onKeyDown={onKeyDown}
          placeholder="Run a command…"
          className="h-[var(--spacing-ctl-lg)] w-full rule-b bg-transparent px-3 text-sm text-[var(--color-ink)]
            placeholder:text-[var(--color-ink-faint)] focus:outline-none"
        />
        <ul className="max-h-[320px] overflow-y-auto py-1">
          {filtered.map((c, i) => (
            <li key={c.id}>
              <button
                type="button"
                onMouseEnter={() => setCursor(i)}
                onClick={() => { void c.run(); onClose(); }}
                className={`flex h-[var(--spacing-ctl-md)] w-full items-center gap-3 px-3 text-left text-xs
                  ${i === cursor ? 'bg-[var(--color-fill-brass)] text-[var(--color-ink)]' : 'text-[var(--color-ink-dim)]'}`}
              >
                <span className="label-micro w-[62px] shrink-0">{c.group}</span>
                <span className="truncate">{c.label}</span>
              </button>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="px-3 py-3 text-mini text-[var(--color-ink-faint)]">No matching command.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
