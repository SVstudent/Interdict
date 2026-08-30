"""Where the morning's post comes from.

Two implementations behind one Protocol, selected by `INBOX_SOURCE`:

  `seed`   the twenty-five fixture messages in `seed/inbox.py`. The default, and what every
           test and every offline replay uses.
  `gmail`  a real mailbox, read over IMAP. The messages the fleet triages are the messages that
           actually arrived.

WHY THIS EXISTS

The demo opens on a real inbox. Without this module that opening would be a cut from a screen
recording of Gmail to a dashboard showing twenty-five fixtures that merely resemble it — two
pictures side by side implying a connection that does not exist. That is precisely the kind of
beat this project's operating rules call disqualifying. With it, the message on screen in Gmail
is the message the fleet fetched, triaged and opened a case from.

WHAT IS REAL HERE AND WHAT IS NOT

Real: the connection, the fetch, the parsing, and Sentry's triage decision about which messages
deserve an investigation. Those are the same model calls the seeded path makes.

Not real: the correlation from a triaged message to the structured `ChangeRequest` the fleet
adjudicates. A production build would extract the proposed banking details out of the message
body and its attachment; this demo reads an `X-Interdict-Scenario` header that the sender script
sets, and looks the fixture up. The extraction is the missing step, and it is missing on purpose
rather than approximated — inventing account numbers out of prose is exactly the hallucination
the rest of this system is built to refuse. `GET /api/inbox` reports `correlation: "header"` so
the surface never overstates it.

SAFETY

Read-only, by construction. The IMAP session is opened with `readonly=True`, and this module has
no code path that deletes, moves, marks, or sends anything. It is a reader.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("interdict.mailbox")

# The header the demo sender stamps so a fetched message can be matched to its fixture.
SCENARIO_HEADER = "X-Interdict-Scenario"

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


@dataclass
class FetchedMessage:
    """A message as it actually arrived, before any fixture is attached to it."""

    message_id: str
    received_at: datetime
    sender_name: str
    sender_email: str
    subject: str
    body: str
    has_attachment: bool = False
    attachment_name: str | None = None
    scenario_id: str | None = None


@runtime_checkable
class Mailbox(Protocol):
    source: str

    async def fetch(self, now: datetime) -> list[FetchedMessage]: ...


class SeededMailbox:
    """The fixture inbox. The default everywhere, and the only thing CI ever sees."""

    source = "seed"

    async def fetch(self, now: datetime) -> list[FetchedMessage]:
        from ..seed.inbox import build_inbox

        return [
            FetchedMessage(
                message_id=m.message_id,
                received_at=m.received_at,
                sender_name=m.sender_name,
                sender_email=m.sender_email,
                subject=m.subject,
                body=m.body,
                has_attachment=m.has_attachment,
                attachment_name=m.attachment_name,
                scenario_id=m.scenario_id,
            )
            for m in build_inbox(now)
        ]


class GmailMailbox:
    """A real mailbox over IMAP, read-only.

    Falls back to the seeded inbox on any failure rather than raising. A mail server that is
    slow, rate-limited or refusing an app password must not be able to take the demo down: the
    console shows `source: "seed"` and a `degraded` reason, which is honest, instead of an error
    page or — worse — an empty inbox that looks like a quiet morning.
    """

    source = "gmail"

    def __init__(self, address: str, app_password: str, folder: str = "INBOX",
                 limit: int = 25) -> None:
        if not address or not app_password:
            raise ValueError(
                "INBOX_SOURCE=gmail needs GMAIL_ADDRESS and GMAIL_APP_PASSWORD. "
                "Generate an app password at https://myaccount.google.com/apppasswords "
                "(requires 2-Step Verification). Put it in .env, which is gitignored."
            )
        self._address = address
        self._password = app_password
        self._folder = folder
        self._limit = limit
        self.degraded: str | None = None

    async def fetch(self, now: datetime) -> list[FetchedMessage]:
        import asyncio

        try:
            # imaplib is blocking and this is called from an async handler; a stalled mail
            # server would otherwise hold the event loop and stall every other surface with it.
            messages = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_blocking, now), timeout=20,
            )
            self.degraded = None
            return messages
        except Exception as exc:  # noqa: BLE001 - a mailbox must never sink the console
            self.degraded = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("gmail fetch failed, falling back to the seeded inbox: %s", self.degraded)
            return await SeededMailbox().fetch(now)

    def _fetch_blocking(self, now: datetime) -> list[FetchedMessage]:
        client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        try:
            client.login(self._address, self._password)
            # readonly: this session cannot change a flag, let alone delete anything.
            client.select(self._folder, readonly=True)
            status, data = client.search(None, "ALL")
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")

            ids = (data[0] or b"").split()
            # Newest first, and only as many as the console shows.
            ids = list(reversed(ids))[: self._limit]

            out: list[FetchedMessage] = []
            for raw_id in ids:
                status, payload = client.fetch(raw_id, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                out.append(_parse(payload[0][1], raw_id.decode(), now))
            return out
        finally:
            try:
                client.logout()
            except Exception:  # noqa: BLE001
                pass


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - a malformed header is not worth losing the message over
        return value


def _body_of(msg: Message) -> tuple[str, bool, str | None]:
    """Plain text body, whether anything is attached, and the first attachment's name."""
    has_attachment = False
    attachment_name: str | None = None
    text = ""

    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in disposition:
                has_attachment = True
                attachment_name = attachment_name or _decode(part.get_filename())
                continue
            if part.get_content_type() == "text/plain" and not text:
                text = _payload_text(part)
    else:
        text = _payload_text(msg)

    return text.strip(), has_attachment, attachment_name


def _payload_text(part: Message) -> str:
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        return raw.decode(part.get_content_charset() or "utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def _parse(raw: bytes, fallback_id: str, now: datetime) -> FetchedMessage:
    msg = email.message_from_bytes(raw)
    sender_name, sender_email = email.utils.parseaddr(_decode(msg.get("From")))
    body, has_attachment, attachment_name = _body_of(msg)

    # The injected clock, not the wall clock. A message with an unreadable Date header still has
    # to be stamped with the same time everything else in the system is reading, or advancing the
    # demo clock four days would leave the inbox behind. `test_no_wallclock.py` enforces this.
    received = now
    date_header = msg.get("Date")
    if date_header:
        try:
            parsed = email.utils.parsedate_to_datetime(date_header)
            if parsed is not None:
                received = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            pass

    scenario = (msg.get(SCENARIO_HEADER) or "").strip().upper() or None

    return FetchedMessage(
        message_id=(msg.get("Message-ID") or f"IMAP-{fallback_id}").strip("<> "),
        received_at=received,
        sender_name=sender_name or (sender_email.split("@")[0] if sender_email else "Unknown"),
        sender_email=sender_email or "unknown@unknown.test",
        subject=_decode(msg.get("Subject")) or "(no subject)",
        body=body,
        has_attachment=has_attachment,
        attachment_name=attachment_name,
        scenario_id=scenario,
    )


def build_mailbox(settings: Any) -> Mailbox:
    source = getattr(settings, "INBOX_SOURCE", "seed")
    if str(source).lower() == "gmail":
        return GmailMailbox(
            address=settings.GMAIL_ADDRESS,
            app_password=settings.GMAIL_APP_PASSWORD,
            folder=settings.GMAIL_FOLDER,
            limit=settings.GMAIL_MAX_MESSAGES,
        )
    return SeededMailbox()
