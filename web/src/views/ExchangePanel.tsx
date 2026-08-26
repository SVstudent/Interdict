import { useCallback, useEffect, useState } from 'react';
import { Share2 } from 'lucide-react';
import { api } from '@/lib/api';
import type { ExchangeEntry, ExchangeFeed, ExchangeRecognition } from '@/lib/types';
import { clock, LOCAL_ZONE, LOCAL_ZONE_LONG, plural } from '@/lib/format';
import { useTenant } from '@/lib/tenant';
import { DataGrid, type Column } from '@/components/DataGrid';
import {
  MonoId, NonIdealState, Panel, Pill, ScopeChip, Timestamp,
} from '@/components/primitives';

/* ============================================================================
   THREAT EXCHANGE — the one thing in this system that crosses a tenant.

   It belongs on Posture because Posture is the data-handling surface, and the
   exchange is the only place data leaves a district at all. Every other pane
   here answers "what may this AGENT touch"; this one answers "what may another
   DISTRICT see", which is the same question one level up.

   THE ASYMMETRY IS THE FEATURE, so the pane states both halves:

     what crosses    the tradecraft — a beneficiary name, a domain technique,
                     a receiving bank, a designation
     what does not   the victim, the amount, the invoice, the supplier's name
                     and phone number

   The second half is COMPUTED by the backend, not asserted: it walks every
   published entry and reports which fields are genuinely absent. If `publish()`
   ever started carrying one, it would drop out of the list rather than the UI
   going on claiming it was withheld. That is why the withheld chips are real
   evidence and not a marketing line.

   NO OXBLOOD. A recognition is intelligence arriving, not money being stopped;
   the money stops on the case it opens, on the Console, where the hue means it.
   ============================================================================ */

