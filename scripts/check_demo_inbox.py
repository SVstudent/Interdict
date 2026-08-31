#!/usr/bin/env python3
"""Preflight the mailbox before recording. Run this instead of finding out on camera.

    python3 scripts/check_demo_inbox.py

Checks, in the order they fail:

  1. Credentials are configured at all.
  2. Gmail's IMAP endpoint is reachable.
  3. The app password authenticates, and the folder exists.
  4. The demo's messages are actually in that folder.
  5. The `X-Interdict-Scenario` headers survived Gmail — this is the one that decides whether a
     fetched message can be matched back to its fixture, and it is the least predictable, because
     custom headers usually survive but nobody should bet a take on "usually".
  6. The three attack messages sort to the TOP of the list, which is the whole point of the cut
     from Gmail to the console. If they are at the bottom they are below the fold and off camera.

Exit code is the number of failed checks, so it can gate a rehearsal script.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

EXPECTED_SCENARIOS = {"S1", "S2", "S3"}


def main() -> int:
    from send_demo_inbox import load_env  # same .env reader, no duplicate parsing

    load_env()

    import asyncio
    import os

    from app.config import DEMO_EPOCH, Settings
    from app.platform.mailbox import IMAP_HOST, IMAP_PORT, GmailMailbox

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> bool:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(label)
        return ok

    settings = Settings()
    address = settings.GMAIL_ADDRESS or os.environ.get("GMAIL_ADDRESS", "")
    password = settings.GMAIL_APP_PASSWORD or os.environ.get("GMAIL_APP_PASSWORD", "")

    print("Mailbox preflight\n")
    if not check("credentials are configured", bool(address and password),
                 "set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env" if not (address and password)
                 else f"{address}"):
        return len(failures)

    check("INBOX_SOURCE is gmail", settings.INBOX_SOURCE.lower() == "gmail",
          f"currently {settings.INBOX_SOURCE!r}; the console will show fixtures "
          "until this is 'gmail'")

    try:
        socket.create_connection((IMAP_HOST, IMAP_PORT), timeout=10).close()
        check(f"{IMAP_HOST}:{IMAP_PORT} is reachable", True)
    except OSError as exc:
        check(f"{IMAP_HOST}:{IMAP_PORT} is reachable", False, str(exc))
        return len(failures)

    mailbox = GmailMailbox(address, password, settings.GMAIL_FOLDER, settings.GMAIL_MAX_MESSAGES)
    messages = asyncio.run(mailbox.fetch(DEMO_EPOCH))

    if not check("the mailbox authenticated and fetched", mailbox.degraded is None,
                 mailbox.degraded or f"folder {settings.GMAIL_FOLDER!r}"):
        print("\n  The console will still work — it degrades to the seeded inbox and says so —")
        print("  but it will not be reading your real mail.")
        return len(failures)

    check("messages were returned", len(messages) > 0,
          f"{len(messages)} in {settings.GMAIL_FOLDER!r}")

    found = {m.scenario_id for m in messages if m.scenario_id}
    check("the scenario headers survived Gmail", found == EXPECTED_SCENARIOS,
          f"found {sorted(found) or 'none'}, expected {sorted(EXPECTED_SCENARIOS)}"
          + ("" if found else " — without these the fleet cannot match a message to its fixture"))

    top = [m.scenario_id for m in messages[:5]]
    check("an attack message is at the top of the list", bool(top and top[0]),
          f"first five: {top} — if these are all None the three are below the fold on camera")

    claimed = [m for m in messages if m.sender_email and address.lower() in m.sender_email.lower()]
    check("your own address is not showing as a sender", not claimed,
          f"{len(claimed)} message(s) would render your real address"
          if claimed else "claimed-sender headers are being read")

    print(f"\n{'READY' if not failures else str(len(failures)) + ' CHECK(S) FAILED'}")
    if not failures:
        print(f"  {len(messages)} messages, newest first, scenarios at the top.")
        print("  Start the backend and confirm GET /api/inbox reports source: gmail.")
    return len(failures)


if __name__ == "__main__":
    raise SystemExit(main())
