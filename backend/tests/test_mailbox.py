"""The inbox source, and the honesty properties that make a real mailbox safe to demo on.

The demo opens on a real Gmail inbox and cuts to the console. That cut is only truthful if the
console is showing the messages that were actually fetched — so the interesting tests here are
not "does IMAP work" (it does, or it degrades) but "can the surface ever claim more than it did".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest

from app.config import DEMO_EPOCH, Settings
from app.platform.mailbox import (SCENARIO_HEADER, FetchedMessage, GmailMailbox,
                                  SeededMailbox, _parse, build_mailbox)

NOW = DEMO_EPOCH


def _raw(subject="Hello", body="Body text", scenario=None, sender="Ada Lovelace <ada@vendor.test>",
         date=None, attachment=None) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "office@district.test"
    msg["Subject"] = subject
    if scenario:
        msg[SCENARIO_HEADER] = scenario
    if date:
        msg["Date"] = date
    msg.set_content(body)
    if attachment:
        msg.add_attachment(b"payload", maintype="text", subtype="plain", filename=attachment)
    return msg.as_bytes()


# --- selection ------------------------------------------------------------------------------


def test_the_default_source_is_the_seeded_inbox():
    """Nothing about a credential-free run may depend on a mailbox being reachable."""
    assert isinstance(build_mailbox(Settings()), SeededMailbox)


def test_gmail_requires_credentials_rather_than_failing_at_fetch_time():
    """A misconfiguration should be loud at construction, not a silently empty morning."""
    with pytest.raises(ValueError) as exc:
        build_mailbox(Settings(INBOX_SOURCE="gmail"))
    assert "GMAIL_APP_PASSWORD" in str(exc.value)


def test_an_unknown_source_falls_back_to_seed():
    assert isinstance(build_mailbox(Settings(INBOX_SOURCE="carrier-pigeon")), SeededMailbox)


async def test_the_seeded_inbox_is_mostly_ordinary_mail():
    """The triage beat is only a demonstration of judgment if most of the post is innocent."""
    messages = await SeededMailbox().fetch(NOW)
    flagged = [m for m in messages if m.scenario_id]
    assert len(messages) >= 20
    assert 1 <= len(flagged) <= 5, (
        f"{len(flagged)} of {len(messages)} messages are scenarios; a fleet that flags most of "
        "the inbox has not shown it can leave mail alone"
    )


# --- parsing --------------------------------------------------------------------------------


def test_a_message_keeps_its_own_sender_and_subject():
    m = _parse(_raw(subject="Invoice INV-4471", sender="AP <ap@northwind.test>"), "1", NOW)
    assert m.subject == "Invoice INV-4471"
    assert m.sender_email == "ap@northwind.test"
    assert m.sender_name == "AP"
    assert "Body text" in m.body


def test_the_scenario_header_is_what_correlates_a_message_to_its_fixture():
    assert _parse(_raw(scenario="S1"), "1", NOW).scenario_id == "S1"
    assert _parse(_raw(), "1", NOW).scenario_id is None


def test_the_scenario_header_is_case_insensitive():
    assert _parse(_raw(scenario="s2"), "1", NOW).scenario_id == "S2"


def test_an_attachment_is_detected_and_named():
    m = _parse(_raw(attachment="remittance-advice.txt"), "1", NOW)
    assert m.has_attachment is True
    assert m.attachment_name == "remittance-advice.txt"


def test_a_message_with_no_date_is_stamped_from_the_injected_clock():
    """Not the wall clock. Advancing the demo clock must not leave the inbox behind."""
    assert _parse(_raw(), "1", NOW).received_at == NOW


def test_a_real_date_header_is_preserved():
    m = _parse(_raw(date="Tue, 25 Aug 2026 09:14:00 +0000"), "1", NOW)
    assert m.received_at.year == 2026 and m.received_at.month == 8 and m.received_at.day == 25


def test_an_unparseable_date_falls_back_to_the_clock_rather_than_raising():
    assert _parse(_raw(date="not a date at all"), "1", NOW).received_at == NOW


def test_an_encoded_subject_is_decoded():
    raw = _raw(subject="Remittance")
    raw = raw.replace(b"Subject: Remittance", b"Subject: =?utf-8?q?Remittance_update?=")
    assert _parse(raw, "1", NOW).subject == "Remittance update"


def test_a_message_with_no_sender_still_parses():
    """A malformed message must not be able to take the inbox down."""
    m = _parse(b"Subject: Orphan\r\n\r\nbody", "7", NOW)
    assert m.subject == "Orphan"
    assert m.sender_email.endswith(".test")


# --- degradation ------------------------------------------------------------------------------


async def test_an_unreachable_mailbox_degrades_to_seed_and_says_so():
    """A mail server having a bad day must not be able to end the demo.

    The important half is `degraded` being set: the API turns that into `source: "seed"` on the
    response, so the console reports fixtures rather than presenting them as a real inbox.
    """
    mailbox = GmailMailbox("nobody@example.test", "not-a-real-password")
    mailbox._fetch_blocking = lambda now: (_ for _ in ()).throw(OSError("connection refused"))

    messages = await mailbox.fetch(NOW)

    assert messages, "degrading to the seeded inbox should still produce the morning's post"
    assert mailbox.degraded is not None
    assert "connection refused" in mailbox.degraded


async def test_a_successful_fetch_clears_a_previous_degradation():
    mailbox = GmailMailbox("nobody@example.test", "pw")
    mailbox.degraded = "OSError: earlier failure"
    mailbox._fetch_blocking = lambda now: [
        FetchedMessage(
            message_id="M1", received_at=now, sender_name="AP",
            sender_email="ap@vendor.test", subject="s", body="b",
        )
    ]

    await mailbox.fetch(NOW)
    assert mailbox.degraded is None


def test_the_mailbox_module_has_no_way_to_delete_or_send():
    """Read-only by construction, asserted so a future edit has to argue with a test."""
    import inspect

    from app.platform import mailbox as module

    source = inspect.getsource(module)
    for forbidden in ("STORE", "expunge", "\\Deleted", "smtplib", "sendmail", "send_message"):
        assert forbidden not in source, (
            f"mailbox.py mentions {forbidden!r}; this module reads a mailbox and does nothing else"
        )
    assert "readonly=True" in source, "the IMAP session must be opened read-only"
