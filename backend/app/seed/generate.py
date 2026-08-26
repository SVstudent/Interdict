"""Synthetic corpus.

Everything here is invented. No real companies, people, banks, or email addresses — every domain
sits under .test, which RFC 2606 reserves precisely so it can never resolve. The UI carries a
persistent banner saying so.

Deterministic: seeded from a fixed value so the same corpus is produced on every machine, which
is what makes replay-mode rehearsals and audit hashes reproducible.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..models.domain import (
    BankingChange,
    BankingDetails,
    ChangeRequest,
    Invoice,
    Payment,
    Vendor,
)
from ..store.base import Repository

SEED = 20260803

# The vendor book of a mid-size public school district: the suppliers a district business
# manager actually pays. Chosen over generic corporate vendors because the operator this product
# is built for is a district business manager, not a corporate AP controller — see
# context/PRODUCT.md and DECISIONS D-014.
INDUSTRY_STEMS = [
    ("Northwind Student Transport", "transport"), ("Calder Food Services", "nutrition"),
    ("Brightmoor Facilities", "facilities"), ("Vantage Educational Print", "print"),
    ("Ashfield Science Supply", "instructional"), ("Kestrel Athletic Equipment", "athletics"),
    ("Lowry Custodial Supply", "facilities"), ("Redgate Student Information Systems", "technology"),
    ("Halloway Uniform", "athletics"), ("Pemberton Playground Systems", "facilities"),
    ("Ironbridge Roofing", "capital"), ("Selkirk Bus Maintenance", "transport"),
    ("Merrow Electrical Contracting", "capital"), ("Thornbury Window", "capital"),
    ("Alderwood Library Books", "instructional"), ("Quarry Lane Paving", "capital"),
    ("Fenwick Lab Instruments", "instructional"), ("Garrick Safety Training", "compliance"),
    ("Padstow Special Education Services", "student services"),
    ("Culver Road Driver Training", "transport"),
]

SUFFIXES = ["LLC", "Inc.", "Ltd.", "Group", "Holdings", "Partners", "Works", "Co."]
BANKS = [
    ("First Meridian Bank", "US"), ("Cascade Union Trust", "US"), ("Harbor Point Bank", "US"),
    ("Stonebridge Commercial", "US"), ("Lakeshore National", "US"), ("Granite Fidelity", "US"),
]


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace(".", "").replace(",", "")


def _banking(rng: random.Random, holder: str, when: datetime, country: str = "US") -> BankingDetails:
    bank, bank_country = rng.choice(BANKS)
    return BankingDetails(
        account_name=holder,
        account_last4=f"{rng.randint(1000, 9999)}",
        routing_last4=f"{rng.randint(1000, 9999)}",
        bank_name=bank,
        bank_country=country or bank_country,
        effective_from=when,
    )


def build_corpus(now: datetime) -> dict[str, list]:
    """40 vendors with 2-8 year histories, ~200 invoices, 12 scheduled payments."""
    rng = random.Random(SEED)
    vendors: list[Vendor] = []
    invoices: list[Invoice] = []
    payments: list[Payment] = []

    def _join(stem: str, *parts: str) -> str:
        """Append only words the stem does not already end with, so we do not produce
        'Lowry Custodial Supply Supply Co.'"""
        out = [stem]
        for part in parts:
            if part.split()[0].lower().rstrip(".") != out[-1].split()[-1].lower().rstrip("."):
                out.append(part)
        return " ".join(out)

    names: list[str] = []
    for stem, _ in INDUSTRY_STEMS:
        names.append(_join(stem, rng.choice(SUFFIXES)))
    for stem, _ in INDUSTRY_STEMS:
        names.append(_join(stem, rng.choice(["Services", "Supply", "Systems", "Solutions"]),
                           rng.choice(SUFFIXES)))

    for index, legal_name in enumerate(names[:40]):
        tenure_days = rng.randint(2 * 365, 8 * 365)
        onboarded = now - timedelta(days=tenure_days)
        domain = f"{_slug(legal_name.rsplit(' ', 1)[0])}.test"
        invoice_count = rng.randint(20, 260)
        vendor_id = f"V-{index + 1:04d}"

        history: list[BankingChange] = []
        # Most long-standing vendors never change banking details. That is what makes a change
        # notable, so the corpus must not sprinkle them everywhere.
        if rng.random() < 0.15:
            changed_at = onboarded + timedelta(days=rng.randint(200, max(201, tenure_days - 60)))
            previous = _banking(rng, legal_name, onboarded)
            history.append(BankingChange(
                changed_at=changed_at, previous=previous,
                proposed=_banking(rng, legal_name, changed_at),
                reason=rng.choice(["Bank merger", "Treasury consolidation", "Branch closure"]),
            ))

        vendor = Vendor(
            vendor_id=vendor_id,
            legal_name=legal_name,
            dba_name=None,
            onboarded_at=onboarded,
            contact_email_of_record=f"ap@{domain}",
            contact_phone_of_record=f"+1-{rng.randint(200, 989)}-555-{rng.randint(100, 999):04d}"[:16],
            banking=_banking(rng, legal_name, history[-1].changed_at if history else onboarded),
            banking_change_history=history,
            total_paid_lifetime=Decimal(rng.randint(180, 9800) * 1000),
            invoice_count=invoice_count,
            operating_country="US",
        )
        vendors.append(vendor)

        for n in range(5):
            issued = now - timedelta(days=rng.randint(5, 160))
            amount = Decimal(rng.randrange(4_000, 190_000, 500))
            invoices.append(Invoice(
                invoice_id=f"INV-{4000 + index * 5 + n}",
                vendor_id=vendor_id, amount=amount, issued_at=issued,
                due_at=issued + timedelta(days=30),
                status="open" if rng.random() < 0.35 else "paid",
            ))

    # 12 scheduled payments across a subset of vendors.
    for slot, vendor in enumerate(rng.sample(vendors, 12)):
        payments.append(Payment(
            payment_id=f"PAY-{9000 + slot}",
            vendor_id=vendor.vendor_id,
            invoice_id=f"INV-{4000 + slot}",
            amount=Decimal(rng.randrange(12_000, 240_000, 1000)),
            scheduled_for=now + timedelta(days=rng.randint(1, 9)),
        ))

    return {"vendors": vendors, "invoices": invoices, "payments": payments}


# ---------------------------------------------------------------------------------
# Scenario vendors.
#
# Each scenario gets its OWN vendor and its OWN payments. They used to share one vendor, which
# broke the demo: `hold_scheduled_payments` only holds payments in SCHEDULED state, so once S1
# held them, S2 and S3 found nothing and opened with $0 exposure. Beats 2-6 run back-to-back in a
# single take, so every scenario after the first showed zero.
#
# Exposures are also chosen so the deterministic rails produce the outcome the runbook expects:
#
#   S1/S5  $340,000  -> BLOCK. Above the ceiling, but the ceiling never gates a BLOCK.
#   S2      $92,400  -> BLOCK on the poisoned artifact.
#   S3/S4  $186,000  -> between CALLBACK_REQUIRED_THRESHOLD ($50k) and AUTO_RELEASE_CEILING
#                       ($250k). S3 escalates because the callback is unanswered; S4, once the
#                       vendor confirms, can genuinely RELEASE. Above the ceiling it could not:
#                       rail 4 converts any proposed RELEASE over $250k into an ESCALATE, so a
#                       higher figure would make the runbook's S4 outcome unreachable.
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioVendor:
    vendor_id: str
    legal_name: str
    domain: str
    phone: str
    tenure_days: int
    invoice_count: int
    lifetime_paid: str
    payments: tuple[tuple[str, str], ...]   # (payment_id, amount)
    invoices: tuple[tuple[str, str], ...]   # (invoice_id, amount)


SCENARIO_VENDORS: dict[str, ScenarioVendor] = {
    # S1, S5 — the flagship. The district's school-bus contractor: six years, zero prior banking
    # changes, and the single largest recurring payment the business manager signs.
    "V-9001": ScenarioVendor(
        vendor_id="V-9001",
        legal_name="Northwind Student Transport LLC",
        domain="northwind-transport.test",
        phone="+1-503-555-0142",
        tenure_days=int(6.2 * 365),
        invoice_count=212,
        lifetime_paid="4820000.00",
        payments=(("PAY-8801", "150000.00"), ("PAY-8802", "190000.00")),
        invoices=(("INV-4471", "150000.00"), ("INV-4488", "190000.00")),
    ),
    # S2 — poisoned attachment from the science-supply vendor.
    "V-9002": ScenarioVendor(
        vendor_id="V-9002",
        legal_name="Ashfield Science Supply Ltd.",
        domain="ashfield-science.test",
        phone="+1-614-555-0188",
        tenure_days=int(4.1 * 365),
        invoice_count=88,
        lifetime_paid="1310000.00",
        payments=(("PAY-8811", "56900.00"), ("PAY-8812", "35500.00")),
        invoices=(("INV-5120", "56900.00"), ("INV-5133", "35500.00")),
    ),
    # S3, S4 — a genuine post-acquisition change. Exposure deliberately under the ceiling so S4
    # can actually RELEASE (D-012).
    "V-9003": ScenarioVendor(
        vendor_id="V-9003",
        legal_name="Kestrel Athletic Equipment Inc.",
        domain="kestrel-athletic.test",
        phone="+1-408-555-0121",
        tenure_days=int(7.4 * 365),
        invoice_count=163,
        lifetime_paid="3960000.00",
        payments=(("PAY-8821", "118000.00"), ("PAY-8822", "68000.00")),
        invoices=(("INV-6204", "118000.00"), ("INV-6217", "68000.00")),
    ),
}

# Which vendor each scenario acts on.
SCENARIO_VENDOR_FOR: dict[str, str] = {
    "S1": "V-9001", "S5": "V-9001",
    "S2": "V-9002",
    "S3": "V-9003", "S4": "V-9003",
}


def build_scenario_vendor(spec: ScenarioVendor, now: datetime) -> Vendor:
    onboarded = now - timedelta(days=spec.tenure_days)
    # If a real demo phone is configured, it becomes the vendor's number OF RECORD. That is the
    # point: the operator dials the number the system already holds, never the one the request
    # supplied.
    from ..config import Settings

    phone = Settings().CALLBACK_DEMO_PHONE or spec.phone
    return Vendor(
        vendor_id=spec.vendor_id,
        legal_name=spec.legal_name,
        dba_name=spec.legal_name.rsplit(" ", 1)[0],
        onboarded_at=onboarded,
        contact_email_of_record=f"ap@{spec.domain}",
        contact_phone_of_record=phone,
        banking=BankingDetails(
            account_name=spec.legal_name,
            account_last4="4417",
            routing_last4="0021",
            bank_name="First Meridian Bank",
            bank_country="US",
            effective_from=onboarded,
        ),
        banking_change_history=[],   # zero prior changes: what makes a change notable
        total_paid_lifetime=Decimal(spec.lifetime_paid),
        invoice_count=spec.invoice_count,
        operating_country="US",
    )


def build_scenario_payments(spec: ScenarioVendor, now: datetime) -> list[Payment]:
    return [
        Payment(
            payment_id=pid,
            vendor_id=spec.vendor_id,
            invoice_id=spec.invoices[i][0] if i < len(spec.invoices) else None,
            amount=Decimal(amount),
            scheduled_for=now + timedelta(days=2 + i * 2),
        )
        for i, (pid, amount) in enumerate(spec.payments)
    ]


def build_scenario_invoices(spec: ScenarioVendor, now: datetime) -> list[Invoice]:
    return [
        Invoice(
            invoice_id=iid,
            vendor_id=spec.vendor_id,
            amount=Decimal(amount),
            issued_at=now - timedelta(days=22 - i * 8),
            due_at=now + timedelta(days=8 + i * 8),
            status="open",
        )
        for i, (iid, amount) in enumerate(spec.invoices)
    ]


def scenario_exposure(scenario_id: str) -> Decimal:
    """Expected exposure for a scenario. Used by tests to assert the fixture still lines up
    with the adjudication thresholds."""
    spec = SCENARIO_VENDORS[SCENARIO_VENDOR_FOR[scenario_id]]
    return sum((Decimal(a) for _, a in spec.payments), Decimal("0"))


async def seed_all(repo: Repository, now: datetime) -> dict[str, int]:
    corpus = build_corpus(now)
    for vendor in corpus["vendors"]:
        await repo.save_vendor(vendor)
    for invoice in corpus["invoices"]:
        await repo.save_invoice(invoice)
    for payment in corpus["payments"]:
        await repo.save_payment(payment)

    # One vendor per scenario, each with its own payments, so running the beats back to back
    # does not leave later scenarios with nothing to hold.
    s_vendors = s_invoices = s_payments = 0
    for spec in SCENARIO_VENDORS.values():
        await repo.save_vendor(build_scenario_vendor(spec, now))
        s_vendors += 1
        for invoice in build_scenario_invoices(spec, now):
            await repo.save_invoice(invoice)
            s_invoices += 1
        for payment in build_scenario_payments(spec, now):
            await repo.save_payment(payment)
            s_payments += 1

    return {
        "vendors": len(corpus["vendors"]) + s_vendors,
        "invoices": len(corpus["invoices"]) + s_invoices,
        "payments": len(corpus["payments"]) + s_payments,
    }
