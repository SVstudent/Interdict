# Interdict — Recording Script

The shooting script for the unedited take. `context/DEMO_RUNBOOK.md` says *which* beats exist and
what they prove; this says **what you click, when, and what you actually say over it.**

---

## Why this cut is eight beats and not ten

Written as whole, connected sentences rather than clipped fragments, the narration runs about 40%
longer than the same content in note form. That is the right trade — fragments read as a machine
reciting a spec — but it costs beats, and the arithmetic is unforgiving:

| Cut | Words | Video | Buffer under 4:00 |
|---|---|---|---|
| **This one — eight beats** | **483** | **3:43** | **17s** |
| + the inbox beat | 529 | 4:04 | **over the cap** |
| + the inbox and the kill | 591 | 4:33 | **over the cap** |

**The inbox and the crash-resume beats are cut.** They are both good and neither fits. Shoot them
as separate 20-second clips for the Devpost page if you want them — the repo proves both with one
command each, and the README carries them.

**Beat 4 is not optional.** Beat 6 wakes a dormant case; without beat 4 injecting S3 there is
nothing dormant to wake.

---

## The pace, and the room for error

Everything below is budgeted at **140 wpm** — clear, unhurried technical delivery, not fast.

| Your pace | Spoken | Video lands at | Buffer under 4:00 |
|---|---|---|---|
| 150 wpm — brisk | 3:13 | 3:29 | 31s |
| **140 wpm — the plan** | **3:27** | **3:43** | 17s |
| 130 wpm — deliberate | 3:42 | 3:58 | 1s — drop both cuttable lines → **3:44**, 15s |
| 120 wpm — slow | 4:01 | 4:17 | **over — drop both cuttable lines → 3:59** |

**If you are running slow**, two lines come out in this order and cost you nothing structural:

1. The `Posture, probe` sentence in beat 5 — marked *(cuttable)*. 23 words, ~10 seconds.
2. The `+16s` sentence in beat 2 — marked *(cuttable)*. 14 words, ~6 seconds.

Together they are 37 words — about 16 seconds — which puts even a 120 wpm delivery back under the cap.

**And if you fumble a sentence, just say it again.** The recovery comes out of the silence, not out
of the cap — there is about 16 seconds of it spread across the take, and no beat needs you to speak
continuously.

---

## Two rules that shape every beat

**Narration runs *over* model latency, never after it.** Every beat has a measured latency floor,
and the words for it are written to outlast that floor — so you are never watching a spinner in
silence, and never talking into a screen that finished ten seconds ago.

**The longest wait does double duty.** S4 takes 41.6 seconds. Rather than stand there you click it
and go underneath — reasoning trace, audit chain, identity denial, Google Cloud console — and come
back as it lands. The wait becomes the argument: *this is long-running async execution, and it keeps
working whether anyone is watching or not.*

---

## Timeline

| # | Beat | In → Out | Length | Latency floor | Surface |
|---|---|---|---|---|---|
| 0 | Hook — the problem, and what we do about it | 0:00 → 0:26 | 0:26 | — | You / title card |
| 1 | Discovery | 0:26 → 0:49 | 0:23 | — | Registry |
| 2 | **The block** | 0:49 → 1:27 | 0:38 | **30.4s** | Console |
| 3 | The injection | 1:27 → 1:50 | 0:23 | instant on Posture | Console → Posture |
| 4 | The abstention | 1:50 → 2:11 | 0:21 | **14.4s** | Console |
| 5 | **Trace, identity, cloud** *(over S4)* | 2:11 → 2:55 | 0:44 | **41.6s, spent** | Docket → Posture → GCP → Console |
| 6 | The wake | 2:55 → 3:18 | 0:23 | ~10s | Console |
| 8 | Close | 3:18 → 3:37 | 0:19 | — | Console |

---

## What each beat is scoring

The criteria are 40 / 30 / 30. Nothing in this cut is decorative.

| Beat | Criterion | The Fortified Enterprise Fleet question it answers |
|---|---|---|
| 0 | Problem + value proposition *(required)* | — |
| 1 | **Demo & Production Readiness** | *How does an organisation discover your agents?* |
| 2 | **Innovation & Operational Utility** — the whole 40% | *Multi-agent orchestration at scale* |
| 3 | **Architectural Discipline** — guardrails | *Can they trust its data handling?* |
| 4 | **Innovation & Operational Utility** — judgment, not classification | — |
| 5 | **Architectural Discipline** + **Production Readiness** *(mandatory cloud proof)* | *Can they audit its reasoning? Observability, zero-trust identity* |
| 6 | **Architectural Discipline** — state and memory | *Long-term state persistence across sessions* |
| 8 | Value proposition, landed as a number | — |

---

## Delivering it so it doesn't sound read

The words below are the *shape* of what to say. Read them three times, then put them away and talk.

