#!/usr/bin/env python3
"""Put the demo's messages into your own inbox, so the recording can open on a real one.

    python3 scripts/send_demo_inbox.py --list
    python3 scripts/send_demo_inbox.py --send

WHAT THIS SENDS

The three scenario messages (S1 lookalike domain, S2 poisoned attachment, S3 genuine-but-thin)
and a handful of ordinary business-office mail, so the triage beat has something to be right
about. Every message is synthetic: invented vendors on RFC 2606 `.test` domains, which cannot
resolve, and 555 reserved phone numbers. No real company, person or bank appears.

Each scenario message carries an `X-Interdict-Scenario` header. That is how a message fetched
back out of the mailbox is matched to the structured change request the fleet adjudicates — see
`backend/app/platform/mailbox.py` for what that does and does not make real.

SAFETY

It will only ever send to the account it authenticated as. The recipient is not a parameter; it
is `GMAIL_ADDRESS`. These messages are business-email-compromise lures by construction, and the
one safe destination for a lure is the mailbox of the person who asked for it.

CREDENTIALS

Reads `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` from the environment or `.env`, which is
gitignored. Generate an app password at https://myaccount.google.com/apppasswords — it needs
2-Step Verification on the account. Nothing in this repository should ever contain its value.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SMTP_HOST, SMTP_PORT = "smtp.gmail.com", 465


def load_env() -> None:
    """Read .env without depending on the backend's settings machinery."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.split("#")[0].strip())


def build_messages(address: str) -> list[EmailMessage]:
    """The scenario artifacts, plus ordinary mail for the triage ratio to be about something."""
    from app.config import DEMO_EPOCH
    from app.seed.inbox import build_inbox
    from app.seed.scenarios import CATALOG, build_request

    out: list[EmailMessage] = []

    # The three that are asking to move money. Bodies come from the same fixture builder the
    # fleet reads, so what lands in the inbox is what the console will show.
    for scenario_id in ("S1", "S2", "S3"):
        scenario = CATALOG[scenario_id]
        request = build_request(scenario_id, DEMO_EPOCH, f"REQ-{scenario_id}")
        meta = request.artifact_metadata

        msg = EmailMessage()
        msg["From"] = f"Accounts Receivable <{address}>"
        msg["To"] = address
        msg["Subject"] = str(meta.get("subject") or f"Remittance update — {scenario.slug}")
        # Correlates the fetched message back to its fixture. Read by platform/mailbox.py.
        msg["X-Interdict-Scenario"] = scenario_id
        # The sender the ARTIFACT claims, kept as a header rather than forged into the envelope:
        # this script authenticates as you and sends to you, and spoofing the envelope would only
        # get the message rejected. The fleet reads the claimed addresses from the fixture.
        msg["X-Interdict-Claimed-From"] = str(meta.get("from") or "")
        msg["X-Interdict-Claimed-Reply-To"] = str(meta.get("reply_to") or "")
        msg.set_content(request.raw_artifact)

        if scenario_id == "S2":
            # The poisoned attachment. Plain text on purpose: the hidden-instruction span has to
            # survive transit intact for the guardrail beat to strike through the real thing.
            msg.add_attachment(
                request.raw_artifact.encode(),
                maintype="text", subtype="plain",
                filename="remittance-advice.txt",
            )
        out.append(msg)

    # Ordinary morning post. Without it the triage beat has nothing to be right about: a fleet
    # that flags the only three messages in an inbox of three has not demonstrated judgment.
    for message in build_inbox(DEMO_EPOCH):
        if message.scenario_id:
            continue
        msg = EmailMessage()
        msg["From"] = f"{message.sender_name} <{address}>"
        msg["To"] = address
        msg["Subject"] = message.subject
        msg["X-Interdict-Claimed-From"] = message.sender_email
        msg.set_content(message.body)
        out.append(msg)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show what would be sent, send nothing")
    parser.add_argument("--send", action="store_true", help="actually send")
    parser.add_argument("--limit", type=int, default=0, help="cap how many are sent")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds between sends; Gmail rate-limits bursts")
    args = parser.parse_args()

    load_env()
    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    if not address:
        print("GMAIL_ADDRESS is not set. Put it in .env (gitignored).", file=sys.stderr)
        return 2

    messages = build_messages(address)
    if args.limit:
        messages = messages[: args.limit]

    print(f"{len(messages)} message(s), all synthetic, all to {address}:\n")
    for m in messages:
        tag = m.get("X-Interdict-Scenario")
        print(f"  [{tag or '  '}] {m['Subject']}")

    if args.list or not args.send:
        print("\nNothing sent. Re-run with --send.")
        return 0

    if not password:
        print("\nGMAIL_APP_PASSWORD is not set. Put it in .env (gitignored).", file=sys.stderr)
        return 2

    # The recipient is not configurable, and this is the assertion that keeps it that way.
    for m in messages:
        assert m["To"] == address, "refusing to send a lure anywhere but the authenticated account"

    print(f"\nSending as {address} …")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(address, password)
        for i, m in enumerate(messages, 1):
            server.send_message(m)
            print(f"  {i}/{len(messages)}  {m['Subject']}")
            if args.delay and i < len(messages):
                time.sleep(args.delay)

    print(f"\nDone. Check {address}.")
    print("Gmail may file the scenario messages under Spam — they are BEC lures and it is doing")
    print("its job. Move them to the inbox before recording, or read from the Spam folder with")
    print("GMAIL_FOLDER='[Gmail]/Spam'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
