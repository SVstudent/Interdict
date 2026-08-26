"""Agent tools.

These are real computations over the case corpus, not fixtures: domain-age arithmetic, homoglyph
comparison, invoice correlation, entity-name matching. They run with no API key, which is what
lets the evidence in a Finding be a literal observed value rather than a model's recollection.

Each tool declares the scope it consumes. The registry enforces it before the body runs.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

from ..guardrails.injection import HOMOGLYPHS
from ..models.domain import Invoice, Payment, Vendor
from .scopes import Scope


@dataclass(frozen=True)
class ToolSpec:
    name: str
    scope: str
    description: str
    fn: Callable[..., Any]


# --- provenance ---------------------------------------------------------------------

def analyze_sender_domain(
    *, from_address: str, reply_to: str, vendor_domain: str, domain_registered_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    """Compare the addresses on an artifact against the vendor's domain of record."""
    def domain_of(addr: str) -> str:
        return addr.rsplit("@", 1)[-1].lower().strip()

    from_domain, reply_domain = domain_of(from_address), domain_of(reply_to or from_address)
    divergent = reply_domain != from_domain

    # Confusable comparison: normalise homoglyphs, then measure edit similarity.
    def fold(d: str) -> str:
        return "".join(HOMOGLYPHS.get(c, c) for c in unicodedata.normalize("NFKC", d))

    folded_reply, folded_vendor = fold(reply_domain), fold(vendor_domain.lower())
    similarity = difflib.SequenceMatcher(None, folded_reply, folded_vendor).ratio()
    lookalike = folded_reply != folded_vendor and similarity >= 0.80

    age_days = (now - domain_registered_at).days if domain_registered_at else None

    return {
        "from_domain": from_domain,
        "reply_to_domain": reply_domain,
        "vendor_domain_of_record": vendor_domain,
        "reply_to_diverges": divergent,
        "lookalike_domain": lookalike,
        "similarity_to_vendor_domain": round(similarity, 4),
        "domain_age_days": age_days,
        "newly_registered": age_days is not None and age_days < 30,
    }


def inspect_document_metadata(*, metadata: dict[str, Any], baseline_producer: str | None) -> dict[str, Any]:
    producer = metadata.get("producer")
    return {
        "producer": producer,
        "baseline_producer": baseline_producer,
        "producer_changed": bool(producer and baseline_producer and producer != baseline_producer),
        "supplied_phone": metadata.get("supplied_phone"),
        "thread_hijack_markers": [
            k for k in ("in_reply_to", "references") if k in metadata
        ],
    }


# --- ledger -------------------------------------------------------------------------

def relationship_baseline(*, vendor: Vendor, now: datetime) -> dict[str, Any]:
    return {
        "vendor_id": vendor.vendor_id,
        "tenure_days": vendor.tenure_days(now),
        "tenure_years": round(vendor.tenure_days(now) / 365.25, 1),
        "invoice_count": vendor.invoice_count,
        "total_paid_lifetime": str(vendor.total_paid_lifetime),
        "prior_banking_changes": len(vendor.banking_change_history),
        "last_banking_change": (
            vendor.banking_change_history[-1].changed_at.isoformat()
            if vendor.banking_change_history else None
        ),
    }


def correlate_open_invoice(
    *, invoices: list[Invoice], referenced_invoice_id: str | None, now: datetime
) -> dict[str, Any]:
    """Does the invoice the request cites actually exist and is it actually open?"""
    match = next((i for i in invoices if i.invoice_id == referenced_invoice_id), None)
    return {
        "referenced_invoice_id": referenced_invoice_id,
        "exists": match is not None,
        "status": match.status if match else None,
        "amount": str(match.amount) if match else None,
        "days_to_due": (match.due_at - now).days if match else None,
        "open_invoice_count": sum(1 for i in invoices if i.status == "open"),
    }


# --- registry-check -----------------------------------------------------------------

def match_account_holder(*, account_name: str, legal_name: str, dba_name: str | None) -> dict[str, Any]:
    def norm(s: str) -> str:
        drop = {"llc", "inc", "ltd", "corp", "co", "gmbh", "plc", "group", "holdings"}
        parts = [p for p in "".join(
            c.lower() if c.isalnum() or c.isspace() else " " for c in s
        ).split() if p not in drop]
        return " ".join(parts)

    candidates = [n for n in (legal_name, dba_name) if n]
    best = max(
        (difflib.SequenceMatcher(None, norm(account_name), norm(c)).ratio() for c in candidates),
        default=0.0,
    )
    return {
        "account_name": account_name,
        "legal_name": legal_name,
        "dba_name": dba_name,
        "best_similarity": round(best, 4),
        "name_matches": best >= 0.85,
    }


def check_bank_jurisdiction(*, bank_country: str, operating_country: str) -> dict[str, Any]:
    return {
        "bank_country": bank_country,
        "operating_country": operating_country,
        "jurisdiction_mismatch": bank_country.upper() != operating_country.upper(),
    }


# --- callback -----------------------------------------------------------------------

