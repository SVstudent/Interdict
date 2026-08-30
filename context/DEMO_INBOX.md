# Recording beat 0.5 — the real inbox

The demo opens on the morning's post arriving in a real mailbox, cuts to the console, and the
same messages are there. This is how to set that up and what breaks.

## Why it is wired to a real mailbox rather than staged

Staging it — showing Gmail, then showing a console full of fixtures that merely resemble it —
would be two pictures side by side implying a connection that does not exist. This project's
operating rules call that disqualifying, and the honest version costs about five minutes of
setup, so there is no trade to make. The console reads the mailbox over IMAP and shows a
`live mailbox` pill only when it really did.

## Setup

**1. Turn on IMAP.** Gmail → Settings → Forwarding and POP/IMAP → Enable IMAP.

**2. Create an app password.** <https://myaccount.google.com/apppasswords>. Requires 2-Step
Verification on the account. This is a credential: it goes in `.env`, which is gitignored, and
nowhere else. Do not paste it into a chat, a commit, or this file.

**3. Configure.** Add to `.env`:

```
INBOX_SOURCE=gmail
GMAIL_ADDRESS=<the account>
GMAIL_APP_PASSWORD=<the app password>
GMAIL_FOLDER=INBOX
```

**4. Send the messages to yourself.**

```bash
python3 scripts/send_demo_inbox.py --list     # see what it would send
python3 scripts/send_demo_inbox.py --send
```

Twenty-five messages: twenty-two ordinary ones and the three that ask to move money. All
synthetic — invented vendors on `.test` domains that cannot resolve, 555 reserved numbers. The
script sends only to the account it authenticated as, and an assertion enforces it: these are
business-email-compromise lures, and the one safe destination for a lure is the mailbox of the
person who asked for it.

**5. Preflight.**

```bash
python3 scripts/check_demo_inbox.py
```

It checks the things that are invisible until they are on camera. Do not skip it.

## What will probably go wrong

**Gmail files the three lures as Spam.** It is a good classifier and they are good lures. Send
them a few hours before the take, mark them *Not spam*, and Gmail tends to remember. Failing
that, set `GMAIL_FOLDER='[Gmail]/Spam'` — but then your opening shot is a spam folder, which
undercuts "this landed in my inbox".

**The scenario headers get stripped.** `X-Interdict-Scenario` is what matches a fetched message
back to its fixture. Custom `X-` headers normally survive, but if the preflight reports them
missing the three messages will triage as ordinary mail and open no cases. Correlating on the
subject line instead is a small change to the same seam.

**The three sort to the bottom.** The console lists newest first. The sender therefore sends the
ordinary post first and the three last — S1 last of all, so it lands at row 1. If you re-send
only the scenario messages, or send them out of order, this inverts and they drop below the fold.
Re-send the whole set rather than patching it.

## On camera

1. Gmail, inbox view. The three remittance messages sit at the top among ordinary school-district
   mail. Scroll once so the ratio is visible: this is a real morning, not three suspicious emails
   in a folder by themselves.
2. Cut to the console, Console surface, **INBOX** tab. Same subjects, same order, `live mailbox`
   in the header.
3. Click **Triage**. A few seconds: 25 read, 22 dismissed **without a model call**, 3 flagged,
   each with a one-line reason.
4. Hand off to beat 1.

**Click `Triage`, not `Investigate`.** Investigate also drives each flagged message through the
full fleet — six model calls each, one case at a time to stay under the rate ceiling, about three
minutes. The scenario beats open their own cases directly and are already timed.

## If the mailbox fails during a take

Nothing breaks. The fetch degrades to the seeded inbox, the API reports `source: "seed"`, and the
`live mailbox` pill does not render. Because the sender script builds its messages from the same
fixtures the seeded inbox uses, **the subjects on screen are identical either way** — so the shot
still works. Just do not call it a live inbox when the pill is absent.
