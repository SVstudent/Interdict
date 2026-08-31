"""The second district.

One instance, two districts, one exchange. Everything `generate.py` seeds belongs to Riverbend,
which is what it always was; this module adds Harborview alongside it with its own vendor book,
its own invoices and its own scheduled payments.

The two books share nothing — no vendor, no bank relationship, no supplier category on the
targeted side. That separation is the whole point of the demonstration: when Harborview
recognises the operators who hit Riverbend, the ONLY thing linking the two cases is the
tradecraft. If the districts shared a supplier, a sceptical judge would rightly read the
recognition as a vendor lookup rather than intelligence crossing a boundary.

Synthetic, like the rest of `seed/`: invented names, `.test` domains that RFC 2606 guarantees
can never resolve.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..models.domain import (
    DEFAULT_TENANT_ID,
    BankingDetails,
    ChangeRequest,
    Invoice,
    Payment,
    Tenant,
    Vendor,
)
from ..store.base import Repository
from .scenarios import _lookalike

SECOND_TENANT_ID = "harborview"

# `short_name` is badge text at 13px, so it is a word rather than an abbreviation — an operator
# glancing at a case row needs to read which district owns it, not decode it.
TENANTS: dict[str, Tenant] = {
    DEFAULT_TENANT_ID: Tenant(
        tenant_id=DEFAULT_TENANT_ID,
        display_name="Riverbend Unified School District",
        short_name="Riverbend",
    ),
    SECOND_TENANT_ID: Tenant(
        tenant_id=SECOND_TENANT_ID,
        display_name="Harborview County Schools",
        short_name="Harborview",
    ),
}


def tenant(tenant_id: str) -> Tenant | None:
    return TENANTS.get(tenant_id)


@dataclass(frozen=True)
class TenantVendor:
    """A literal spec rather than a seeded rng draw. Harborview's book is small enough to state
    outright, and the cross-district scenario depends on the targeted vendor's exact tenure and
    domain, which a generator would silently move the next time it changed."""

    vendor_id: str
    legal_name: str
    domain: str
    phone: str
    tenure_days: int
    invoice_count: int
    lifetime_paid: str
    bank: str
    payments: tuple[tuple[str, str], ...]   # (payment_id, amount)
    invoices: tuple[tuple[str, str], ...]   # (invoice_id, amount)


# Harborview's suppliers. Deliberately a different corner of the K-12 book from Riverbend's
# transport-and-facilities corpus, and V-2001 in particular is a food-service vendor precisely
# because Riverbend's flagship victim is a school-bus contractor.
HARBORVIEW_VENDORS: tuple[TenantVendor, ...] = (
    TenantVendor(
        vendor_id="V-2001",
        legal_name="Tidewater School Nutrition LLC",
        domain="tidewater-nutrition.test",
        phone="+1-207-555-0164",
        tenure_days=int(5.4 * 365),
        invoice_count=176,
        lifetime_paid="3140000.00",
        bank="Granite Fidelity",
        payments=(("PAY-6001", "128000.00"), ("PAY-6002", "96000.00")),
        invoices=(("INV-3101", "128000.00"), ("INV-3117", "96000.00")),
    ),
    TenantVendor(
        vendor_id="V-2002",
        legal_name="Marrowfield Textbook Depot Inc.",
        domain="marrowfield-depot.test",
        phone="+1-207-555-0177",
        tenure_days=int(8.1 * 365),
        invoice_count=241,
        lifetime_paid="2280000.00",
        bank="Lakeshore National",
        payments=(("PAY-6011", "44500.00"),),
        invoices=(("INV-3204", "44500.00"),),
    ),
    TenantVendor(
        vendor_id="V-2003",
        legal_name="Quillon Grounds Maintenance Co.",
        domain="quillon-grounds.test",
        phone="+1-207-555-0132",
        tenure_days=int(3.7 * 365),
        invoice_count=94,
        lifetime_paid="612000.00",
        bank="Stonebridge Commercial",
        payments=(("PAY-6021", "31800.00"),),
        invoices=(("INV-3308", "31800.00"),),
    ),
    TenantVendor(
        vendor_id="V-2004",
        legal_name="Beacon Hill Speech Therapy Partners",
        domain="beaconhill-speech.test",
        phone="+1-207-555-0119",
        tenure_days=int(6.6 * 365),
        invoice_count=308,
        lifetime_paid="1870000.00",
        bank="Harbor Point Bank",
        payments=(("PAY-6031", "72400.00"),),
        invoices=(("INV-3412", "72400.00"),),
    ),
    TenantVendor(
        vendor_id="V-2005",
        legal_name="Saltmarsh Instrument Repair Ltd.",
        domain="saltmarsh-instrument.test",
        phone="+1-207-555-0155",
        tenure_days=int(4.9 * 365),
        invoice_count=61,
        lifetime_paid="404000.00",
        bank="First Meridian Bank",
        payments=(),
        invoices=(("INV-3520", "18900.00"),),
    ),
    TenantVendor(
        vendor_id="V-2006",
        legal_name="Wrenfield HVAC Systems LLC",
        domain="wrenfield-hvac.test",
        phone="+1-207-555-0148",
        tenure_days=int(7.2 * 365),
        invoice_count=139,
        lifetime_paid="2960000.00",
        bank="Cascade Union Trust",
        payments=(("PAY-6041", "165000.00"),),
        invoices=(("INV-3611", "165000.00"),),
    ),
    TenantVendor(
        vendor_id="V-2007",
        legal_name="Dunmore Crossing Guard Services LLC",
        domain="dunmore-crossing.test",
        phone="+1-207-555-0126",
        tenure_days=int(2.8 * 365),
        invoice_count=52,
        lifetime_paid="288000.00",
        bank="Granite Fidelity",
        payments=(),
        invoices=(("INV-3704", "9600.00"),),
    ),
    TenantVendor(
        vendor_id="V-2008",
        legal_name="Alnwick Data Cabling Group",
        domain="alnwick-cabling.test",
        phone="+1-207-555-0193",
        tenure_days=int(5.1 * 365),
        invoice_count=87,
        lifetime_paid="1140000.00",
        bank="Harbor Point Bank",
        payments=(("PAY-6051", "58200.00"),),
        invoices=(("INV-3808", "58200.00"),),
    ),
)

# The vendor the shared operators hit second. Named so the demo control plane and the tests refer
# to the same record rather than each picking a row out of the book.
CROSS_DISTRICT_TARGET = HARBORVIEW_VENDORS[0]

# What Tidewater's real accounts-receivable contact says when Callback dials the number on file,
# which is not the number the artifact supplied. It lives here, beside the request it belongs to,
# for the same reason every other scenario's does: the runbook forbids the API layer deciding a
# callback outcome. Harborview's vendor denies the change exactly as Riverbend's did — same
# operators, same lie, a district that had never heard of either.
CROSS_DISTRICT_CALLBACK = "denied"


def build_tenant_vendor(spec: TenantVendor, now: datetime) -> Vendor:
    onboarded = now - timedelta(days=spec.tenure_days)
    return Vendor(
        vendor_id=spec.vendor_id,
        tenant_id=SECOND_TENANT_ID,
        legal_name=spec.legal_name,
        dba_name=None,
        onboarded_at=onboarded,
        contact_email_of_record=f"ap@{spec.domain}",
        contact_phone_of_record=spec.phone,
        banking=BankingDetails(
            account_name=spec.legal_name,
            account_last4=spec.vendor_id[-4:],
            routing_last4="0088",
            bank_name=spec.bank,
            bank_country="US",
            effective_from=onboarded,
        ),
        banking_change_history=[],
        total_paid_lifetime=Decimal(spec.lifetime_paid),
        invoice_count=spec.invoice_count,
        operating_country="US",
    )


def build_tenant_payments(spec: TenantVendor, now: datetime) -> list[Payment]:
    return [
        Payment(
            payment_id=pid,
            vendor_id=spec.vendor_id,
            tenant_id=SECOND_TENANT_ID,
            invoice_id=spec.invoices[i][0] if i < len(spec.invoices) else None,
            amount=Decimal(amount),
            scheduled_for=now + timedelta(days=3 + i * 2),
        )
        for i, (pid, amount) in enumerate(spec.payments)
    ]


def build_tenant_invoices(spec: TenantVendor, now: datetime) -> list[Invoice]:
    return [
        Invoice(
            invoice_id=iid,
            vendor_id=spec.vendor_id,
            amount=Decimal(amount),
            issued_at=now - timedelta(days=19 - i * 7),
            due_at=now + timedelta(days=11 + i * 7),
            status="open",
        )
        for i, (iid, amount) in enumerate(spec.invoices)
    ]


CROSS_DISTRICT_BODY = """Hi Business Office,