- **They are written as whole sentences on purpose.** Say them that way — let the clauses run
  together the way they do in conversation. If you find yourself hitting a full stop every four
  words, you have slipped back into reading.
- **React to the screen.** It's live. When the verdict lands, say "and there it goes." If a lane
  finishes early, mention it. The unscripted half-sentence is what proves this isn't a recording of
  a recording.
- **Contractions, always.** "It's", "doesn't", "won't", "here's". Nobody says "it does not".
- **Plain thing first, the term once.** "It actually rings the vendor" — then, later and only once,
  "out-of-band verification". Never lead with the jargon.
- **Let the silence sit.** Two seconds of nothing while four lanes light up beats filling it.
  Silence reads as confidence.

---

## Pre-flight — off camera, in order

```bash
# 1. Exactly one backend. Two uvicorns against one Vertex project contend for quota,
#    and the symptom is a beat taking eight times as long as it should.
lsof -nP -iTCP:8077 -sTCP:LISTEN -t          # zero or one PID. Kill any extras.

# 2. .env must say live. It currently says record — change it.
grep -E '^(DEMO_MODE|PLATFORM_BACKEND)' .env
#    want: DEMO_MODE=live   PLATFORM_BACKEND=local

# 3. Backend, then front end.
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8077
cd web && npm run dev                        # :5173, proxies /api to :8077

# 4. WARM-UP. Beat 2 has measured 57.8s, 67.6s and 79.4s on identical code, and a cold
#    first call is the worst of them. Burn one, then reset.
curl -s -X POST localhost:8077/api/demo/inject_scenario/S1 -m 300 -o /dev/null
curl -s -X POST localhost:8077/api/demo/reset

# 5. Confirm you are live, not replaying.
curl -s localhost:8077/healthz               # expect "mode":"live"
```

**Browser.** One window on `localhost:5173`, bookmarks bar hidden (`⌘⇧B`), Do Not Disturb on. This
machine's Chrome won't exceed a 1309px viewport and the Console clips there — zoom to **67%**
(`⌘−` ×3) and check `document.documentElement.clientWidth` reads ≥ 1900 before you record.

One more tab, already authenticated: the **Google Cloud console**, parked on the page beat 5 uses.

**Two things that fail a take on the spot:** a spinner sitting at a beat's peak (keep talking, don't
cut), and two backends.

---

# The take

---

## Beat 0 — Hook · 0:00 → 0:26 · you, or a title card

> Someone emails your accounts payable office pretending to be a vendor you've paid for years, and
> asks you to update their bank details. Everything checks out except the account number. It's a
> three-billion-dollar-a-year problem, and it hits hardest wherever nobody's job is security — so
> Interdict freezes the payment first, and makes twelve agents earn the release.

*(56 words · 24s spoken)*

---

## Beat 1 — Discovery · 0:26 → 0:49

| t | Do this |
|---|---|
| 0:26 | Click **Registry** in the nav rail — third icon down. |
| 0:29 | Catalogue: twelve agents with owner, department, data classification, version, granted/denied scope ratio. |
| 0:33 | Click the **Challenger** row. The detail pane fills on the right. |
| 0:38 | **Scroll the detail pane** to **Scope manifest** — 1 granted (`findings:read`), 6 denied. |
| 0:44 | Keep scrolling to **Version history** — v1.x → **v2.0.0**. |

⚠︎ Don't linger on the **Platform** readout in the catalogue footer. It says `local`, which is
accurate and documented — but it isn't the point of this beat.

> Before anyone can trust a fleet like this, they have to be able to find it — so here's the
> catalogue. This one's the Challenger, and it's granted exactly one permission: to read findings.
> Everything that touches money is denied, because its job is to argue, not to act.

*(48 words · 21s spoken)*

---

## Beat 2 — The block · 0:49 → 1:27

Most of the video's value is in these thirty-eight seconds.

| t | Do this / what appears |
|---|---|
| 0:49 | Click **Console** — you land on the Cases tab. |
| 0:51 | Click **Lookalike**, first brass button in the demo bar. **Then take your hands off the mouse.** |
| +2.5s | Hold fires. **$340,000** into **Held** on the ledger. Case opens and selects itself — *Northwind Student Transport LLC*. |
| +2.7s | Four lanes go live, staggered 0.6s apart. |
| +11–12s | Four findings land; chips slot onto the rail with per-lane latency. |
| +24s | The steelman lands — and is **struck through**. Four rebuttals, four defeated. |
| **+30s** | **Balance tips. BLOCK, in oxblood.** This is the shot. |

⚠︎ The demo bar never disables while busy — deliberately. The HTTP request doesn't return for ~65
seconds, but **nothing on screen changes after the verdict.** Move on the verdict, not the spinner.

