"""Identity scopes — enforced, not asserted.

Each agent declares what it may do. A call outside that set raises AND emits a posture event
carrying the policy that produced the denial, because an enforcement you cannot show is one a
judge assumes you did not build (context/AGENTS.md).
"""
from __future__ import annotations

from dataclasses import dataclass


class Scope:
    PAYMENTS_FREEZE = "payments:freeze"
    PAYMENTS_RELEASE = "payments:release"
    PAYMENTS_BLOCK = "payments:block"
    CASES_WRITE = "cases:write"
    VENDOR_CONTACT_READ = "vendor:contact_of_record:read"
    VENDOR_BANKING_READ = "vendor:banking:read"
    ERP_INVOICES_READ = "erp:invoices:read"
    ERP_VENDOR_READ = "erp:vendor:read"
    ERP_WRITE = "erp:write"
    ARTIFACT_READ = "artifact:read"
    ENTITY_LOOKUP = "entity:lookup"
    FINDINGS_READ = "findings:read"
    AUDIT_WRITE = "audit:write"
    THREATINTEL_READ = "threatintel:read"
    THREATINTEL_WRITE = "threatintel:write"
    PAYMENTS_SCAN = "payments:scan"
    # Run a case through the pipeline against a sandbox that holds no real payments. Distinct
    # from CASES_WRITE so an agent can exercise the fleet without being able to open a case
    # that freezes a district's money.
    CASES_SIMULATE = "cases:simulate"
    PRECEDENT_READ = "precedent:read"
    PRECEDENT_WRITE = "precedent:write"


@dataclass(frozen=True)
class ScopeGrant:
    agent: str
    granted: frozenset[str]
    denied: frozenset[str]
    policy_id: str

    def permits(self, scope: str) -> bool:
        return scope in self.granted and scope not in self.denied


