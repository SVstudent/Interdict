"""The schema files in schemas/ are the frontend's contract. Guard them.

A model change that is not reflected in schemas/ is a silent break: the TypeScript types stop
matching the wire format and the UI fails at runtime rather than at build time.
"""
from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import pytest

from app.models.export_schema import WIRE_MODELS, api_contract, invariants

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def test_schema_directory_exists():
    assert SCHEMA_DIR.is_dir(), "run `make schemas` to generate schemas/"


@pytest.mark.parametrize("name", sorted(WIRE_MODELS))
def test_committed_schema_matches_the_model(name):
    """Fails when a Pydantic model changed but schemas/ was not regenerated."""
    path = SCHEMA_DIR / f"{name}.schema.json"
    assert path.exists(), f"missing {path.name}; run `make schemas`"
    committed = json.loads(path.read_text())
    current = WIRE_MODELS[name].model_json_schema()
    assert committed == current, (
        f"{name}.schema.json has drifted from the model. Run `make schemas` and commit the result."
    )


def test_money_serialises_as_a_decimal_string_not_a_float():
    """Money must cross the wire as a string, or a JS consumer loses cents to float64.

    Note the SCHEMA legitimately declares anyOf[number, string] — that is Pydantic describing what
    it ACCEPTS on input. What matters is what we EMIT, so assert the runtime, not the schema.
    """
    from datetime import datetime
    from decimal import Decimal

    from app.models.domain import Invoice, Payment

    p = Payment(
        payment_id="PAY-1", vendor_id="V-1", amount=Decimal("340000.005"),
        scheduled_for=datetime(2026, 8, 3, tzinfo=UTC),
    )
    dumped = p.model_dump(mode="json")["amount"]
    assert isinstance(dumped, str), f"Payment.amount emitted {type(dumped).__name__}, not str"
    # Full precision must survive; float64 would round this.
    assert dumped == "340000.005"

    inv = Invoice(
        invoice_id="INV-1", vendor_id="V-1", amount=Decimal("0.01"),
        issued_at=datetime(2026, 8, 1, tzinfo=UTC),
        due_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert isinstance(inv.model_dump(mode="json")["amount"], str)


def test_money_schema_offers_a_string_branch_for_codegen():
    """A type generator must be able to pick the string branch. If Pydantic ever stops offering
    one, generated TypeScript would type money as `number` and silently corrupt it."""
    for name in ("Payment", "Invoice"):
        schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
        branches = schema["properties"]["amount"].get("anyOf", [schema["properties"]["amount"]])
        assert any(b.get("type") == "string" for b in branches), (
            f"{name}.amount schema has no string branch"
        )


def test_banking_details_never_expose_full_numbers():
    """INV-6. A schema that permitted a full account number would be a data-handling defect."""
    schema = json.loads((SCHEMA_DIR / "BankingDetails.schema.json").read_text())
    props = schema["properties"]
    assert set(props) & {"account_last4", "routing_last4"}
    assert "account_number" not in props
    assert "routing_number" not in props
    assert props["account_last4"]["pattern"] == r"^\d{4}$"


def test_every_invariant_names_its_enforcement_site():
    for inv in invariants()["invariants"]:
        assert inv["enforced_by"], f"{inv['id']} claims no enforcement site"
        assert "/" in inv["enforced_by"] or "." in inv["enforced_by"]


def test_api_contract_flags_the_endpoints_that_cost_money():
    """Anyone reading the contract must be able to see which calls spend tokens."""
    paying = [e for e in api_contract()["endpoints"] if "MODEL CALLS" in str(e.get("cost", ""))]
    assert paying, "inject_scenario must be flagged as costing money"
    assert any("inject_scenario" in e["path"] for e in paying)


# --- replay cache durability --------------------------------------------------

async def test_replay_cache_survives_a_process_restart(tmp_path):
    """The cache existed only in process memory, so every backend restart discarded it and the
    next run had to hit the models again — which made replay useless as a quota workaround."""
    from app.config import DemoMode, Settings
    from app.demo.replay import ReplayCache
    from app.store.memory import InMemoryRepository

    cache_file = tmp_path / "replay_cache.json"

    # Process 1 records.
    recording = ReplayCache(InMemoryRepository(), Settings(DEMO_MODE=DemoMode.RECORD), cache_file)
    await recording.store("hash-abc", {"verdict": "contradicts", "confidence": 0.94})
    assert await recording.flush() == 1
    assert cache_file.exists()

    # Process 2, fresh repository, replays.
    fresh_repo = InMemoryRepository()
    replaying = ReplayCache(fresh_repo, Settings(DEMO_MODE=DemoMode.REPLAY), cache_file)
    assert await replaying.load() == 1
    assert (await replaying.lookup("hash-abc"))["verdict"] == "contradicts"


async def test_replay_mode_never_writes_to_the_cache(tmp_path):
    from app.config import DemoMode, Settings
    from app.demo.replay import ReplayCache
    from app.store.memory import InMemoryRepository

    cache_file = tmp_path / "replay_cache.json"
    cache = ReplayCache(InMemoryRepository(), Settings(DEMO_MODE=DemoMode.REPLAY), cache_file)
    await cache.store("hash-xyz", {"verdict": "supports"})
    assert await cache.flush() == 0
    assert not cache_file.exists()


async def test_a_missing_cache_file_is_not_an_error(tmp_path):
    """A fresh clone has no cache. That must degrade to zero entries, not crash startup."""
    from app.config import Settings
    from app.demo.replay import ReplayCache
    from app.store.memory import InMemoryRepository

    cache = ReplayCache(InMemoryRepository(), Settings(), tmp_path / "absent.json")
    assert await cache.load() == 0