> **(on the click)** Here's the email arriving — watch the money.
>
> **(+4s)** Three hundred and forty thousand has moved into hold, before any agent has formed an
> opinion.
>
> **(+9s)** Four go out in parallel, and the one to watch actually rings the vendor — on the number
> we already hold, not the one in the email.
>
> **(+16s)** *(cuttable)* They all come back against it, and the vendor confirms they never sent
> this.
>
> **(+27s)** Then the Challenger argues the opposite case and takes down each finding in turn — and
> all four attempts fail.
>
> **(+33s)** So the balance tips, and it blocks.

*(89 words · 38s spoken)*

---

## Beat 3 — The injection · 1:27 → 1:50

The guardrail event is written **before any agent parses the artifact**, so it's on Posture within a
second of the click. That's what lets a 23-second beat sit on top of a 30-second verdict.

| t | Do this / what appears |
|---|---|
| 1:27 | Click **Poisoned PDF**. |
| 1:29 | **Immediately** click **Posture**. Don't wait. |
| 1:31 | Top-left, **Guardrail screening**: **1 · Injections neutralized**, and below it the removed span reproduced **verbatim and struck through**, with technique (`hidden_text`), location and byte offset. |
| 1:36 | Let the cursor rest on the struck-through line as you say "written for the model". The screen carries the sentence; you don't have to read it out. |
| 1:46 | Click **Console**. Findings are landing; BLOCK follows. |

> Same attack, except this time there's a PDF attached, with a line hidden inside it written for the
> model rather than the person reading it. It's reproduced here exactly as we stripped it out, and
> it never reached an agent — the case still blocks, on evidence the fleet gathered itself.

*(50 words · 21s spoken)*

---

## Beat 4 — The abstention · 1:50 → 2:11

The differentiator, and a prerequisite: beat 6 has nothing to wake without it.

| t | Do this / what appears |
|---|---|
| 1:50 | Click **Thin evidence**. |
| +3s | Hold fires. New case — *Padstow Special Education Services LLC*, **$268,000**. |
| **+14.4s** | It **parks** in *Waiting on vendor callback*. Callback panel renders. **Findings visible, verdict band empty.** |

⚠︎ **Stop the take if any oxblood appears here.** If the case decides, the fixture is wrong, not the
rules — `tests/test_callback_window.py` is the regression guard.

> This third one is genuine — a real bank change after a real acquisition. The headers are clean and
> the entity checks out, but nobody answers the callback, so it simply stops without a verdict. A
> vendor not picking up the phone isn't a yes.

*(44 words · 19s spoken)*

---

## Beat 5 — Trace, identity, cloud · 2:11 → 2:55

**The pivot beat.** You click S4, leave it running, and go underneath. It takes 41.6 seconds and you
spend every one of them.

⚠︎ **Rules requirement — uncuttable.** The submission *must* show the backend running on Google
Cloud: Cloud Run dashboard, Vertex logs, Console, or a `.run.app` URL. It lands here.

| t | Do this / what appears |
|---|---|
| 2:11 | Click **Late callback**. New case — *Redgate Student Information Systems*, **$47,250**. Then leave it. |
| 2:16 | **Docket → Reasoning chain tab.** Trace tree expands with latency and tokens per node. Hover one. |
| 2:25 | **Docket → Audit record tab.** Point at `prev_record_hash`. |
| 2:31 | **Posture** → bottom-left **Identity denials** → click **Probe callback → banking read**. The denial writes itself in with its policy ID. |
| 2:39 | **Switch to the Google Cloud tab.** Decide which page before the take — see below. |
| ~2:50 | **Back to Console.** **RELEASE** in verdigris; the ledger's **Released** row increments. If it hasn't landed, stay on the cloud tab one more beat. |

**Google Cloud tab — pick one before you record:**

| Option | What you show | What it costs you |
|---|---|---|
| **Preferred — Cloud Run** | `make deploy DEMO_MODE=live`, then the Cloud Run service page with the revision serving and the `.run.app` URL visible. | One step this repo can't do for you: `gcloud auth login` as the account that owns `interdict-demo-57216`, then `gcloud config set project`. |
| **Verified fallback — Vertex logs** | Cloud Logging filtered to `aiplatform.googleapis.com`, showing the run you just recorded: `gemini-3.6-flash` and `gemini-3.7-flash`, and the `modelarmor…:sanitizeUserPrompt` 200s beside them. | Nothing. Satisfies the requirement as written, and it's real either way. |

> **(on the click)** One more, and it takes about forty seconds — which it'll spend whether I'm
> watching or not, so let me use the time to show you underneath.
>
> **(Docket, reasoning chain)** Every step is traced, so you can read what each agent concluded and
> why — and every case closes into a record carrying the hash of the one before it.
>
> **(Posture, probe)** *(cuttable)* The boundaries are enforced, not documented — that's the callback
> agent asking for the bank details it's meant to be verifying, and being refused.
>
> **(Google Cloud)** All of it running on Google Cloud — Gemini on Vertex AI, with Model Armor
> screening every attachment.
>
> **(back on Console)** And there it is — the vendor called back, confirmed, and it released.

