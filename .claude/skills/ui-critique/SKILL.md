---
name: ui-critique
description: Adversarially critique an Interdict surface against the design system and recording constraints. Use after building or changing any view in web/src/views or web/src/components.
---

# UI critique

Screenshot via Playwright at **1440x900** and **390x844**, then check against
`context/PRODUCT.md`. Report findings as a list; do not silently fix and move on.

## Token discipline
- Every color resolves to a token from `context/PRODUCT.md`. **Zero raw hex** and zero
  Tailwind palette classes (`zinc-*`, `emerald-*`, `red-*`) in component code.
- **`--oxblood` appears only on `contradicts` findings and BLOCK states.** Count its occurrences
  across the whole interface: roughly four total. Any decorative use is a defect.
  *(The discarded scaffold used `red-*` 30+ times, which is what made its palette meaningless.)*
- `--amber` for held/awaiting/dormant. `--verdigris` for released/confirmed. `--brass` for
  structure and the rail — never for status.

## Type
- Newsreader for display, Inter Tight for interface, IBM Plex Mono for all data.
- All money, account fragments, case IDs, hashes, session IDs and timestamps are mono with
  `tabular-nums`. A figure that shifts width as it updates is a defect.
- The verdict line and the exposure figure are the two largest elements on screen.

## Recording constraints
- Legible at 1080p at 100% zoom. Read the screenshot at 50% scale — if a label is illegible there,
  it is illegible on video.
- **Comprehensible muted.** Cover the audio in your head: does the beat still read?
- **No layout shift on SSE arrival.** Space for incoming findings is reserved, not allocated.
- **Nothing appears only on hover.** Hover does not read on video.
- Visible keyboard focus on every interactive element.
- Responsive to 390px with no horizontal scroll.
- `prefers-reduced-motion` collapses the balance tip to a plain state change.

## Copy
- Names the thing the operator controls: "Hold released," not "State transition committed."
- Active voice on every control; an action keeps its name from button to confirmation.
- Empty states instruct. Errors say what happened and what to do.
- No raw enum values in the UI — `AWAITING_CALLBACK` renders as "Waiting on vendor callback."

## Output
For each finding: screenshot region, which rule it breaks, and the specific fix. Then re-shoot and
confirm. Finish with an explicit oxblood occurrence count.
