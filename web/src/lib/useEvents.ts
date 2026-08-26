import { useCallback, useEffect, useRef, useState } from 'react';

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
  at: string;
}

/**
 * Subscribes to the backend SSE stream.
 *
 * Events are appended as they arrive — never polled — because a spinner followed by a result
 * is a failed demo beat. The buffer is capped so a long rehearsal cannot grow without bound.
 */
export function useEvents(limit = 400) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const source = new EventSource(`${import.meta.env.VITE_API_URL ?? ''}/api/events`);

    const handle = (raw: MessageEvent) => {
      try {
        const payload = JSON.parse(raw.data) as StreamEvent;
        seq.current += 1;
        setEvents((prev) => {
          const next = [...prev, payload];
          return next.length > limit ? next.slice(next.length - limit) : next;
        });
      } catch {
        /* a malformed frame must not tear down the stream mid-demo */
      }
    };

    const NAMES = [
      'demo_reset', 'case_opened', 'state_changed', 'step_started', 'step_completed',
      'step_failed', 'lane_started', 'lane_failed', 'finding_added', 'challenge_completed',
      'decision_rendered', 'payments_held', 'payments_finalized', 'clock_advanced',
      'runner_killed', 'runner_resumed', 'scope_denied',
      'recall_hit', 'dossier_written', 'fingerprint_recorded', 'inbox_triaged',
      'sweep_completed', 'callback_recorded', 'callback_window_expired',
      'attribution_unavailable', 'scribe_unavailable',
      'redteam_run_started', 'redteam_variant_generated', 'redteam_trial_completed',
      'redteam_run_completed',
      'precedent_recorded', 'precedent_cited', 'precedent_unavailable',
      'tenant_switched', 'exchange_published', 'exchange_recognised',
    ];
    NAMES.forEach((n) => source.addEventListener(n, handle as EventListener));
    source.addEventListener('open', () => setConnected(true));
    source.addEventListener('error', () => setConnected(false));

    return () => source.close();
  }, [limit]);

  /**
   * Append an event the client itself originated. `tenant_switched` has no backend
   * emitter — the district an operator is looking at is a client-side fact — and the
   * feed would otherwise be missing the one action that reframes every other event
   * in it.
   */
  const push = useCallback((event: string, data: Record<string, unknown>) => {
    setEvents((prev) => {
      const next = [...prev, { event, data, at: new Date().toISOString() }];
      return next.length > limit ? next.slice(next.length - limit) : next;
    });
  }, [limit]);

  return { events, connected, push, clear: () => setEvents([]) };
}

/** The most recent event of a given type, or undefined. */
export function latest(events: StreamEvent[], name: string): StreamEvent | undefined {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i]?.event === name) return events[i];
  }
  return undefined;
}
