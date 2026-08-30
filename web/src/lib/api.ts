import type {
  AuditRecord, CaseDetail, CaseSummary, Checkpoint, Effect, ExchangeFeed, GatewayDecision,
  CallbackInstructions, Health, HumanOutcome, ImpactSummary, InboxMessage, InboxRun, LedgerTotals,
  PostureEvent, Precedent, PrecedentMatchResult, PrecedentResolution, RedTeamRun,
  RedTeamScoreboard, RegistryEntry,
  Scenario, ScopeManifestRow, Span, TenantDetail, TenantSummary, ThreatLibrary, Vendor,
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '';

class ApiError extends Error {
  constructor(readonly status: number, readonly path: string, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new ApiError(res.status, path, body || res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const post = <T>(path: string, body?: unknown): Promise<T> =>
  req<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });

export const api = {
  health: () => req<Health>('/healthz'),

  /** Omit tenantId for every district — the single-district surfaces have always done that. */
  cases: (tenantId?: string) =>
    req<CaseSummary[]>(`/api/cases${tenantId ? `?tenant_id=${tenantId}` : ''}`),
  case: (id: string) => req<CaseDetail>(`/api/cases/${id}`),
  trace: (id: string) => req<{ case_id: string; spans: Span[] }>(`/api/cases/${id}/trace`),
  checkpoints: (id: string) =>
    req<{ case_id: string; checkpoints: Checkpoint[]; effects: Effect[] }>(
      `/api/cases/${id}/checkpoints`,
    ),
  memory: (id: string) =>
    req<{
      case_id: string; session_id: string | null; age_days: number | null;
      events: { event_id: string; kind: string; occurred_at: string; payload: unknown }[];
    }>(`/api/cases/${id}/memory`),

  vendors: (tenantId?: string) =>
    req<Vendor[]>(`/api/vendors${tenantId ? `?tenant_id=${tenantId}` : ''}`),
  threatLibrary: (tenantId?: string) =>
    req<ThreatLibrary>(`/api/threat-library${tenantId ? `?tenant_id=${tenantId}` : ''}`),
  inbox: () => req<{
    messages: InboxMessage[]; count: number;
    // Where the post came from. `seed` is the fixture inbox, `gmail` a real mailbox read over
    // IMAP. Rendered in the panel header: a console that showed fixtures while the recording
    // implied a live mailbox would be claiming something it had not done.
    source?: 'seed' | 'gmail'; correlation?: 'fixture' | 'header'; degraded?: string | null;
  }>('/api/inbox'),
  // `triageOnly` reads and sorts the morning's post without driving the flagged cases
  // through the fleet. Seconds rather than minutes — see the endpoint's docstring.
  processInbox: (triageOnly = false) =>
    post<InboxRun>(`/api/inbox/process${triageOnly ? '?triage_only=true' : ''}`),
  callbackInstructions: (caseId: string) =>
    req<CallbackInstructions>(`/api/cases/${caseId}/callback`),
  recordCallback: (caseId: string, outcome: 'confirmed' | 'denied' | 'no_answer',
                   verifiedBy: string, notes = '') =>
    post<{ ok: boolean; state: string; outcome: string | null }>(
      `/api/cases/${caseId}/callback`,
      { outcome, verified_by: verifiedBy, notes },
    ),
  impact: (tenantId?: string) =>
    req<ImpactSummary>(`/api/impact${tenantId ? `?tenant_id=${tenantId}` : ''}`),
  ledger: (tenantId?: string) =>
    req<LedgerTotals>(`/api/ledger${tenantId ? `?tenant_id=${tenantId}` : ''}`),

  /** F1 — Red Team. `run` COSTS MODEL CALLS: a generation call plus a pipeline run per variant. */
  redteam: {
    runs: () => req<{ runs: RedTeamRun[]; scoreboard: RedTeamScoreboard }>('/api/redteam/runs'),
    run: (runId: string) => req<RedTeamRun>(`/api/redteam/runs/${runId}`),
    /** `dryRun` generates the variants and executes none of them — one model call, no pipeline. */
    start: (variants = 3, dryRun = true) =>
      post<RedTeamRun>('/api/redteam/run', { variants, dry_run: dryRun }),
  },

  /** F2 — Precedent. */
  precedent: {
    all: (tenantId?: string) =>
      req<{ precedents: Precedent[]; count: number }>(
        `/api/precedent${tenantId ? `?tenant_id=${tenantId}` : ''}`,
      ),
    one: (precedentId: string) => req<Precedent>(`/api/precedent/${precedentId}`),
    forCase: (caseId: string) =>
      req<PrecedentMatchResult>(`/api/cases/${caseId}/precedent`),
    resolve: (caseId: string, outcome: HumanOutcome, rationale: string, decidedBy: string) =>
      post<PrecedentResolution>(`/api/cases/${caseId}/resolve`, {
        outcome, rationale, decided_by: decidedBy,
      }),
  },

  /** F3 — tenants and the one exchange they share. */
  tenants: () => req<{ tenants: TenantSummary[]; exchange_id: string }>('/api/tenants'),
  tenant: (tenantId: string) => req<TenantDetail>(`/api/tenants/${tenantId}`),
  exchange: () => req<ExchangeFeed>('/api/exchange'),

  registry: () => req<{ entries: RegistryEntry[]; backend: string }>('/api/registry'),
  agent: (id: string) => req<RegistryEntry>(`/api/registry/${id}`),

  posture: () =>
    req<{
      events: PostureEvent[];
      gateway_decisions: GatewayDecision[];
      scope_manifest: ScopeManifestRow[];
    }>('/api/posture'),

  auditChain: () =>
    req<{ records: AuditRecord[]; verification: { intact: boolean; length?: number; reason?: string } }>(
      '/api/audit',
    ),
  auditRecord: (caseId: string) => req<AuditRecord>(`/api/audit/${caseId}`),
  auditDownloadUrl: (caseId: string) => `${BASE}/api/audit/${caseId}/download`,

  demo: {
    scenarios: () => req<Scenario[]>('/api/demo/scenarios'),
    reset: () => post<{ ok: boolean; seeded: Record<string, number>; elapsed_ms: number }>(
      '/api/demo/reset',
    ),
    inject: (id: string) =>
      post<{
        ok: boolean; case_id: string; state: string; outcome: string | null;
        elapsed_ms: number; screening: Record<string, unknown>;
      }>(`/api/demo/inject_scenario/${id}`),
    advanceClock: (days: number) => post<{ ok: boolean; now: string }>('/api/demo/advance_clock', { days }),
    kill: (caseId?: string) =>
      post<{ ok: boolean; killed: string[] }>(
        `/api/demo/kill_runner${caseId ? `?case_id=${caseId}` : ''}`,
      ),
    resume: (caseId?: string) =>
      post<{ ok: boolean; reports: unknown[] }>(
        `/api/demo/resume_runner${caseId ? `?case_id=${caseId}` : ''}`,
      ),
    forceScopeViolation: () =>
      post<{ denied: boolean; agent: string; scope: string; policy_id: string; message: string }>(
        '/api/demo/force_scope_violation',
      ),
    timings: () => req<{ beats: Record<string, number>; mode: string; platform: string }>(
      '/api/demo/timings',
    ),
  },
};

export { ApiError };
