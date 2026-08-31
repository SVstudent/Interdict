"""Intake triage.

The fleet costs six model calls and roughly forty seconds per case. Pointing it at every message
in a business office inbox would be unaffordable, so Sentry decides what deserves it. These tests
pin that decision: it must catch every attack, spend almost nothing doing so, and — the part that
actually bites — must not open a case on ordinary correspondence.
"""
from __future__ import annotations

import pytest

from app.agents.sentry import SentryAgent
from app.config import DEMO_EPOCH, Settings
from app.seed.inbox import build_inbox
from app.seed.scenarios import build_request

SENTRY = SentryAgent(Settings())


def _inbox():
    messages = build_inbox(DEMO_EPOCH)
    for m in messages:
        if m.scenario_id:
            m.body = build_request(m.scenario_id, DEMO_EPOCH, "REQ-X").raw_artifact
    return messages


def _classify(message) -> str:
    money, change = SENTRY._scan(f"{message.subject}\n{message.body}")
    if not money:
        return "ignore_free"
    if change:
        return "investigate_free"
    return "ambiguous"


def test_the_inbox_is_mostly_ordinary_correspondence():
    """If the inbox were all attacks the triage would be demonstrating nothing."""
    messages = _inbox()
    attacks = [m for m in messages if m.scenario_id]
    assert len(messages) >= 25
    assert len(attacks) == 3
    assert len(attacks) / len(messages) < 0.2


def test_every_attack_is_caught():
    """A missed payee-change request is money out the door. This is the one that must never fail."""
    missed = [
        m.scenario_id for m in _inbox()
        if m.scenario_id and _classify(m) == "ignore_free"
    ]
    assert missed == [], f"triage ignored real attacks: {missed}"


def test_no_ordinary_message_is_flagged_for_investigation():
    """A false positive costs six model calls and puts a phantom interdiction in front of the
    operator. Substring matching once flagged a custodial invoice because 'ach' appears inside
    'attaching' and 'change' inside 'no change to the hours'."""
    wrong = [
        m.subject for m in _inbox()
        if not m.scenario_id and _classify(m) == "investigate_free"
    ]
    assert wrong == [], f"ordinary correspondence flagged: {wrong}"


def test_triage_settles_the_overwhelming_majority_without_a_model_call():
    messages = _inbox()
    free = sum(1 for m in messages if _classify(m) != "ambiguous")
    assert free / len(messages) >= 0.9, (
        f"only {free}/{len(messages)} settled for free; intake is too expensive to run at scale"
    )


@pytest.mark.parametrize("term,inside_word", [
    ("ach", "We are attaching the invoice."),
    ("ach", "Each site reported in."),
    ("eft", "The truck left after the delivery."),
    ("wire", "The wireless access point is down."),
])
def test_money_terms_do_not_match_inside_other_words(term, inside_word):
    money, _ = SENTRY._scan(inside_word)
    assert not money, f"'{term}' matched as a substring in {inside_word!r}"


@pytest.mark.parametrize("text", [
    "Please update our remittance bank account details.",
    "Our new banking details are effective immediately.",
    "We have changed the account funds should be remitted to.",
])
def test_genuine_payee_change_language_is_caught(text):
    money, change = SENTRY._scan(text)
    assert money and change


@pytest.mark.parametrize("text", [
    "Attaching September's custodial invoice, no change to the hours.",
    "Thursday deliveries are moving to 6:30am starting next week.",
    "The mediums came in short. I'm sending replacements, no charge.",
])
def test_routine_correspondence_stays_out_of_the_fleet(text):
    assert _classify(type("M", (), {"subject": "", "body": text})()) != "investigate_free"


def test_word_stems_still_match_their_inflections():
    """'update' must catch 'updated', 'migrat' must catch 'migrating' — the boundary fix must not
    have made matching so strict that real language slips through."""
    for text in ("Our details were updated last week.", "We are migrating banks."):
        _, change = SENTRY._scan(text)
        assert change, f"inflected form missed in {text!r}"
