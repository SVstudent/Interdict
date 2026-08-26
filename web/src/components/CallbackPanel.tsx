import { useEffect, useState } from 'react';
import { Phone } from 'lucide-react';
import { api } from '@/lib/api';
import type { CallbackInstructions } from '@/lib/types';
import { Button, Callout } from './primitives';

/**
 * The out-of-band call.
 *
 * This is the control the entire product exists to enforce: before money moves, a human speaks to
 * the vendor on the number the SYSTEM holds — never the number the request supplied. So the panel
 * shows exactly two things large enough to act on: the number to dial, and, when the request tried
 * to supply its own, the number NOT to dial.
 *
 * The operator makes a real call and records what they heard. Nothing here is simulated.
 */
export function CallbackPanel({
  caseId, onResolved,
}: { caseId: string; onResolved: () => void }) {
  const [info, setInfo] = useState<CallbackInstructions | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void api.callbackInstructions(caseId).then(setInfo).catch(() => setInfo(null));
  }, [caseId]);

  if (!info?.awaiting || !info.dial) return null;

  const record = async (outcome: 'confirmed' | 'denied' | 'no_answer') => {
    setBusy(outcome);
    try {
      await api.recordCallback(caseId, outcome, 'Business Office');
      onResolved();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Callout tone="amber" className="mx-3 mt-2">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div>
          <span className="label-micro">Call this number</span>
          <div className="mt-[2px] flex items-center gap-2">
            <Phone aria-hidden size={14} className="text-[var(--color-amber-text)]" />
            <a
              href={`tel:${info.dial.replace(/[^+\d]/g, '')}`}
              className="font-mono text-xl leading-none text-[var(--color-ink)] underline
                decoration-[var(--color-amber-dim)] underline-offset-4"
            >
              {info.dial}
            </a>
          </div>
          <span className="mt-[2px] block text-mini text-[var(--color-ink-dim)]">
            {info.dial_source}
          </span>
        </div>

        {info.request_supplied_number && (
          <div>
            <span className="label-micro">Do not call</span>
            <div className="mt-[2px] font-mono text-base text-[var(--color-ink-faint)] line-through">
              {info.request_supplied_number}
            </div>
            <span className="mt-[2px] block max-w-[46ch] text-mini text-[var(--color-ink-dim)]">
              Supplied by the request itself.
            </span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          <Button tone="verdigris" disabled={busy !== null} onClick={() => record('confirmed')}>
            Vendor confirmed
          </Button>
          <Button disabled={busy !== null} onClick={() => record('denied')}>
            Vendor denied
          </Button>
          <Button disabled={busy !== null} onClick={() => record('no_answer')}>
            No answer
          </Button>
        </div>
      </div>

      {info.script && (
        <p className="mt-2 max-w-[100ch] text-xs leading-[1.5] text-[var(--color-ink-muted)]">
          {info.script}
        </p>
      )}
    </Callout>
  );
}
