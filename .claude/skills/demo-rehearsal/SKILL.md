---
name: demo-rehearsal
description: Run a full demo rehearsal — reset state, execute every beat through the demo control plane, screenshot each peak moment, and assert per-beat wall-clock against budget. Use before any recording and at every phase gate from Phase 4 on.
---

# Demo rehearsal

Backs `make rehearse`. Fails loudly. A rehearsal that "mostly worked" is a failed rehearsal.

## Procedure
1. `POST /api/demo/reset` — assert it returns in **under 2 seconds**.
2. For each beat 1-8 in `context/DEMO_RUNBOOK.md`:
   - Start a wall-clock timer.
   - Execute the beat's command from the runbook command table.
   - Wait for the beat's terminal SSE event (not a fixed sleep — a fixed sleep hides regressions).
   - Screenshot the peak moment via Playwright at **1440x900**.
   - Stop the timer; record elapsed.
3. `GET /api/demo/timings` and cross-check against the client-side measurements. A divergence means
   the server finished before the UI rendered — that is a real bug for the video, not a rounding issue.
4. Write `artifacts/rehearsal-<timestamp>/` with all screenshots plus `timings.json`.

## Assertions — any failure fails the rehearsal
- Every beat is at or under its runbook budget. Beat 2 <= 70s in `live` mode.
- Total across beats 0-8 <= 4:00.
- **No screenshot contains a spinner or a loading skeleton.**
- **No screenshot shows an empty state** where content is expected.
- **No layout shift**: capture immediately before and after each SSE burst; bounding boxes of
  persistent elements must be identical.
- Beat 2's screenshot shows all four lanes as having run **concurrently** (overlapping start/end
  timestamps in the trace), not sequentially.
- Beat 6's checkpoint list shows **no repeated step**, and `effects/` holds exactly one entry
  for the release/block action.
- Beat 3's Posture screenshot contains the **literal** injected sentence, struck through.

## Reporting
Print a table: beat, budget, actual, delta, pass/fail. Then the screenshot paths.
If any beat is over budget, do not "note it" — state which beat is cut or what is being tightened,
per the runbook's cut order (beat 4 first; never beat 1 or 7).
