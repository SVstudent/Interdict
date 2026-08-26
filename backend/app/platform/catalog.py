"""The published agent catalog — what beat 1 shows.

Metadata is written as a procurement reviewer would read it. Two unrelated fleets are included
alongside `interdict.*`: a registry with one entry is a demo, three is a platform.
"""
from __future__ import annotations

from .registry import RegistryEntry
from ..agents.scopes import FLEET_SCOPES

FINDING_SCHEMA = {
    "type": "object",
    "required": ["verdict", "confidence", "evidence", "reasoning"],
    "properties": {
        "verdict": {"enum": ["supports", "contradicts", "inconclusive"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {
            "type": "object",
            "required": ["source", "locator", "excerpt"],
            "properties": {"source": {"type": "string"}, "locator": {"type": "string"},
                           "excerpt": {"type": "string"}}}},
        "reasoning": {"type": "string"},
    },
}

CASE_INPUT_SCHEMA = {
    "type": "object",
    "required": ["case_id", "request_id"],
    "properties": {"case_id": {"type": "string"}, "request_id": {"type": "string"}},
}


def _scopes(agent: str) -> tuple[list[str], list[str]]:
    grant = FLEET_SCOPES[agent]
    return sorted(grant.granted), sorted(grant.denied)


def _entry(
    agent: str, version: str, description: str, department: str, classification: str,
    used_by: list[str], changelog: list[dict[str, str]],
) -> RegistryEntry:
    granted, denied = _scopes(agent)
    return RegistryEntry(
        agent_id=f"interdict.{agent}",
        display_name=agent.replace("-", " ").title(),
        version=version,
        description=description,
        owner="treasury-controls@example-corp.test",
        department=department,
        data_classification=classification,
        granted_scopes=granted,
        denied_scopes=denied,
        input_schema=CASE_INPUT_SCHEMA,
        output_schema=FINDING_SCHEMA,
        changelog=changelog,
        used_by=used_by,
    )


AP = "Accounts Payable"
TR = "Treasury"
IA = "Internal Audit"

INTERDICT_FLEET: list[RegistryEntry] = [
    _entry("sentry", "1.4.0",
           "Detects payee-detail changes on inbound artifacts, resolves the vendor of record, "
           "freezes affected scheduled payments and opens a case. Makes no legitimacy judgment.",
           "Treasury Controls", "restricted", [AP, TR],
           [{"version": "1.4.0", "note": "Exposure now sums real held payments instead of an estimate."},
            {"version": "1.3.0", "note": "Vendor resolution falls back to domain matching."}]),
    _entry("callback", "1.2.1",
           "Out-of-band vendor confirmation. Dials only the contact number held in the system of "
           "record; records a request-supplied number as a signal and never dials it.",
           "Treasury Controls", "confidential", [AP],
           [{"version": "1.2.1", "note": "Request-supplied numbers logged as a signal before being discarded."},
            {"version": "1.2.0", "note": "Dormant callbacks now suspend the case rather than blocking the fan-out."}]),
    _entry("ledger", "1.3.0",
           "Relationship baseline from the ERP: tenure, invoice history, prior banking-change "
           "frequency, and whether a referenced open invoice actually correlates. Read-only.",
           "Financial Systems", "restricted", [AP, TR, IA],
           [{"version": "1.3.0", "note": "Adds open-invoice correlation against the cited invoice number."}]),
    _entry("provenance", "1.1.0",
           "Inbound artifact forensics: reply-to divergence, domain registration age, homoglyph "
           "detection, document producer metadata against historical invoices, thread-hijack markers.",
           "Security Engineering", "internal", [AP, IA],
           [{"version": "1.1.0", "note": "Homoglyph comparison folds confusables before scoring similarity."}]),
    _entry("registry-check", "1.0.2",
           "Entity attestation: proposed account holder name against the registered legal entity, "
           "and bank jurisdiction against the vendor operating country.",
           "Security Engineering", "confidential", [AP],
           [{"version": "1.0.2", "note": "Corporate suffixes normalised before name comparison."}]),
    _entry("challenger", "2.0.0",
           "Adversarial review. Constructs the strongest legitimate explanation for the change — "
           "acquisitions, bank mergers, factoring, treasury consolidation — then rebuts each "
           "supporting finding individually. Read-only by construction; holds no tools.",
           "Treasury Controls", "restricted", [TR, IA],
           [{"version": "2.0.0", "note": "Steelman is now constructed before rebuttal; reduces false-positive blocks."},
            {"version": "1.4.2", "note": "Rebuttals bound to finding IDs rather than a single survived flag."},
            {"version": "1.2.0", "note": "Initial adversarial pass over aggregated findings."}]),
    _entry("scribe", "1.0.0",
           "Threat intelligence. After an interdiction, reads the whole case and writes a dossier "
           "on the operation behind it: a designation, an assessment, the reusable tradecraft, "
           "indicators to watch for, and the vendor type it expects to be targeted next.",
           "Treasury Controls", "restricted", [IA, TR],
           [{"version": "1.0.0", "note": "Initial release. Turns a blocked case into durable intelligence."}]),
    _entry("attribution", "1.0.0",
           "Reads a known operation's dossier and argues whether an incoming request belongs to "
           "it. Deliberately sceptical: shared banks and new domains recur for innocent reasons, "
           "and a wrong attribution misleads the operator about who is attacking them.",
           "Security Engineering", "restricted", [AP, IA],
           [{"version": "1.0.0", "note": "Initial release. Agentic attribution over deterministic retrieval."}]),
    _entry("redteam", "1.0.0",
           "Adversarial assurance. Reads the threat library, invents attack variants the fleet "
           "has never been shown, runs them through the real pipeline against a simulation "
           "tenant and reports the hit rate plus a reason for every variant that got through. "
           "Denied write access to the library it tests against.",
           "Security Engineering", "restricted", [IA],
           [{"version": "1.0.0", "note": "Initial release. Detection claims become a measured number."}]),
    _entry("precedent-clerk", "1.0.0",
           "Institutional memory for human decisions. Records how a named reviewer resolved an "
           "escalation and why, then argues whether that ruling governs a later case with the "
           "same exposure band, verdict pattern, callback state and vendor tenure.",
           "Treasury Controls", "confidential", [AP, TR, IA],
           [{"version": "1.0.0", "note": "Initial release. An escalation stops dead-ending at a human."}]),
    _entry("adjudicator", "1.5.0",
           "Weighs findings against the adversarial review, applies the deterministic release "
           "rails, and emits the decision plus the Nacha 2026 audit record.",
           "Treasury Controls", "restricted", [AP, TR, IA],
           [{"version": "1.5.0", "note": "Auto-release ceiling enforced in code, ahead of model judgment."},
            {"version": "1.4.0", "note": "Audit records hash-chained to the preceding record."}]),
]

# Unrelated fleets. They make the Registry read as an organisation's catalog rather than a
# single project's self-listing.
NEIGHBOURING_FLEETS: list[RegistryEntry] = [
    RegistryEntry(
        agent_id="procurement.onboarding", display_name="Vendor Onboarding",
        version="3.2.1",
        description="Runs new-supplier intake: document collection, sanctions screening, "
                    "tax-form validation and ERP record creation.",
        owner="procurement-platform@example-corp.test", department="Procurement",
        data_classification="restricted", granted_scopes=["erp:vendor:write", "entity:lookup"],
        denied_scopes=["payments:release"], used_by=["Procurement", "Legal"],
        changelog=[{"version": "3.2.1", "note": "Sanctions screening moved to the async runtime."}],
    ),
    RegistryEntry(
        agent_id="finance.close", display_name="Period Close Assistant",
        version="2.8.0",
        description="Coordinates month-end close: accrual proposals, intercompany reconciliation "
                    "and variance narratives for the controller's review.",
        owner="fin-ops@example-corp.test", department="Controllership",
        data_classification="confidential", granted_scopes=["erp:gl:read", "erp:journal:propose"],
        denied_scopes=["erp:journal:post"], used_by=["Controllership", "FP&A"],
        changelog=[{"version": "2.8.0", "note": "Variance narratives cite source journals."}],
    ),
]


def full_catalog() -> list[RegistryEntry]:
    return [*INTERDICT_FLEET, *NEIGHBOURING_FLEETS]
