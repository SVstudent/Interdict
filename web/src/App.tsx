import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import type { Health } from '@/lib/types';
import { useEvents } from '@/lib/useEvents';
import { TenantProvider } from '@/lib/tenant';
import { AppShell, useCommandPalette, type Surface } from '@/components/AppShell';
import { Console } from '@/views/Console';
import { Docket } from '@/views/Docket';
import { Posture } from '@/views/Posture';
import { Registry } from '@/views/Registry';
import { CommandPalette } from '@/components/CommandPalette';

export default function App() {
  const [surface, setSurface] = useState<Surface>('console');
  const [selectedCase, setSelectedCase] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const { events, connected, push } = useEvents();
  const { open, setOpen } = useCommandPalette();

  useEffect(() => {
    const load = () => void api.health().then(setHealth).catch(() => setHealth(null));
    load();
    const id = window.setInterval(load, 10_000);
    return () => window.clearInterval(id);
  }, []);

  // Which agents are mid-flight right now, for the header health strip.
  const activeAgents = useMemo(() => {
    const running = new Set<string>();
    for (const e of events) {
      const agent = String((e.data as Record<string, unknown>).agent ?? '');
      if (!agent) continue;
      if (e.event === 'lane_started') running.add(agent);
      if (e.event === 'finding_added' || e.event === 'lane_failed') running.delete(agent);
    }
    return running;
  }, [events]);

  const sessionCount = useMemo(
    () => new Set(events.filter((e) => e.event === 'case_opened')
      .map((e) => String((e.data as Record<string, unknown>).case_id))).size,
    [events],
  );

  /* Changing district changes which money is on screen, so it belongs in the same
     feed as every other event that changed it. No backend emits this one — the
     selection is a client-side fact — so the selector is its origin. */
  const onTenantSwitch = useCallback(
    (tenantId: string) => {
      push('tenant_switched', { tenant_id: tenantId });
      // The previous district's case is not in this one's docket.
      setSelectedCase(null);
    },
    [push],
  );

  return (
    <TenantProvider onSwitch={onTenantSwitch}>
      <AppShell
        surface={surface}
        onNavigate={setSurface}
        health={health ? { ...health, ok: health.ok && connected } : null}
        activeAgents={activeAgents}
        sessionCount={sessionCount}
        onCommand={() => setOpen(true)}
      >
        {surface === 'console' && (
          <Console events={events} selectedCase={selectedCase} onSelectCase={setSelectedCase} />
        )}
        {surface === 'docket' && (
          <Docket selectedCase={selectedCase} onSelectCase={setSelectedCase} />
        )}
        {surface === 'registry' && <Registry />}
        {surface === 'posture' && <Posture />}

        {open && (
          <CommandPalette
            onClose={() => setOpen(false)}
            onNavigate={(s) => { setSurface(s); setOpen(false); }}
          />
        )}
      </AppShell>
    </TenantProvider>
  );
}