export function ExchangePanel() {
  const { tenantId } = useTenant();
  const [feed, setFeed] = useState<ExchangeFeed | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    let live = true;
    void api.exchange()
      .then((f) => { if (live) setFeed(f); })
      .catch(() => { if (live) setFeed(null); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  useEffect(() => load(), [load]);

  const members = feed?.members ?? [];
  const entries = feed?.entries ?? [];
  const recognitions = feed?.recognitions ?? [];
  const withheld = feed?.withheld ?? [];

  const shortName = (id: string) =>
    members.find((m) => m.tenant_id === id)?.short_name ?? id;

  const entryColumns: Column<ExchangeEntry>[] = [
    {
      key: 'designation',
      header: 'Operation',
      width: '168px',
      sortable: true,
      value: (r) => r.designation,
      title: (r) => r.designation,
      render: (r) => (
        <span className="truncate font-medium text-[var(--color-ink)]">{r.designation}</span>
      ),
    },
    {
      key: 'from',
      header: 'Contributed by',
      width: '132px',
      sortable: true,
      value: (r) => r.contributed_by_tenant_id,
      render: (r) => (
        <Pill tone={r.contributed_by_tenant_id === tenantId ? 'brass' : 'neutral'} minWidth={68}>
          {shortName(r.contributed_by_tenant_id)}
        </Pill>
      ),
    },
    {
      key: 'recognised',
      header: 'Recognised by',
      width: '128px',
      numeric: true,
      sortable: true,
      value: (r) => r.recognised_by_tenant_ids.length,
      title: (r) => (r.recognised_by_tenant_ids.map(shortName).join(', ') || 'Nobody yet'),
      render: (r) => r.recognised_by_tenant_ids.length,
    },
    {
      key: 'at',
      header: `Published (${LOCAL_ZONE})`,
      width: '132px',
      headerTitle: `Local time — ${LOCAL_ZONE_LONG}`,
      sortable: true,
      value: (r) => r.published_at,
      render: (r) => <Timestamp>{clock(r.published_at)}</Timestamp>,
    },
    {
      key: 'assessment',
      header: 'Assessment',
      title: (r) => r.dossier?.assessment ?? '',
      render: (r) => (
        <span className="truncate text-[var(--color-ink-muted)]">
          {r.dossier?.assessment ?? '—'}
        </span>
      ),
    },
  ];

  const recognitionColumns: Column<ExchangeRecognition>[] = [
    {
      key: 'designation',
      header: 'Operation',
      width: '168px',
      sortable: true,
      value: (r) => r.designation,
      render: (r) => <span className="truncate">{r.designation}</span>,
    },
    {
      key: 'who',
      header: 'Recognised by',
      width: '132px',
      sortable: true,
      value: (r) => r.tenant_id,
      render: (r) => (
        <Pill tone={r.tenant_id === tenantId ? 'brass' : 'neutral'} minWidth={68}>
          {shortName(r.tenant_id)}
        </Pill>
      ),
    },
    {
      key: 'case',
      header: 'On case',
      width: '132px',
      sortable: true,
      value: (r) => r.case_id,
      render: (r) => <MonoId>{r.case_id}</MonoId>,
    },
    {
      key: 'score',
      header: 'Score',
      width: '72px',
      numeric: true,
      sortable: true,
      value: (r) => r.score,
      headerTitle: 'A cross-district match must clear the same threshold as a local one',
      render: (r) => (
        <span data-numeric="" className="font-mono tabular">{r.score.toFixed(2)}</span>
      ),
    },
    {
      key: 'why',
      header: 'Matched on',
      title: (r) => r.matched_on.join('; '),
      render: (r) => (
        <span className="truncate text-[var(--color-ink-muted)]">{r.matched_on.join('; ')}</span>
      ),
    },
  ];

  return (
    <Panel
      title="Threat exchange"
      label="Shared threat exchange"
      className="min-h-0"
      actions={
        <span className="text-mini text-[var(--color-ink-dim)]">
          {plural(members.length, 'district')} · {plural(entries.length, 'operation')}
        </span>
      }
      footer={
        <>
          <span className="label-micro shrink-0">Exchange</span>
          <MonoId truncate>{feed?.exchange_id ?? '—'}</MonoId>
        </>
      }
    >
      <div className="flex flex-col">
        <div className="flex flex-col gap-3 rule-b px-3 py-3">
          <p className="max-w-[92ch] text-xs leading-5 text-[var(--color-ink-dim)]">
            Tradecraft crosses districts. Money does not.
          </p>

          {/* The claim that matters, and the reason it is trustworthy: these field
              names were checked against the published entries, not asserted. */}
          <div className="flex flex-col gap-2">
            <span className="label-micro">Never leaves the district</span>
            <div className="flex flex-wrap gap-1">
              {withheld.length
                ? withheld.map((field) => <ScopeChip key={field} scope={field} denied />)
                : (
                  <span className="text-mini text-[var(--color-ink-faint)]">
                    Nothing published yet, so nothing has been withheld.
                  </span>
                )}
            </div>
          </div>

          {members.length > 0 && (
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {members.map((m) => (
                <span key={m.tenant_id} className="flex items-baseline gap-2">
                  <Pill tone={m.tenant_id === tenantId ? 'brass' : 'neutral'} minWidth={68}>
                    {m.short_name}
                  </Pill>
                  <span data-numeric="" className="font-mono tabular text-mini text-[var(--color-ink-dim)]">
                    {m.contributed} contributed · {m.recognised_from_exchange} recognised
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>

        <DataGrid
          label="Published operations"
          density="dense"
          columns={entryColumns}
          rows={entries}
          rowKey={(r) => r.entry_id}
          loading={loading}
          skeletonRows={3}
          empty={
            <NonIdealState
              visual={<Share2 aria-hidden size={22} strokeWidth={1.75} />}
              title="Nothing published yet"
              description="A district publishes to the exchange the moment it blocks an operation. What it publishes is the method, never the target."
            />
          }
        />

        {recognitions.length > 0 && (
          <>
            <div className="flex h-[30px] shrink-0 items-center rule-b rule-t px-3">
              <h3 className="label-micro truncate">Recognised on first contact</h3>
            </div>
            <DataGrid
              label="Cross-district recognitions"
              density="dense"
              columns={recognitionColumns}
              rows={recognitions}
              rowKey={(r) => `${r.case_id}:${r.entry_id}`}
            />
          </>
        )}

        {entries.length > 0 && recognitions.length === 0 && (
          <div className="px-3 py-3">
            <p className="text-mini text-[var(--color-ink-dim)]">
              Published; no cross-district match yet.
            </p>
          </div>
        )}
      </div>
    </Panel>
  );
}
