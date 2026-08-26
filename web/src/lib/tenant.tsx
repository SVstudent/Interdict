import {
  createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react';
import { api } from '@/lib/api';
import type { TenantSummary } from '@/lib/types';

/* ============================================================================
   WHICH DISTRICT THE OPERATOR IS IN.

   Always exactly one, never "all". A business office belongs to a district:
   its queue, its ledger, its supplier book and its precedent are that
   district's, and a merged view would let an operator act on money that is
   not theirs. The one surface that reads across the boundary is the threat
   exchange on Posture, and it reads tradecraft only.

   The selection is deliberately NOT persisted. On a fresh load the operator
   lands in the first district every time, which is the one thing a recording
   and a demo rehearsal both need to be reproducible.
   ============================================================================ */

interface TenantContextValue {
  tenants: TenantSummary[];
  /**
   * The district in force, or null when the roster could not be read. Null means
   * "unscoped", which is exactly the behaviour every surface had before tenancy
   * existed — so a failed roster fetch degrades to the old console rather than to
   * a blank one.
   */
  tenantId: string | null;
  active: TenantSummary | null;
  /** True once the roster has resolved OR failed. A view must not fetch before this. */
  ready: boolean;
  select: (id: string) => void;
  /** Bumped by `select`, so a view can refetch without watching the id itself. */
  epoch: number;
}

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({
  children, onSwitch,
}: {
  children: ReactNode;
  /** The `tenant_switched` event has no backend emitter; the selector is its origin. */
  onSwitch?: (tenantId: string) => void;
}) {
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    let live = true;
    void api.tenants()
      .then((r) => {
        if (!live) return;
        setTenants(r.tenants);
        setTenantId((current) => current ?? r.tenants[0]?.tenant_id ?? null);
      })
      .catch(() => { if (live) setTenants([]); })
      .finally(() => { if (live) setReady(true); });
    return () => { live = false; };
  }, []);

  // Side effects live here, not inside the state updater: React may invoke an updater
  // twice, and a switch that emitted two events would double-count in the feed.
  const select = useCallback((id: string) => {
    if (id === tenantId) return;
    setTenantId(id);
    setEpoch((n) => n + 1);
    onSwitch?.(id);
  }, [onSwitch, tenantId]);

  const value = useMemo<TenantContextValue>(() => ({
    tenants,
    tenantId,
    active: tenants.find((t) => t.tenant_id === tenantId) ?? null,
    ready,
    select,
    epoch,
  }), [tenants, tenantId, ready, select, epoch]);

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const value = useContext(TenantContext);
  if (!value) throw new Error('useTenant must be used inside a TenantProvider');
  return value;
}
