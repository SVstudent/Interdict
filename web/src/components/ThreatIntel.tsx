import type { Finding, ThreatDossier } from '@/lib/types';
import { Callout, Card, MonoId, Pill, SectionHeader } from './primitives';

/* ============================================================================
   Threat intelligence.

   Two presentations of one idea, deliberately no new surface:

     RecognitionStrip  Console — a single line above the balance the moment an incoming
                       request is attributed to a known operation. This is the visible product
                       feature: the fleet says "I have seen these people before" before any
                       verification lane has finished.

     DossierPanel      Docket — the full intelligence product, inside the existing session-memory
                       tab because that is what it is: memory.
   ============================================================================ */

export function RecognitionStrip({
  finding, designation, priorCaseId,
}: { finding: Finding; designation: string; priorCaseId: string }) {
  const attributed = finding.signal === 'known_operation_recognised';

  // Not attributed = the matcher saw a resemblance and the analyst declined to call it. That is a
  // quieter state and must not borrow the alarm colour.
  return (
    <Callout tone="amber" className="mx-3 mt-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="label-micro">
          {attributed ? 'Known operation' : 'Resemblance, not attributed'}
        </span>
        <span className="font-display text-lg leading-none text-[var(--color-ink)]">
          {designation}
        </span>
        <Pill tone="amber">
          {Math.round(finding.confidence * 100)}% confidence
        </Pill>
        <span className="label-micro">first seen</span>
        <MonoId>{priorCaseId}</MonoId>
      </div>
      <p className="mt-1 max-w-[104ch] text-mini leading-[1.5] text-[var(--color-ink-dim)]">
        {finding.reasoning}
      </p>
    </Callout>
  );
}

export function DossierPanel({ dossier }: { dossier: ThreatDossier }) {
  return (
    <Card elevation={1} className="p-0">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rule-b px-3 py-2">
        <span className="label-brass">Operation</span>
        <h3 className="font-display text-xl leading-none text-[var(--color-ink)]">
          {dossier.designation}
        </h3>
        <Pill tone="neutral">{Math.round(dossier.confidence * 100)}% confidence</Pill>
        <span className="ml-auto flex items-baseline gap-2">
          <span className="label-micro">first seen</span>
          <MonoId>{dossier.first_seen_case_id}</MonoId>
        </span>
      </header>

      <div className="px-3 py-2.5">
        <p className="max-w-[100ch] text-xs leading-[1.55] text-[var(--color-ink)]">
          {dossier.assessment}
        </p>

        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <ListBlock title="Tradecraft" items={dossier.tradecraft} />
          <ListBlock title="Indicators" items={dossier.indicators} />
        </div>

        {dossier.likely_next_target && (
          <div className="mt-3 rule-t pt-2.5">
            <SectionHeader title="Predicted next target" />
            <p className="mt-1 max-w-[100ch] text-xs leading-[1.55] text-[var(--color-brass)]">
              {dossier.likely_next_target}
            </p>
          </div>
        )}

        {dossier.authored_by && (
          <p className="mt-3 text-micro text-[var(--color-ink-faint)]">
            Written by {dossier.authored_by}
            {dossier.model ? ` on ${dossier.model}` : ''} after the interdiction. The fleet
            attributes later requests against this record.
          </p>
        )}
      </div>
    </Card>
  );
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <SectionHeader title={title} />
      <ul className="mt-1 flex flex-col gap-1">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-mini leading-[1.5] text-[var(--color-ink-dim)]">
            <span aria-hidden className="mt-[6px] h-[3px] w-[3px] shrink-0 bg-[var(--color-brass)]" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
