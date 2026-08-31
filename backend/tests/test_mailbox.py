"""The inbox source, and the honesty properties that make a real mailbox safe to demo on.

The demo opens on a real Gmail inbox and cuts to the console. That cut is only truthful if the
console is showing the messages that were actually fetched — so the interesting tests here are
not "does IMAP work" (it does, or it degrades) but "can the surface ever claim more than it did".
"""
from __future__ import annotations

from email.message import EmailMessage

import pytest

from app.config import DEMO_EPOCH, Settings
from app.platform.mailbox import (
    SCENARIO_HEADER,
    FetchedMessage,
    GmailMailbox,
    SeededMailbox,
    _parse,
    build_mailbox,
)

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
    """Nothing about a credential-free run may depend on a mailbox being reachable.

    Asserted against the field's declared default rather than a constructed `Settings()`, because
    `Settings` reads the developer's `.env` — so once someone sets INBOX_SOURCE=gmail locally to
    rehearse the demo, a test written the obvious way starts failing on their machine and passing
    in CI. The suite must not depend on whose laptop it runs on.
    """
    assert Settings.model_fields["INBOX_SOURCE"].default == "seed"
    assert isinstance(build_mailbox(Settings(INBOX_SOURCE="seed")), SeededMailbox)


def test_gmail_requires_credentials_rather_than_failing_at_fetch_time():
    """A misconfiguration should be loud at construction, not a silently empty morning."""
    with pytest.raises(ValueError) as exc:
        # Explicitly blank, not merely unset: a developer rehearsing the demo has real values in
        # their .env and Settings would otherwise pick them up.
        build_mailbox(Settings(INBOX_SOURCE="gmail", GMAIL_ADDRESS="", GMAIL_APP_PASSWORD=""))
    assert "GMAIL_APP_PASSWORD" in str(exc.value)


def test_an_unknown_source_falls_back_to_seed():
    assert isinstance(build_mailbox(Settings(INBOX_SOURCE="carrier-pigeon")), SeededMailbox)  # noqa: E501


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


# --- the opening beat -------------------------------------------------------------------------


async def test_triage_only_opens_no_cases():
    """Beat 0.5 reads the morning and stops. Driving the flagged cases is a different beat.

    The full path is six model calls per flagged message, run one case at a time to stay under
    the provider's rate ceiling — around three minutes, against a four-minute video. Triage on its
    own answers in about ten seconds, and it is the half that demonstrates judgment.
    """
    from app.api.inbox import process_inbox
    from app.state import build_state

    state = build_state(Settings(DEMO_MODE="replay", PLATFORM_BACKEND="local"))
    state.clock = type("C", (), {"now": staticmethod(lambda: DEMO_EPOCH)})()

    body = await process_inbox(triage_only=True, state=state)

    assert body["triage_only"] is True
    assert body["messages_read"] >= 20
    assert body["cases_opened"] == [], "triage-only drove a case; the opening beat would run long"
    assert body["triage"]["investigate"] >= 1


async def test_most_of_the_morning_is_settled_without_a_model_call():
    """The affordability claim, asserted rather than narrated.

    A fleet that spends a model call on every delivery-window notice is not one a school district
    business office can run. This is the ratio the README argues from.
    """
    from app.api.inbox import process_inbox
    from app.state import build_state

    state = build_state(Settings(DEMO_MODE="replay", PLATFORM_BACKEND="local"))
    state.clock = type("C", (), {"now": staticmethod(lambda: DEMO_EPOCH)})()

    triage = (await process_inbox(triage_only=True, state=state))["triage"]
    total = triage["investigate"] + triage["ignored"]

    assert triage["settled_without_a_model_call"] >= total * 0.8, (
        f"only {triage['settled_without_a_model_call']}/{total} messages were settled for free; "
        "the deterministic screen has stopped carrying the inbox"
    )


