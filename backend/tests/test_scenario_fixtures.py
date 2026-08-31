"""The fixtures must stay consistent with the adjudication thresholds.

Two defects motivated this file, both found only by running the scenarios back to back:

1. All scenarios shared one vendor. `hold_scheduled_payments` only holds payments in SCHEDULED
   state, so once S1 held them, S2 and S3 opened with $0 exposure. Beats 2-6 run consecutively in
   a single recorded take, so every beat after the first showed zero.

2. S3 and S4 share a vendor, and the runbook expects S3 -> ESCALATE, S4 -> RELEASE. But rail 4
   converts any proposed RELEASE above AUTO_RELEASE_CEILING into an ESCALATE. With exposure above
   the ceiling, S4's documented outcome was unreachable.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import Settings
from app.seed.generate import (
    SCENARIO_VENDOR_FOR,
    SCENARIO_VENDORS,
    scenario_exposure,
    seed_all,
)
from app.seed.scenarios import CATALOG, build_request
from app.store.memory import InMemoryRepository

SETTINGS = Settings()


def test_every_scenario_maps_to_a_seeded_vendor():
    for scenario_id in CATALOG:
        assert scenario_id in SCENARIO_VENDOR_FOR, f"{scenario_id} has no vendor mapping"
        assert SCENARIO_VENDOR_FOR[scenario_id] in SCENARIO_VENDORS


def test_scenarios_that_run_consecutively_do_not_share_a_vendor():
    """S1, S2 and S3 run as beats 2, 3 and 4 of one take. If they shared a vendor, the second and
    third would find no SCHEDULED payments left to hold."""
    consecutive = ["S1", "S2", "S3"]
    vendors = [SCENARIO_VENDOR_FOR[s] for s in consecutive]
    assert len(set(vendors)) == len(vendors), (
        f"beats 2-4 share vendors {vendors}; later beats will open with $0 exposure"
    )


def test_s4_exposure_is_below_the_auto_release_ceiling():
    """Otherwise the runbook's S4 RELEASE is unreachable: rail 4 forces ESCALATE
    above the ceiling."""
    exposure = scenario_exposure("S4")
    assert exposure <= SETTINGS.AUTO_RELEASE_CEILING, (
        f"S4 exposure {exposure} exceeds the ${SETTINGS.AUTO_RELEASE_CEILING} ceiling, so it can "
        f"never RELEASE. Lower the fixture or raise the ceiling deliberately."
    )


def test_s3_exposure_is_above_the_callback_threshold():
    """S3's documented ESCALATE is driven by an unanswered callback, which only gates above the
    threshold. Below it, S3 would not escalate for the stated reason."""
    exposure = scenario_exposure("S3")
    assert exposure > SETTINGS.CALLBACK_REQUIRED_THRESHOLD


def test_s1_exposure_is_the_headline_figure():
    """Beat 2 is scripted around $340,000, and it must be the sum of real payment documents."""
    assert scenario_exposure("S1") == Decimal("340000.00")


@pytest.mark.parametrize("scenario_id", sorted(CATALOG))
def test_scenario_request_references_its_own_vendors_invoice(scenario_id):
    from app.config import DEMO_EPOCH

    spec = SCENARIO_VENDORS[SCENARIO_VENDOR_FOR[scenario_id]]
    request = build_request(scenario_id, DEMO_EPOCH, "REQ-TEST")
    assert request.vendor_id == spec.vendor_id
    assert request.artifact_metadata["referenced_invoice"] in {i for i, _ in spec.invoices}


@pytest.mark.parametrize("scenario_id", ["S1", "S2", "S5"])
def test_fraud_scenarios_use_a_homoglyph_lookalike_reply_to(scenario_id):
    from app.config import DEMO_EPOCH

    spec = SCENARIO_VENDORS[SCENARIO_VENDOR_FOR[scenario_id]]
    meta = build_request(scenario_id, DEMO_EPOCH, "REQ-TEST").artifact_metadata
    assert meta["reply_to"].split("@")[-1] != spec.domain, "reply-to must diverge"
    assert meta["from"].split("@")[-1] == spec.domain, "from must be the real domain"


@pytest.mark.parametrize("scenario_id", ["S3", "S4"])
def test_genuine_scenarios_have_clean_provenance(scenario_id):
    """S3/S4 must be genuinely clean, or the ESCALATE is really just a disguised BLOCK."""
    from app.config import DEMO_EPOCH

    spec = SCENARIO_VENDORS[SCENARIO_VENDOR_FOR[scenario_id]]
    meta = build_request(scenario_id, DEMO_EPOCH, "REQ-TEST").artifact_metadata
    assert meta["reply_to"].split("@")[-1] == spec.domain
    assert "supplied_phone" not in meta or not meta.get("supplied_phone")


async def test_each_scenario_vendor_has_holdable_payments_after_seeding():
    from app.config import DEMO_EPOCH
    from app.models.domain import PaymentStatus

    repo = InMemoryRepository()
    await seed_all(repo, DEMO_EPOCH)
    for vendor_id, spec in SCENARIO_VENDORS.items():
        payments = await repo.list_payments(vendor_id)
        schedulable = [p for p in payments if p.status is PaymentStatus.SCHEDULED]
        assert len(schedulable) == len(spec.payments), (
            f"{vendor_id} has {len(schedulable)} holdable payments, expected {len(spec.payments)}"
        )
        total = sum((p.amount for p in schedulable), Decimal("0"))
        assert total == scenario_exposure(
            next(s for s, v in SCENARIO_VENDOR_FOR.items() if v == vendor_id)
        )