def contact_of_record(*, vendor: Vendor, supplied_phone: str | None) -> dict[str, Any]:
    """Return ONLY the number of record.

    A request that supplies its own phone number is offering to verify itself; the number is
    recorded as a signal and then never dialled. This is the tool that makes principle 1
    mechanical rather than aspirational.
    """
    return {
        "dialing": vendor.contact_phone_of_record,
        "source": "system_of_record",
        "request_supplied_phone": supplied_phone,
        "request_supplied_its_own_number": bool(supplied_phone),
        "ignored_supplied_number": bool(supplied_phone),
    }


# --- sentry -------------------------------------------------------------------------

def read_vendor_banking(*, vendor: Vendor) -> dict[str, Any]:
    """Read the vendor's banking details of record.

    Deliberately scoped to `vendor:banking:read`, which Callback is denied. Callback exists to
    phone a number from the system of record; handing it the account data it is verifying would
    defeat the separation the control depends on.
    """
    b = vendor.banking
    return {
        "account_name": b.account_name,
        "account_last4": b.account_last4,
        "routing_last4": b.routing_last4,
        "bank_name": b.bank_name,
        "bank_country": b.bank_country,
    }


def scheduled_exposure(*, payments: list[Payment]) -> dict[str, Any]:
    total = sum((p.amount for p in payments), Decimal("0"))
    return {
        "payment_ids": [p.payment_id for p in payments],
        "count": len(payments),
        "total": str(total),
    }


# --- threat intelligence -------------------------------------------------------------

def compose_threat_library_entry(
    *, designation: str, assessment: str, tradecraft: list[str], indicators: list[str],
    likely_next_target: str, confidence: float, first_seen_case_id: str, authored_by: str,
    model: str,
) -> dict[str, Any]:
    """Normalise a dossier into the row the threat library stores.

    The pen on the library lives here so the grant is exercised on the path that actually
    writes it. Scribe holds `threatintel:write`; Red Team, Hunter and the precedent clerk are
    denied it, and a denial that only a monkeypatched tool can demonstrate is not enforcement.
    """
    text = re.sub(r"^\s*operation\s+", "", str(designation), flags=re.I).strip().strip("\"'")
    words = [w for w in re.split(r"[^A-Za-z]+", text) if w][:2]
    return {
        "designation": " ".join(w.capitalize() for w in words) or "Unnamed Operation",
        "assessment": assessment,
        # Six is what an operator reads before scrolling; a model handed no ceiling writes twenty.
        "tradecraft": list(tradecraft)[:6],
        "indicators": list(indicators)[:6],
        "likely_next_target": likely_next_target,
        "confidence": float(confidence),
        "first_seen_case_id": first_seen_case_id,
        "authored_by": authored_by,
        "model": model,
    }


def read_threat_library(*, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project the library down to tradecraft, dropping who it was used against.

    A reader wants to know how an operation works. The victim vendor ids in each sighting are
    the district's supplier list, and a reader granted `threatintel:read` has not been granted
    `erp:vendor:read` — most sharply for the red team, which is told about its sandbox target
    and must learn nothing about the district's real ones.
    """
    return [
        {
            "designation": op.get("designation"),
            "dossier": op.get("dossier", {}),
            "fingerprint": op.get("fingerprint", {}),
            "sighting_count": op.get("sighting_count", 1),
        }
        for op in operations
    ]


TOOL_SPECS: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec("analyze_sender_domain", Scope.ARTIFACT_READ,
                 "Compare artifact addresses against the vendor domain of record.", analyze_sender_domain),
        ToolSpec("inspect_document_metadata", Scope.ARTIFACT_READ,
                 "Inspect document producer metadata and thread-hijack markers.", inspect_document_metadata),
        ToolSpec("relationship_baseline", Scope.ERP_VENDOR_READ,
                 "Vendor tenure, invoice history and prior banking-change frequency.", relationship_baseline),
        ToolSpec("correlate_open_invoice", Scope.ERP_INVOICES_READ,
                 "Verify a referenced invoice exists and is genuinely open.", correlate_open_invoice),
        ToolSpec("match_account_holder", Scope.ENTITY_LOOKUP,
                 "Compare the proposed account holder name to the legal entity.", match_account_holder),
        ToolSpec("check_bank_jurisdiction", Scope.ENTITY_LOOKUP,
                 "Compare bank jurisdiction to the vendor operating country.", check_bank_jurisdiction),
        ToolSpec("contact_of_record", Scope.VENDOR_CONTACT_READ,
                 "Return the vendor callback number from the system of record only.", contact_of_record),
        ToolSpec("read_vendor_banking", Scope.VENDOR_BANKING_READ,
                 "Read the vendor banking details of record.", read_vendor_banking),
        ToolSpec("scheduled_exposure", Scope.PAYMENTS_FREEZE,
                 "Sum the vendor's scheduled payments to compute exposure.", scheduled_exposure),
        ToolSpec("read_threat_library", Scope.THREATINTEL_READ,
                 "Read named operations and their tradecraft, without the victims.",
                 read_threat_library),
        ToolSpec("write_threat_library", Scope.THREATINTEL_WRITE,
                 "Normalise a dossier into the threat library's stored row.",
                 compose_threat_library_entry),
    )
}