Our group completed a treasury consolidation this month and our receiving account has moved.
Please update remittance for invoice {invoice} before the next disbursement run.

New beneficiary: NW Holdings Group
Account ending 4180 / routing ending 2265 — Stonebridge Commercial

I am covering AR while our controller is out, so please reach me directly on {phone}.

Regards,
Daniel Reyes
Accounts Receivable, Tidewater School Nutrition
"""


def build_cross_district_request(now: datetime, request_id: str) -> ChangeRequest:
    """The same operators, the second district, a vendor with nothing in common with the first.

    The lookalike is built with `scenarios._lookalike`, the helper Riverbend's own scenarios use.
    Reusing it is the point rather than an economy: hand-rolling a second lookalike would produce
    a different technique, and the recognition would then be an artefact of the fixture instead of
    the same tradecraft turning up twice.

    The receiving bank is deliberately NOT the one used against Riverbend. A mule account gets
    frozen once its first victim files, so the operators open the next one elsewhere — and a
    fixture that repeated every field byte for byte would prove only that identical inputs match
    identically. Beneficiary, substitution, domain freshness and the attacker's own callback
    number carry over, which is what actually survives between victims, and the recognition has
    to be earned on those.
    """
    spec = CROSS_DISTRICT_TARGET
    invoice = spec.invoices[0][0]
    real = spec.domain
    lookalike = _lookalike(real)
    supplied_phone = "+1-702-555-0199"

    return ChangeRequest(
        request_id=request_id,
        vendor_id=spec.vendor_id,
        channel="email",
        received_at=now,
        raw_artifact=CROSS_DISTRICT_BODY.format(invoice=invoice, phone=supplied_phone),
        artifact_metadata={
            "from": f"d.reyes@{real}",
            "reply_to": f"d.reyes@{lookalike}",
            "reply_to_domain_registered_at": now - timedelta(days=6),
            "referenced_invoice": invoice,
            "supplied_phone": supplied_phone,
            "baseline_producer": "Sage Intacct PDF Writer 9.2",
            "subject": f"Updated remittance details — invoice {invoice}",
        },
        proposed_banking=BankingDetails(
            account_name="NW Holdings Group",
            account_last4="4180",
            routing_last4="2265",
            bank_name="Stonebridge Commercial",
            bank_country="US",
            effective_from=now,
        ),
        claimed_reason="Treasury consolidation",
    )


async def seed_tenants(repo: Repository, now: datetime) -> dict[str, int]:
    """Seed the districts `generate.seed_all` does not.

    Riverbend is already in the store by the time this runs — every record `generate.py` writes
    defaults to it — so this adds Harborview's book and nothing else. Idempotent by construction:
    every id is a literal, so a second run overwrites rather than duplicates.
    """
    vendors = invoices = payments = 0
    for spec in HARBORVIEW_VENDORS:
        await repo.save_vendor(build_tenant_vendor(spec, now))
        vendors += 1
        for invoice in build_tenant_invoices(spec, now):
            await repo.save_invoice(invoice)
            invoices += 1
        for payment in build_tenant_payments(spec, now):
            await repo.save_payment(payment)
            payments += 1

    return {"tenants": len(TENANTS), "vendors": vendors,
            "invoices": invoices, "payments": payments}