*(107 words · 46s spoken)*

---

## Beat 6 — The wake · 2:55 → 3:18

| t | Do this / what appears |
|---|---|
| 2:55 | Click **+4 days** in the demo bar. |
| ~+10s | The clock passes the 48-hour grace window. **The dormant Padstow case wakes on its own** — no click. Its session rehydrates, prior findings reappear with session ID and age in days, and it resolves to **ESCALATE**. |
| 3:12 | Click the **Padstow row** in the left queue to put ESCALATE on screen for the cut. |

> Now, the case that refused to decide. I'm pushing the clock forward four days, and nobody touches
> it — it wakes itself up, pulls its own earlier findings back out of memory, and stops waiting. It
> escalates to a named person, which is the right answer when the evidence never arrived.

*(50 words · 21s spoken)*

---

## Beat 8 — Close · 3:18 → 3:37

| t | Do this |
|---|---|
| 3:18 | Click **Console**. Cursor rests on the right-hand **Ledger** panel — four rows with proportional meters. |

| Row | Amount | From |
|---|---|---|
| Blocked | **$485,500** | S1 $340,000 + S2 $145,500 |
| Escalated | **$268,000** | S3, after the clock |
| Released | **$47,250** | S4 |
| Held | $0 | everything resolved |

> Eight hundred thousand dollars examined in four minutes: four hundred and eighty-five thousand
> blocked, two hundred and sixty-eight thousand escalated to a person because the system knew what
> it didn't know, and forty-seven thousand released, because it earned it.

*(39 words · 17s spoken)*

---

## One thing to decide before you record

The demo runs `PLATFORM_BACKEND=local`. Under that setting **Vertex AI and Model Armor are called on
every run** — those are real, and the narration above claims only those. Firestore, Agent Runtime
and Memory Bank are implemented behind the Protocols in `backend/app/platform/` and selected by
`PLATFORM_BACKEND=geap`, but they are **not on the default path**, and the Agent Registry does not
provision on this project at all (DECISIONS D-013a).

**So do not say "Agent Registry" or "Memory Bank" on camera.** Say what is true — agent discovery,
versioning, scope manifests, a session that rehydrates with its own prior findings — and let the
README's [Google Cloud section](../README.md#what-is-genuinely-running-on-google-cloud) carry the
precise split. A submission that draws that line honestly reads far better than one implying a
managed service it never calls.

---

## The two cut beats, if you want them as separate clips

Neither fits the four-minute take. Both are about 20 seconds on their own.

**The inbox.** Gmail, scroll once, cut to Console → **Inbox** tab → **Triage**. Twenty-five real
messages read over IMAP, twenty-two dismissed, three flagged, and only three model calls spent doing
it. Needs `INBOX_SOURCE=gmail` and `python3 scripts/check_demo_inbox.py` passing first; see
`context/DEMO_INBOX.md`. **Click `Triage`, never `Open 3 cases`** — the latter runs three minutes.

**The kill.** Click **Crash**, wait 6–8 seconds so the hold has fired and a lane or two has landed,
then click **Kill run** and **Resume**. Docket → **Crash safety** shows `hold_payments` and
`begin_verification` *skipped* rather than re-run, and exactly one entry in the effects ledger.

---

## Optional — cross-district recognition

The single most impressive thing the system does, and it needs about 35 seconds. No UI button:

```bash
curl -X POST localhost:8077/api/demo/inject_cross_tenant
```

Then switch districts with the **RIVERBEND / HARBORVIEW toggle** in the navbar. Harborview shares no
vendor with Riverbend, no bank relationship, and has blocked nothing of its own — and it recognises
the same operators on first contact at score **0.85**, on tradecraft alone, from the exchange entry
Riverbend contributed.

---

## If a take goes wrong

Between takes, click **Reset** — under two seconds, and it rewinds the clock offset so a take that
ran `+4 days` doesn't start the next one four days in the future.

| Symptom | Do this |
|---|---|
| You fumble a sentence | Say it again and keep going. It comes out of the silence, not the cap. |
| Beat 2 passes 70s with no verdict | Stop. Reset. Cold start or a second backend — re-check `lsof`. |
| A lane shows `failed` | Keep going. The failure is stated with a reason and the fleet still adjudicates. Don't draw attention to it. |
| S3 decides instead of parking | Stop the take. The fixture is wrong. |
| S3 still parked after `+4 days` | Stop. The wake path is broken. |
| Anything shows a spinner at a peak | Keep talking. Never cut on a spinner. |