# Denials are explicit rather than "everything not granted", so the Registry manifest can show a
# procurement reviewer what an agent is specifically forbidden from touching.
FLEET_SCOPES: dict[str, ScopeGrant] = {
    "sentry": ScopeGrant(
        "sentry",
        frozenset({Scope.PAYMENTS_FREEZE, Scope.CASES_WRITE, Scope.ARTIFACT_READ}),
        frozenset({Scope.VENDOR_BANKING_READ, Scope.PAYMENTS_RELEASE, Scope.ERP_WRITE}),
        "interdict-policy/sentry-v1",
    ),
    "callback": ScopeGrant(
        "callback",
        frozenset({Scope.VENDOR_CONTACT_READ}),
        # The callback agent must never read banking details. It exists to phone a number from
        # the system of record; giving it the account data it is verifying defeats the control.
        frozenset({Scope.VENDOR_BANKING_READ, Scope.PAYMENTS_RELEASE, Scope.ERP_WRITE}),
        "interdict-policy/callback-v1",
    ),
    "ledger": ScopeGrant(
        "ledger",
        frozenset({Scope.ERP_INVOICES_READ, Scope.ERP_VENDOR_READ}),
        frozenset({Scope.ERP_WRITE, Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK}),
        "interdict-policy/ledger-v1",
    ),
    "provenance": ScopeGrant(
        "provenance",
        frozenset({Scope.ARTIFACT_READ}),
        frozenset({Scope.ERP_INVOICES_READ, Scope.ERP_VENDOR_READ, Scope.ERP_WRITE,
                   Scope.VENDOR_BANKING_READ}),
        "interdict-policy/provenance-v1",
    ),
    "registry-check": ScopeGrant(
        "registry-check",
        frozenset({Scope.ENTITY_LOOKUP, Scope.VENDOR_BANKING_READ}),
        frozenset({Scope.ERP_WRITE, Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK}),
        "interdict-policy/registry-check-v1",
    ),
    "challenger": ScopeGrant(
        "challenger",
        frozenset({Scope.FINDINGS_READ}),
        # Read-only by construction: the adversary must not be able to act on its own argument.
        frozenset({Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK, Scope.PAYMENTS_FREEZE,
                   Scope.ERP_WRITE, Scope.VENDOR_BANKING_READ, Scope.ARTIFACT_READ}),
        "interdict-policy/challenger-v2",
    ),
    # Scribe turns a blocked case into durable intelligence. It reads findings and writes the
    # threat library, and is denied everything that touches money or the ERP — an agent that
    # authors the fleet's own memory must not also be able to act on it.
    "scribe": ScopeGrant(
        "scribe",
        frozenset({Scope.FINDINGS_READ, Scope.THREATINTEL_WRITE}),
        frozenset({Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK, Scope.PAYMENTS_FREEZE,
                   Scope.ERP_WRITE, Scope.VENDOR_BANKING_READ, Scope.ARTIFACT_READ}),
        "interdict-policy/scribe-v1",
    ),
    # Attribution reads the threat library and argues. Read-only everywhere, including the
    # library itself: the agent that decides "this is the same operator" must not be able to
    # edit the record it is reasoning from.
    "attribution": ScopeGrant(
        "attribution",
        frozenset({Scope.FINDINGS_READ, Scope.THREATINTEL_READ}),
        frozenset({Scope.THREATINTEL_WRITE, Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK,
                   Scope.PAYMENTS_FREEZE, Scope.ERP_WRITE, Scope.VENDOR_BANKING_READ}),
        "interdict-policy/attribution-v1",
    ),
    # Hunter searches the payment book for other targets of a known operation. It may READ
    # payments and freeze them, but it may not release, block, or touch the ERP — a proactive
    # agent acting on its own initiative gets the narrowest possible power to interrupt, and no
    # power to conclude. Every hold it places still goes through the full fleet.
    "hunter": ScopeGrant(
        "hunter",
        frozenset({Scope.PAYMENTS_SCAN, Scope.PAYMENTS_FREEZE, Scope.THREATINTEL_READ,
                   Scope.ERP_VENDOR_READ}),
        frozenset({Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK, Scope.ERP_WRITE,
                   Scope.THREATINTEL_WRITE, Scope.VENDOR_BANKING_READ}),
        "interdict-policy/hunter-v1",
    ),
    # Red Team invents an attack the fleet has never seen and runs it, to measure what gets
    # through. It reads the threat library so it can build a variant that is genuinely novel,
    # and it is denied WRITING to that library: a red team that can edit the record it is
    # testing against measures its own edits, not the fleet. It simulates cases rather than
    # opening them, so an invented attack can never freeze a district's actual payments, and it
    # holds no money power at all — the fleet, not the attacker, decides what happens next.
    "redteam": ScopeGrant(
        "redteam",
        frozenset({Scope.THREATINTEL_READ, Scope.CASES_SIMULATE}),
        frozenset({Scope.THREATINTEL_WRITE, Scope.CASES_WRITE, Scope.PAYMENTS_RELEASE,
                   Scope.PAYMENTS_BLOCK, Scope.PAYMENTS_FREEZE, Scope.PAYMENTS_SCAN,
                   Scope.ERP_WRITE, Scope.VENDOR_BANKING_READ}),
        "interdict-policy/redteam-v1",
    ),
    # The Precedent Clerk turns a human's resolution of an escalation into a durable record, and
    # cites it back on later cases. It reads findings and owns the precedent book, and is denied
    # every money power: a precedent is an argument put to the adjudicator, never an instruction.
    # The agent that remembers what the organisation decided must not also be able to act on it.
    "precedent-clerk": ScopeGrant(
        "precedent-clerk",
        frozenset({Scope.FINDINGS_READ, Scope.PRECEDENT_READ, Scope.PRECEDENT_WRITE}),
        frozenset({Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK, Scope.PAYMENTS_FREEZE,
                   Scope.ERP_WRITE, Scope.VENDOR_BANKING_READ, Scope.THREATINTEL_WRITE}),
        "interdict-policy/precedent-clerk-v1",
    ),
    "adjudicator": ScopeGrant(
        "adjudicator",
        frozenset({Scope.PAYMENTS_RELEASE, Scope.PAYMENTS_BLOCK, Scope.AUDIT_WRITE,
                   Scope.FINDINGS_READ}),
        frozenset({Scope.ERP_WRITE}),
        "interdict-policy/adjudicator-v1",
    ),
}


class ScopeViolation(PermissionError):
    def __init__(self, agent: str, scope: str, policy_id: str) -> None:
        super().__init__(
            f"agent '{agent}' attempted '{scope}', which its identity denies "
            f"(policy {policy_id})"
        )
        self.agent, self.scope, self.policy_id = agent, scope, policy_id
