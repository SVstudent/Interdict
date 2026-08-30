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
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger("interdict.mailbox")

# The header the demo sender stamps so a fetched message can be matched to its fixture.
SCENARIO_HEADER = "X-Interdict-Scenario"
# The addresses the artifact claims. Written by scripts/send_demo_inbox.py; see _parse.
CLAIMED_FROM_HEADER = "X-Interdict-Claimed-From"
CLAIMED_REPLY_TO_HEADER = "X-Interdict-Claimed-Reply-To"
# Stamped on every message the demo sender puts in the mailbox, and the thing the fetch is
# scoped to. See _fetch_blocking.
DEMO_HEADER = "X-Interdict-Demo"

# How far back to look. A bare `HEADER` search makes Gmail scan the whole mailbox, and a real
# mailbox is not a test one: on a 41,796-message account that search did not return inside a
# twenty-second timeout, which would have taken the opening beat down. Narrowing by internal date
# first uses Gmail's date index — the same search resolves in under a second — and the demo's
# messages are sent shortly before recording, so a few days is generous.
DEMO_LOOKBACK_DAYS = 7

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
                asyncio.to_thread(self._fetch_blocking, now), timeout=45,
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

            # Scoped to the messages this repository's own sender put there, NOT to the whole
            # mailbox. `ALL` fetched the presenter's genuine private mail — which would then be
            # rendered on camera, shipped in the API response, and stored in a system whose
            # standing claim is that every address in it is synthetic. Reading a real mailbox
            # does not require reading someone's real correspondence.
            #
            # It also makes the newest-N window mean "the newest N demo messages", so the two
            # fetches this beat performs — one on page load, one on the click — agree even if
            # ordinary mail arrives between them. They are correlated by message id in the panel,
            # and a shifted window silently renders rows with no verdict.
            since = (now - timedelta(days=DEMO_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
            status, data = client.search(None, "SINCE", since, "HEADER", DEMO_HEADER, "1")
            if status != "OK" or not (data and data[0]):
                # A mailbox populated some other way still works; the failure mode is the old
                # one rather than an empty pane. The preflight reports which path was taken.
                status, data = client.search(None, "ALL")
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")

            ids = (data[0] or b"").split()
            # Take the tail of the mailbox — the most recently arrived — then sort by the
            # message's own Date below. IMAP sequence order is arrival order, which is close to
            # but not the same as Date order, and the console renders whatever order this
            # returns: `InboxPanel` does not sort.
            ids = list(reversed(ids))[: self._limit]

            # ONE fetch for the whole set, not one per message.
            #
            # Twenty-five sequential round trips to Gmail took nine to eleven seconds, and the
            # inbox pane has no loading state that survives that: the beat opened on the words
            # "Inbox empty" for ten seconds. Batched, the same fetch is a single round trip.
            #
            # Falls back to per-message on any parsing trouble, because a batched FETCH response
            # is a flat list of alternating tuples and closing bytes rather than the tidy shape
            # the single-message call returns, and one odd server reply should cost latency, not
            # the whole inbox.
            out: list[FetchedMessage] = []
            try:
                status, payload = client.fetch(b",".join(ids), "(RFC822)")
                if status == "OK" and payload:
                    for part in payload:
                        if isinstance(part, tuple) and len(part) >= 2 and part[1]:
                            out.append(_parse(part[1], "batch", now))
            except Exception:  # noqa: BLE001 - fall through to the reliable path
                out = []

            if len(out) != len(ids):
                out = []
                for raw_id in ids:
                    status, payload = client.fetch(raw_id, "(RFC822)")
                    if status != "OK" or not payload or not isinstance(payload[0], tuple):
                        continue
                    out.append(_parse(payload[0][1], raw_id.decode(), now))

            # Newest first, exactly like the seeded inbox (`seed/inbox.py` sorts the same way).
            #
            # This sort is NOT what puts the three attack messages at the top — the sender's
            # backdated `Date` headers do that, and before those existed reordering the send did.
            # What the sort buys is independence from IMAP sequence numbering and from send
            # jitter, so a partial re-send or a mailbox that renumbers cannot reorder the pane.
            out.sort(key=lambda m: m.received_at, reverse=True)
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

    # The address the ARTIFACT claims, not the envelope it arrived in.
    #
    # Two reasons, and the second is the important one. First, the demo's messages are sent by
    # the presenter to themselves, so the envelope `From` is their own personal address — which
    # would put a real email address into a system whose standing claim is that every address in
    # it is synthetic. Second, and generally: in a business-email-compromise the envelope sender
    # is frequently a genuinely compromised mailbox, and the interesting address is the one the
    # message asks you to reply to. Reading the claimed header is closer to what the analysis is
    # actually about, not merely convenient for the recording.
    claimed = _decode(msg.get(CLAIMED_FROM_HEADER))
    if claimed:
        claimed_name, claimed_email = email.utils.parseaddr(claimed)
        sender_email = claimed_email or claimed
        sender_name = sender_name or claimed_name
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
