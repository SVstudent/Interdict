# PRODUCT — Interdict

## The problem
A vendor emails accounts payable to update remittance bank details. The email is clean — no link,
no payload, correct signature block, references a genuinely open invoice. AP updates the vendor
master. The next payment run wires several hundred thousand dollars to a mule account.

- BEC drove roughly **$3.05B in reported US losses in 2025** — second-largest loss category, FBI IC3.
- Average per-complaint loss exceeds **$122,000**.
- **86%** of funds move by wire or ACH — fast, usually unrecoverable.
- **~76%** of US organizations saw attempted or actual payments fraud; **74%** were hit by BEC.
- Only about **17%** use AI to defend. Attackers automated. Defenders did not.

> Figures are cited in the README and beat 0. Each must carry its source. Do not round or restate
> them differently anywhere else in the repo — a judge who spots drift discounts all of them.

## The regulatory hook
Nacha's Phase 2 fraud-monitoring rule took effect June 19/22, 2026. Every non-consumer ACH
originator must run risk-based processes to identify entries initiated under false pretenses —
payments authorized through deception — and document that process with annual review.
**Interdict's audit record is that documentation.** This is why the hash-chained artifact matters:
it is not decoration, it is the deliverable a compliance officer keeps.

## Principles, in priority order
1. **Never trust the inbound artifact.** Contact details come from the system of record, never the
   request. A request supplying its own phone number alongside a banking change is a fraud signal,
   not a convenience.
2. **Abstention is a first-class outcome.** ESCALATE with stated reasoning is a success state.
   A fleet that always decides is guessing.
3. **Every conclusion cites evidence.** Structurally enforced, not politely requested.
4. **Idempotency is a safety property.** A payment is never released twice, regardless of crashes.

## The user — the Unlikely Hero
**The business manager of a mid-size public school district.**

One person, or a small business office, signing seven-figure payment runs: the bus contractor, food
services, custodial supply, athletics, textbooks, a roofing project. They have no security team, no
fraud analyst, and no budget for enterprise payment controls. The money is public.

This is deliberately not a corporate AP controller. The people who lose most to this attack are the
ones who can least afford to defend against it, and school districts are hit by exactly this
pattern. Interdict is institutional-grade agent capability pointed at someone who could never staff
an institution's security function.

They are not a security analyst. They control holds and releases. Copy names things by what they
control: "Hold released," not "State transition committed." "Waiting on vendor callback," not
"AWAITING_CALLBACK."

---

# DESIGN SYSTEM

## Direction
The subject is a control point where money is about to leave, and the vernacular is judicial:
cases, evidence, findings, a challenger, an adjudicator, a verdict. The language is
**the docket and the ledger** — institutional, precise, documentary. Not cyber-security. Not fintech.

**Out of bounds** — every AI-designed dashboard in this category converges on these two:
1. Near-black with a single acid-green or vermilion accent. *(The `untitled/` scaffold landed
   exactly here: `bg-zinc-950` + `emerald-400`. See DECISIONS D-001 F12.)*
2. Warm cream with a high-contrast serif and terracotta.

If the palette drifts toward either, choose again.

## Tokens
```css
--ground:         #12151A;  /* graphite blue-black, the field */
--surface:        #1A1F26;
--surface-raised: #232932;
--rule:           #2E3641;  /* hairlines only, never border-heavy cards */

--ink:            #E8E4DC;  /* warm off-white, parchment cast, not #FFF */
--ink-dim:        #8A9099;

--brass:          #B8934A;  /* structure: labels, active state, the rail */
--oxblood:        #A03A32;  /* RESERVED: contradicts + BLOCK. Nowhere else. */
--verdigris:      #4A8F7B;  /* released, confirmed */
--amber:          #C9873A;  /* held, awaiting, dormant */
```
Brass, verdigris and oxblood is a ledger-book and bank-fittings palette — aged metal, not neon.
The discipline that makes it work: **oxblood appears roughly four times in the entire interface.**
When it does, it means money is being stopped. `ui-critique` asserts this.

## Type
- **Display** — Newsreader. Editorial, slightly bookish; documentary rather than luxury.
  Case titles, section heads, the verdict.
- **Interface** — Inter Tight. Labels, body, controls.
- **Data** — IBM Plex Mono, `font-variant-numeric: tabular-nums`. All money, account fragments,
  case IDs, hashes, session IDs, timestamps.

The verdict line and the exposure figure are the two largest things on screen. Everything else
steps down sharply.

## Motion
One orchestrated moment, not scattered effects: findings slotting into the rail, the Challenger's
block landing, the tip. Everything else instant. `prefers-reduced-motion` collapses the tip to a
state change.

## Recording constraints — requirements, not preferences
- Legible at 1080p, browser at 100% zoom, on a laptop screen.
- Comprehensible **muted** — every beat readable from the screen alone.
- No layout shift when SSE events land. Reserve the space.
- Nothing appears only on hover; hover states don't read on video.
- Keyboard focus visible; responsive to 390px.