async def test_a_real_mailbox_lists_in_the_same_order_as_the_seeded_one():
    """THE test for this feature. The demo cuts from Gmail to the console; the two must agree.

    Builds the exact messages the sender script would send, parses them back through the same
    `_parse` the live path uses, shuffles to prove the sort does not depend on arrival order, and
    compares element for element against the seeded pane. Covers row order, the subjects, the S2
    paperclip, and the scenario headers surviving a round trip — the four things that drifted.

    No network: this is the seam where the two paths meet, and it is checkable offline.
    """
    import random
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from send_demo_inbox import build_messages

    built = build_messages("presenter@example.test")
    parsed = [_parse(m.as_bytes(), str(i), NOW) for i, m in enumerate(built)]
    random.shuffle(parsed)
    parsed.sort(key=lambda m: m.received_at, reverse=True)

    seeded = await SeededMailbox().fetch(NOW)

    def shape(messages):
        return [(m.subject, m.has_attachment, m.scenario_id) for m in messages]

    assert shape(parsed) == shape(seeded), (
        "the real-mailbox order or content diverged from the seeded pane; the demo's cut from "
        "Gmail to the console would show two different lists"
    )


async def test_the_three_attacks_are_reachable_without_scrolling():
    """A message the camera never sees is a message the demo did not show.

    The inbox pane renders about ten rows once a triage run gives every row a reason line.
    """
    messages = await SeededMailbox().fetch(NOW)
    rows = {m.scenario_id: i for i, m in enumerate(messages) if m.scenario_id}
    assert rows, "no scenario messages in the inbox at all"
    assert max(rows.values()) < 10, f"a scenario sits below the fold: {rows}"


async def test_the_attacks_are_still_interleaved():
    """Three suspicious messages sitting together is a fixture arranging itself to be found."""
    messages = await SeededMailbox().fetch(NOW)
    positions = sorted(i for i, m in enumerate(messages) if m.scenario_id)
    gaps = [b - a for a, b in zip(positions, positions[1:], strict=False)]
    assert all(g > 1 for g in gaps), (
        f"scenario messages are adjacent at rows {positions}; the fleet should be picking them "
        "out of a real morning, not off the top of a pile"
    )


def test_the_presenters_own_address_never_reaches_the_api():
    """The envelope is the presenter's own account; the claimed header is what should render."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from send_demo_inbox import build_messages

    address = "presenter@example.test"
    for built in build_messages(address):
        parsed = _parse(built.as_bytes(), "1", NOW)
        assert address not in parsed.sender_email, (
            f"the presenter's real address rendered as the sender of {parsed.subject!r}"
        )


def test_the_envelope_is_used_when_nothing_is_claimed():
    """The claimed header is a preference, not a requirement — ordinary mail still parses."""
    assert _parse(_raw(sender="Real Sender <real@vendor.test>"), "1", NOW).sender_email \
        == "real@vendor.test"


def test_the_fetch_is_scoped_to_the_demos_own_messages():
    """`ALL` would fetch the presenter's genuine private mail and render it on camera."""
    import inspect

    from app.platform import mailbox as module

    source = inspect.getsource(module._fetch_blocking) if hasattr(module, "_fetch_blocking") \
        else inspect.getsource(module.GmailMailbox._fetch_blocking)
    assert 'DEMO_HEADER' in source and '"HEADER"' in source, (
        "the IMAP search is not scoped to the demo header; it would read real correspondence"
    )


def test_dotenv_is_read_regardless_of_working_directory():
    """`.env` must resolve against the repo, not the process CWD.

    The documented way to start the service is `cd backend && uvicorn app.main:app`, and with a
    relative `env_file=".env"` that means `backend/.env` — which does not exist, so the file was
    silently never read. It looked fine for months because the run commands passed the same values
    as environment variables; the first setting that lived only in `.env` was the one that caught
    it, by reporting the default while `.env` said otherwise.
    """
    from pathlib import Path

    env_file = Settings.model_config.get("env_file")
    assert env_file is not None, "Settings no longer reads a .env file at all"
    assert Path(env_file).is_absolute(), (
        f"env_file is {env_file!r}, which resolves against the process CWD; starting the service "
        "from backend/ would silently ignore .env"
    )
