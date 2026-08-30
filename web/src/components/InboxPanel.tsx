import { useEffect, useMemo, useState } from 'react';
import { Paperclip } from 'lucide-react';
import { api } from '@/lib/api';
import type { InboxMessage, InboxRun } from '@/lib/types';
import { Button, Dot, NonIdealState, Pill } from './primitives';

/**
 * The morning's post.
 *
 * The operator does not read these. Sentry does, decides which ones are asking the district to
 * change where money is sent, and opens cases only for those. The header reports how that was
 * reached — how many were settled without a model call — because the affordability of the whole
 * fleet rests on it being pointed only where it is needed.
 */
export function InboxPanel({ onCaseOpened }: { onCaseOpened: () => void }) {
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [source, setSource] = useState<string | null>(null);
  // Starts true. A real mailbox takes seconds to fetch, and without this the pane
  // renders the words 'Inbox empty' for the whole of it — which is what the beat
  // opens on. An empty state is a claim that there is nothing there; while a fetch
  // is outstanding that claim is not yet true.
  const [loading, setLoading] = useState(true);
  const [run, setRun] = useState<InboxRun | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.inbox()
      .then((r) => { setMessages(r.messages); setSource(r.degraded ? 'seed' : (r.source ?? null)); })
      .catch(() => { setMessages([]); setSource(null); })
      .finally(() => setLoading(false));
  }, []);

  const verdictFor = useMemo(() => {
    const map = new Map<string, InboxRun['verdicts'][number]>();
    run?.verdicts.forEach((v) => map.set(v.message_id, v));
    return map;
  }, [run]);

  const caseFor = useMemo(() => {
    const map = new Map<string, string>();
    run?.cases_opened.forEach((c) => { if (c.case_id) map.set(c.message_id, c.case_id); });
    return map;
  }, [run]);

  const process = async (triageOnly = false) => {
    setBusy(true);
    try {
      setRun(await api.processInbox(triageOnly));
      if (!triageOnly) onCaseOpened();
    } finally {
      setBusy(false);
    }
  };

  return (
    /* min-h-0 on BOTH the column and the scroll child. Without it on the child, the list
       grows past the flex container and its rows render underneath the panel footer. */
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex h-[30px] shrink-0 items-center gap-2 rule-b px-3">
        {/* Where the post came from. Only shown when it is a real mailbox: labelling the default
            "seed" would be noise, but letting a recording imply a live inbox that was actually
            fixtures would be a claim the system had not earned. */}
        {source === 'gmail' && (
          <Pill tone="verdigris" minWidth={0}>live mailbox</Pill>
        )}
        {run ? (
          <span className="flex min-w-0 items-baseline gap-2 truncate">
            <span className="label-micro">Read</span>
            <span data-numeric="" className="font-mono text-mini text-[var(--color-ink)]">
              {run.messages_read}
            </span>
            <span className="label-micro">Flagged</span>
            <span data-numeric="" className="font-mono text-mini text-[var(--color-amber-text)]">
              {run.triage.investigate}
            </span>
            <span className="label-micro">Model calls</span>
            <span data-numeric="" className="font-mono text-mini text-[var(--color-ink)]">
              {run.triage.model_calls}
            </span>
          </span>
        ) : (
          <span className="label-micro">{messages.length} messages</span>
        )}
        {/* ONE control, two states, because the pane is 368px and after a run the header already
            carries a pill and three label/value pairs. Two buttons truncated the counts — which
            are the whole point of the beat — so the label describes what the next click does:

              nothing run yet        -> Triage        (read the morning, open nothing)
              a triage run flagged n -> Open n cases  (drive them through the fleet, minutes)
              a full run             -> Triage        (back to the top)

            Both actions stay reachable and the expensive one is never the default. */}
        <span className="ml-auto shrink-0">
          <Button
            tone="brass"
            disabled={busy}
            onClick={() => process(!(run && run.triage.investigate > 0 && run.triage_only))}
            title={run && run.triage_only && run.triage.investigate > 0
              ? 'Drive every flagged message through the fleet. Several minutes.'
              : "Read and triage the morning's post. No cases are opened."}
          >
            {busy
              ? 'Reading…'
              : run && run.triage_only && run.triage.investigate > 0
                ? `Open ${run.triage.investigate} cases`
                : 'Triage'}
          </Button>
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && messages.length === 0 ? (
          /* Reserved rows at the real row height, so the list does not jump when it arrives.
             The runbook forbids a layout shift at a beat's peak, and this beat's peak is the
             moment the morning's post appears. */
          <div aria-busy="true" aria-label="Reading the mailbox">
            {Array.from({ length: 10 }, (_, i) => (
              <div key={i} className="flex h-[51px] flex-col justify-center gap-1.5 rule-b-muted px-3">
                <div className="h-[10px] w-[38%] rounded-[2px] bg-[var(--color-fill-neutral)]" />
                <div className="h-[10px] w-[72%] rounded-[2px] bg-[var(--color-fill-neutral)]" />
              </div>
            ))}
          </div>
        ) : messages.length === 0 ? (
          <NonIdealState title="Inbox empty" />
        ) : (
          messages.map((m) => {
            const v = verdictFor.get(m.message_id);
            const caseId = caseFor.get(m.message_id);
            return (
              <article
                key={m.message_id}
                className={`flex flex-col gap-[2px] rule-b px-3 py-1.5
                  ${v?.action === 'investigate' ? 'bg-[var(--color-surface)]' : ''}
                  ${v?.action === 'ignore' ? 'opacity-55' : ''}`}
              >
                <div className="flex min-w-0 items-baseline gap-2">
                  {v && (
                    <Dot tone={v.action === 'investigate' ? 'amber' : 'neutral'} />
                  )}
                  <span className="min-w-0 truncate text-mini font-medium text-[var(--color-ink)]">
                    {m.sender_name}
                  </span>
                  {m.has_attachment && (
                    <Paperclip aria-hidden size={9} className="shrink-0 text-[var(--color-ink-faint)]" />
                  )}
                  {caseId && (
                    <span className="ml-auto shrink-0">
                      <Pill tone="amber" minWidth={0}>case opened</Pill>
                    </span>
                  )}
                </div>
                <span className="truncate text-mini text-[var(--color-ink-muted)]">
                  {m.subject}
                </span>
                {v && (
                  <span className="truncate text-micro text-[var(--color-ink-faint)]">
                    {v.used_model ? 'read by Sentry · ' : 'filtered · '}{v.reason}
                  </span>
                )}
              </article>
            );
          })
        )}
      </div>
    </div>
  );
}
