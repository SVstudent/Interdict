# UI_SPEC — Interdict Design System

**Status:** authoritative. Every surface (Console, Docket, Registry, Posture) is implemented from
this document. Where this document and a component disagree, this document wins and the component
is wrong.

**Implementation:** `web/src/styles/tokens.css` (tokens), `web/src/components/primitives.tsx`
(inventory), `web/src/components/DataGrid.tsx` (tabular data), `web/src/components/AppShell.tsx`
(global chrome). No component may hard-code a hex value that is not in this document.

**Provenance.** The geometry is Palantir Blueprint v6 (4px unit, 30px control, 50px chrome,
box-shadow elevation, 20/24/30/40 control ladder). The information architecture and the stage
indicator are Salesforce Lightning conventions (label-above-value, two-row record header, path
state machine, `aria-sort` discipline). The density and no-shift rules are ops-console convention
(ISA-101 chroma budget, tabular figures, fixed table layout). **We match structure and density.
We never use either vendor's name, wordmark, or brand blue.** The palette, the type, and the
oxblood discipline are ours and are not negotiable.

---

## 0. Non-negotiables

| # | Rule | Test |
|---|------|------|
| N1 | `--oxblood` appears ONLY on `contradicts` findings and on `BLOCK`/`blocked`. | grep the tree; ~4 live uses |
| N2 | `--brass` is structure only — labels, rules, active nav, focus, the rail. Never status. | no `STATE_TONE`/`VERDICT_TONE`/`OUTCOME_TONE` entry is `brass` for a terminal state |
| N3 | Nothing appears only on hover. Hover may only *emphasise* what is already visible. | mute the video; every beat still readable |
| N4 | No layout shift when SSE events land. Space is reserved, never conditionally rendered. | CLS < 0.1 over the 4-minute run |
| N5 | The document never scrolls. Panes scroll independently. | `body { overflow: hidden }` |
| N6 | No trademark, no brand blue (`#0176d3`, `#1b96ff`, `#2d72d2`), no vendor name in the UI. | grep |
| N7 | No decorative gradients, no glassmorphism, no emoji-as-UI, no radius ≥ 8px on a data container. The one sanctioned `linear-gradient` is `.struck`, which draws a 1px strike-through line. | grep for `linear-gradient`, `backdrop-filter`, `rounded-lg` |
| N8 | One icon family (lucide-react), monochrome, `currentColor`, stroke 1.75. | grep imports |

---

## 1. Grid and spacing

Base unit **4px** (Blueprint `$pt-spacing`). Tailwind's `--spacing` is `0.25rem`, so `p-2` = 8px.

**The permitted ramp — no other value may appear in a layout declaration:**

| Token | px | Named | Use |
|---|---|---|---|
| `--spacing-hair` | 2 | xxx-small | icon nudge, pill vertical padding |
| `--spacing-xxs` | 4 | xx-small | tight gap, menu padding |
| `--spacing-xs` | 6 | — | pill horizontal padding |
| `--spacing-sm` | 8 | x-small | control padding, child gap, cell padding |
| `--spacing-md` | 12 | small | pane inner padding, card header |
| `--spacing-lg` | 16 | medium | card padding (compact), dialog body |
| `--spacing-xl` | 20 | — | card padding (standard, Blueprint) |
| `--spacing-2xl` | 24 | large | section gap, table edge buffer |
| `--spacing-3xl` | 32 | x-large | detail-block separation |
| `--spacing-4xl` | 48 | xx-large | major section break |

**Banned:** 5, 10, 14, 18, 30, and anything ≥ 56 in a layout. `20` is permitted **only** as
card/section padding (Blueprint's own use); it may never set a row rhythm or a control height.

## 2. Control heights — the ladder

Blueprint's ladder exactly. Nothing in this app is 32px or 36px tall.

| Token | px | What |
|---|---|---|
| `--h-micro` | 18 | status pill |
| `--h-xs` | 20 | micro chip, kbd chip, dense button, tag |
| `--h-sm` | 24 | small button, inline input action, filter token |
| `--h-md` | 30 | **standard** — button, input, tab, tree node, menu row, table column header, pane header |
| `--h-lg` | 40 | large button, command-palette input |
| `--h-navbar` | 50 | global navbar (Blueprint `$pt-navbar-height`, SLDS global header) |

Chrome bands:

| Band | px |
|---|---|
| Synthetic-data banner | 24 |
| Global navbar | 50 |
| Nav rail width | 56 |
| Pane header | 30 |
| Status bar | 26 |
| Table column header | 30 |

Total fixed chrome, vertical: 24 + 50 + 26 = **100px**. At a 900px content box that leaves 800px
of pane, i.e. **28 rows** at 28px inside a pane with a 30px header. Hard floor: 20 visible rows.

## 3. Table density

| Density | Row px | Font px | Line-height | Use |
|---|---|---|---|---|
| `dense` | 24 | 11 | 1.35 | audit chain, checkpoints, span lists |
| `compact` (**default**) | 28 | 11 | 1.40 | every queue and catalog |
| `comfortable` | 32 | 12 | 1.40 | two-value cells only |

- Column header: **30px**, 10px, weight 600, `letter-spacing 0.09em`, uppercase,
  `--color-ink-faint`, sticky (`top:0; z-index:2`), background `--color-surface` (never
  transparent), 1px bottom rule in `--color-rule`.
  *Deviation from Blueprint*, whose `th` carries no chrome: our header must survive video
  compression while scrolling, so it gets an opaque fill and a rule.
- Cell padding: **0 8px** horizontal, **0** vertical. Row height comes from an explicit `height`,
  never from padding. First and last cell get 12px (a reduced SLDS "cell buffer" — 24px is too
  airy at our width).
- `table-layout: fixed`, every column width declared. Non-negotiable: auto layout means any data
  update can reflow every column.
- Numeric columns: `text-align: right`, `font-variant-numeric: tabular-nums`, mono face,
  min-width sized in `ch` for the largest expected value.
- Zebra striping: **none**. Separation is a 1px `--color-rule-muted` bottom border.
- Row hover: background `--color-raised`. Nothing else — no transform, no shadow, no border.
- Row selected: background `--color-overlay` + `inset 2px 0 0 --color-brass`. The 2px accent is
  drawn *inside* the row, so selection never changes row height.
- Sort: `aria-sort` is `"ascending" | "descending" | "none"` and is **present on every sortable
  column**, including unsorted ones. The caret is 10px and renders only on the active column;
  a muted caret appears on hover/focus for sortable-unsorted columns (redundant with `aria-sort`,
  never the sole affordance).
- Keyboard (WAI-ARIA grid, row mode): `ArrowUp`/`ArrowDown` and `k`/`j` move the focused row;
  `Home`/`End` first/last; `PageUp`/`PageDown` by 10; `Enter`/`Space` activates. Roving
  `tabIndex` — exactly one row is tabbable. Rows are keyed by id so selection survives a refresh.
- Loading: N skeleton rows at the **exact** final row height and column x-positions. Never a
  spinner, never a collapsed container. Minimum display 300ms. A refetch never re-skeletons.

## 4. Elevation

Blueprint's model: **a hairline ring plus one or two long-throw drop shadows**, not a `border`.
Borders change layout size and cannot stack; every hairline in this system is an inset box-shadow
or a real 1px rule on a divider element. The ring is tinted `226 234 247` (our graphite blue), not
pure white.

| Level | Token | Value | Use |
|---|---|---|---|
| 0 | `--shadow-elev-0` | `inset 0 0 0 1px rgb(226 234 247 / .10), 0 0 10px 0 rgb(0 0 0 / .20)` | flat panel, resting well |
| 1 | `--shadow-elev-1` | ring @ .14 + sheen + `0 1px 10px 0 rgb(0 0 0 / .30), 0 1px 10px -1px rgb(0 0 0 / .20)` | navbar, resting card, pane |
| 2 | `--shadow-elev-2` | ring + sheen + `0 4px 6px -4px rgb(0 0 0 / .50), 0 10px 30px -5px rgb(0 0 0 / .50)` | hover lift, raised card |
| 3 | `--shadow-elev-3` | ring + sheen + `0 20px 25px -5px rgb(0 0 0 / .45), 0 10px 30px -5px rgb(0 0 0 / .45)` | popover, tooltip, command palette |
| 4 | `--shadow-elev-4` | ring + sheen + `0 25px 60px -12px rgb(0 0 0 / .85)` | modal-most (unused; we do not modal) |

**The sheen** — levels 1–4 only — is two sub-pixel inset highlights on the top edge:
`inset 0 0 0.5px 0 rgb(255 255 255 / .28), inset 0 0.5px 0 0 rgb(255 255 255 / .07)`.
This is the single highest-leverage detail: it is what makes a dark panel read as a lit physical
surface rather than a flat gray rectangle. Level 0 does **not** get it.

Additional shadow tokens: `--shadow-well` (input recess:
`inset 0 0 0 1px rgb(226 234 247 / .16), inset 0 1px 2px 0 rgb(0 0 0 / .45)`),
`--shadow-well-focus` (the same plus a brass ring).

**Discipline.** Panes are rectangles separated by 1px lines, not floating cards on a background.
Elevation 2–4 appears only on genuinely floating surfaces (palette, popover, tooltip). Elevation
1 is for the navbar and for a Card that must read as a distinct object. Everything else is
elevation 0 or nothing. Pane corners are square.

## 5. Surface ramp (neutral)

Blueprint's dark ramp structure **exactly** — same six steps, same relative luminance
relationships (L* 8.0 / 13.1 / 16.9 / 21.0 / 24.9 / 29.0, i.e. ≈ +4% lightness per step) — retinted
to our graphite blue-black at **H 218°, S ×1.20**. The asymmetry is deliberate and load-bearing:
surface-to-surface contrast is tiny (≈1.3:1) while text-to-surface contrast is enormous (14.7:1).
That asymmetry is what makes dense panels legible.

| Token | Hex | Blueprint analogue | Role |
|---|---|---|---|
| `--color-ground` | `#101319` | `$black #111418` | app field |
| `--color-surface` | `#1b2028` | `$dark-gray1 #1c2127` | pane, navbar, table header |
| `--color-raised` | `#242932` | `$dark-gray2 #252a31` | card, row hover, control fill |
| `--color-overlay` | `#2e333d` | `$dark-gray3 #2f343c` | popover, menu, selected row |
| `--color-elevated` | `#373d48` | `$dark-gray4 #383e47` | command palette, table chrome |
| `--color-scrim` | `#3e4756` | `$dark-gray5 #404854` | tooltip surface |

Rules (solid, because Tailwind border utilities need a colour):

| Token | Hex | Use |
|---|---|---|
| `--color-rule-muted` | `#262b33` | in-pane separators, table row dividers |
| `--color-rule` | `#2f353f` | pane boundaries, card edges, dividers |
| `--color-rule-strong` | `#3d4654` | active pane boundary, outlined control |

## 6. Ink ramp

Blueprint's dark text ramp structure, warming as it comes forward: the top step is our parchment
identity, the receding steps cool toward the blue-black field.

| Token | Hex | Blueprint analogue | Contrast on `--ground` | Use |
|---|---|---|---|---|
| `--color-ink` | `#e8e4dc` | `$light-gray5` | 14.7 : 1 | body, headings, primary values |
| `--color-ink-muted` | `#b0b4ba` | `$gray4 #abb3bf` | 8.9 : 1 | secondary values, icons |
| `--color-ink-dim` | `#8a9099` | `$gray3 #8f99a8` | 5.8 : 1 | metadata, mono ids |
| `--color-ink-faint` | `#626a75` | `$gray1 #5f6b7c` | 3.4 : 1 | column headers, micro labels |
| `--color-ink-disabled` | `#4c535d` | `$gray1 @60%` | 2.4 : 1 | disabled text only |

`--color-ink-faint` at 3.4:1 is below AA for body text and is therefore permitted **only** for
10–11px uppercase micro-labels and column headers, which are structural chrome, never content.

## 7. Semantic colour

Exactly four hues. ISA-101 doctrine: ≥ 90% of pixels are neutral at rest; colour enters only on
deviation and on operator-action states. Desaturate a screenshot — the only survivors should be
the severity rail, the status pills, the LIVE dot, and the selected row.

| Family | Base (fill/rail) | Text-on-dark | Edge | Deep | Means |
|---|---|---|---|---|---|
| brass | `#b8934a` | `#bb9853` | `#5e4c28` | `#3a2f18` | **structure only** — labels, rules, active nav, focus, the rail |
| oxblood | `#a03a32` | `#db8076` | `#51201c` | `#321311` | **money is being stopped** — `contradicts`, `BLOCK`, `blocked` |
| verdigris | `#4a8f7b` | `#5eac95` | `#28493f` | `#182d27` | released, confirmed, `supports`, healthy |
| amber | `#c9873a` | `#ce914b` | `#674620` | `#402b13` | held, awaiting, dormant, escalated |
| neutral | `--ink-dim` | `--ink-dim` | `--rule-strong` | — | opened, inconclusive, no deviation |

**Rules.**
- `-text` variants are the *only* values permitted for text on a dark surface. They clear 4.5:1
  on `--color-raised`. The base value is for fills, rails, dots, and 1px edges — never for text.
- Alpha fills for pills: base at **14%** for a resting fill, **22%** for the selected/active
  state. Tokens: `--fill-{family}` and `--fill-{family}-strong`.
- **Redundant encoding is mandatory.** Severity = colour + position (2px left rail) + a text
  token. Colour alone fails grayscale, colour-blindness, and video compression.
- Never animate a severity colour on a loop. Flash once for ≤ 400ms on transition, then hold.
- Never use a severity hue for a primary button, a link, a chart series, or the focus ring.

### State → tone map (authoritative)

| `CaseState` | Tone | | `Verdict` | Tone | | `Outcome` | Tone |
|---|---|---|---|---|---|---|---|
| `opened` | neutral | | `supports` | verdigris | | `RELEASE` | verdigris |
| `held` | amber | | `contradicts` | **oxblood** | | `BLOCK` | **oxblood** |
| `verifying` | brass\* | | `inconclusive` | neutral | | `ESCALATE` | amber |
| `awaiting_callback` | amber | | | | | | |
| `challenging` | brass\* | | | | | | |
| `adjudicating` | brass\* | | | | | | |
| `escalated` | amber | | | | | | |
| `released` | verdigris | | | | | | |
| `blocked` | **oxblood** | | | | | | |

\* The three in-flight states are brass because they are *process*, not status — the case has no
verdict yet, and brass is the structure hue. This is the one sanctioned brass-on-a-state usage and
it is why N2 is phrased as "never status": an in-flight state is not a status.

## 8. Type

Three families, no more. `font-variant-numeric: tabular-nums` is applied globally to every table
cell, figure, counter, and timer.

- **Display** — Newsreader. Case titles, section heads, the verdict, the exposure figure.
- **Interface** — Inter Tight. Everything else.
- **Data** — IBM Plex Mono. Money, account fragments, case ids, hashes, session ids, timestamps,
  latencies, confidence.

| Token | px | rem | Line-height | Use |
|---|---|---|---|---|
| `--text-micro` | 10 | .625 | 14px | uppercase chip and pill text, kbd |
| `--text-mini` | 11 | .6875 | 15px | column headers, table cells, metadata, mono ids |
| `--text-xs` | 12 | .75 | 16px | body, field values |
| `--text-sm` | 13 | .8125 | 18px | emphasis body, row primary text |
| `--text-base` | 14 | .875 | 18px | Blueprint base; prose, agent reasoning (1.5 line-height) |
| `--text-lg` | 18 | 1.125 | 22px | pane/entity titles (SLDS page-header title) |
| `--text-xl` | 22 | 1.375 | 26px | case titles (Blueprint h3) |
| `--text-2xl` | 28 | 1.75 | 32px | surface headline (Blueprint h2) |
| `--text-figure` | 44 | 2.75 | 1 | **the exposure figure** — one per screen |
| `--text-verdict` | 52 | 3.25 | 1 | **the verdict** — one per screen |

Ceiling discipline: exactly two elements on any screen may exceed 28px, and they are the verdict
and the exposure figure. Everything else steps down sharply.

**Micro-label** (`.label-micro`, `.label-brass`) is the single sanctioned uppercase treatment:
10px / weight 600 / `letter-spacing 0.09em` / uppercase. It appears on column headers, field
labels, and group headings, and nowhere else. Applying uppercase tracking to every heading level
is a template tell.

**Label above value, label smaller than value** (SLDS). A key/value pair is a 10px
`--color-ink-faint` uppercase label over a 12–13px `--color-ink` value. `KeyValue` stacks;
`FieldRow` puts the label in a fixed 132px left column for dense definition lists. Never make the
label the same size as the value.

## 9. Focus

**One global rule, not per-component** (Blueprint):

```css
outline: 2px solid rgb(184 147 74 / .75);   /* --color-brass @ 0.752 */
outline-offset: 2px;
```

The alpha is deliberate: it is the value that holds a ≥ 3:1 focus contrast against every surface
in the ramp from `--ground` through `--scrim`. Do not substitute a solid colour.

Exceptions, and only these:
- **Text inputs** do not use an outline. Their focus is a box-shadow well
  (`--shadow-well-focus`), because the recess *is* the affordance and an outline would fight it.
- **Pills/tags** use `outline-offset: 0` (Blueprint) — a 2px offset on an 18px pill collides with
  its neighbour.
- The **active pane** carries `inset 0 0 0 1px --color-rule-strong` so the operator (and the
  video viewer) can always see where keystrokes are going.

Focus is always visible on `:focus-visible`. We do not run a focus-style manager; on a muted
recording an invisible keyboard model is an absent one.

## 10. Motion

| Duration | Easing | Use |
|---|---|---|
| 100ms | `cubic-bezier(.4, 1, .75, .9)` | hover, press, selection, colour |
| 150ms | same | pane/panel reveal |
| 200ms | same | positional — tab indicator, progress meter width, caret rotation |
| 260ms | `cubic-bezier(.16,.84,.44,1)` | a finding slotting into the rail |
| 420ms | ease-out | the strike-through on a rebutted argument |
| 700ms | ease-out | new-row highlight decay |
| 900ms | `cubic-bezier(.22,1,.36,1)` | **the tip** — one orchestrated moment |
| 1600ms | ease-in-out, infinite | the LIVE dot pulse. Exactly one on screen. |

Banned: transform/scale/translate on rows or cards; parallax; spring physics; staggered list
entrances; shimmer skeletons; anything over 200ms on a routine interactive affordance.
`prefers-reduced-motion` collapses the tip to a state change and zeroes everything else.

## 11. Border radius

| Value | Where |
|---|---|
| 0 | panes, table cells, pane corners, dividers |
| 2px | status pills, severity swatches |
| 3px | inputs, chips, kbd |
| 4px | buttons, cards, callouts, tags (Blueprint `$pt-border-radius`) |
| 6px | command palette overlay — the **only** surface above 4px |
| 9999px | the LIVE dot and state dots only |

Nothing else. A 12px-rounded data container reads as a marketing site.

## 12. Numeric and identifier rendering

- **Money** — right-aligned, decimal-aligned, tabular, mono. `$12,480` in grids (0 decimals),
  `$12,480.00` in the detail pane and on the figure (2 decimals, always). Currency code is a
  separate 10px muted suffix, never inline. One format per column, always.
- **Identifiers** — mono 11px, `--color-ink-dim`, **middle-truncated** (`case_8f3a1c…c19d`), never
  end-truncated; the discriminating characters are at the end. Fixed width in `ch`. Full value in
  `title`. Click-to-copy confirms with a check glyph for 900ms — never a toast.
- **Hashes** — 10 chars + ellipsis, mono, `--color-ink-faint`.
- **Latency** — integer ms, fixed 6ch: `842ms`, `1.20s` above 1000. Never a float with 6 decimals.
- **Confidence** — `0.87`, two decimals, with at most a 3px × 64px bar behind it. Never a donut,
  never a radial gauge, never a progress ring for a scalar.
- **Timestamps** — fixed-width, timezone declared **once in the column header**, never per row.
  Relative time only as a secondary muted line. An audit surface that shows only "3 minutes ago"
  is not auditable.

## 13. Component inventory

Everything below lives in `web/src/components/primitives.tsx` unless noted. Nothing may be
re-implemented locally in a view.

### Structure
| Component | Contract |
|---|---|
| `Panel` | Pane with a 30px header (`label-brass` title + right-aligned actions) and an independently scrolling body. `elevation?: 0\|1`. |
| `Card` | `elevation?: 0..4`, `compact?`, `interactive?`, `selected?`. Padding 20px, compact 16px, radius 4px. Interactive hover → elevation 2. |
| `Divider` | 1px `--color-rule`. `vertical?` renders 20px tall with 8px horizontal margin (Blueprint navbar divider). |
| `SectionHeader` | 30px, `label-brass`, 1px bottom rule, optional right slot. |
| `Callout` | `intent`, optional `icon`, `compact?`. 16px padding (compact 8px), 40px left padding when it has an icon, icon absolute at left 16 / top 18. Neutral fill `--color-raised`; intent fill is the family at 14%. |
| `NonIdealState` | Vertical flex, centred, every child `max-width: 400px` with `margin-bottom: 20px` except the last. Visual icon is one ramp step *quieter* than the body text. Slots: `visual`, `title`, `description`, `action`. |
| `EmptyState` | Thin wrapper over `NonIdealState` — kept for source compatibility. |

### Controls
| Component | Contract |
|---|---|
| `Button` | `variant: 'default' \| 'minimal' \| 'outlined'`, `tone`, `size: 'xs'\|'sm'\|'md'\|'lg'` → 20/24/30/40px. Padding 0 8px (md: 4px 8px, lg: 4px 16px). Icon-only stays square. `default` = neutral fill + inset ring + 1px drop. `minimal` = no fill, no ring at rest; hover 8% wash, active 16%. `outlined` = real 1px border, no fill. Toolbars use `minimal`; only a commit action uses `default`. |
| `Input` / `FormGroup` | 30px (sm 24, lg 40), padding 0 8px, radius 3px, `--shadow-well` at rest, `--shadow-well-focus` on focus. `FormGroup` supplies a `label-micro` label, optional helper, and intent. |
| `Tabs` | 30px tabs, 20px column gap, `role="tablist"`, roving `tabIndex`, `aria-selected`, `aria-controls`. Selected: `inset 0 -2px 0 --color-brass` + brass text. Indicator transitions 200ms. |
| `Tooltip` | Opens on hover **and** focus, 100ms, `--color-scrim` surface, elevation 3, 11px, max-width 280px. Supplementary only — never the sole carrier of information (N3). |
| `Breadcrumbs` | 11px, `--color-ink-dim`, 4px chevron separator, current item `--color-ink` and not a link. |

### Status and data
| Component | Contract |
|---|---|
| `Pill` / `Tag` | 18px min-height, 10px uppercase, weight 600, `letter-spacing .08em`, padding 0 6px, radius 2px, `min-width: 68px` in a status column so it never jitters. Exactly **one** encoding: either a 14% fill + `-text` colour, or a dot + neutral text. Never dot + fill + coloured text + icon. |
| `Dot` | 5px, `--color-{family}`, `live?` pulses 1600ms. |
| `StateChip` | `Pill` bound to `STATE_TONE` and `stateLabel`. |
| `ScopeChip` | Mono 10px. Denied is struck-through neutral, **deliberately not oxblood** — a denial is the system working, not money being stopped. |
| `CasePath` | SLDS Path over `CaseState`. Six stages: Opened → Held → Verifying → Challenging → Adjudicating → Outcome. 30px chevrons, `min-width 80px`. `current` = where the case actually is; `active` = which stage the operator is inspecting; both classes can co-exist. A terminal outcome recolours the **whole track**, not one stage. Complete stages carry a check glyph, so the encoding survives grayscale. |
| `ProgressBar` | Track 6px, radius 9999px, fill `--color-rule`; meter transitions width 200ms. `indeterminate` renders a 2px sweep. Never used for an unbounded stream. |
| `Money` | `size: 'sm'\|'md'\|'lg'\|'figure'` → 13/16/22/44px. Mono, tabular, right-alignable. |
| `MonoId` | 11px mono. `truncate` middle-truncates and sets `title`. `copyable` adds click-to-copy with a 900ms check. |
| `ConfidenceBar` | 3px × 64px bar + `0.87` in 10px mono. |
| `Latency`, `Timestamp` | Fixed-width mono, tabular. |
| `KeyValue` | Label **above** value (SLDS). |
| `FieldRow` | Label in a fixed 132px left column (dense definition list). |
| `Kbd` | 18px chip, 10px mono, 1px `--color-rule-strong`, radius 3px. Every action button that has a shortcut renders one. |

### Chrome (`AppShell.tsx`)
| Component | Contract |
|---|---|
| `AppShell` | 24px synthetic banner / 50px navbar / 56px rail + content / 26px status bar. Nothing in the chrome scrolls. |
| `Navbar` | 50px, padding 0 16px, `--color-surface`, elevation 1, `z-index: 10`. Left group: heading (18px display) + divider + fleet strip. Right group: minimal buttons + dividers. Dividers are 1px × 20px with 8px horizontal margin. |
| `NavRail` | 56px, four 52px targets, 16px icon over a 9px label, active = 2px brass left border + `--color-raised` fill + brass glyph. `aria-current="page"`. |
| `StatusBar` | 26px, 10px, tabular. LIVE dot + heartbeat + counters left, latency + mode/platform right. This is the persistent proof-of-liveness for a muted recording. |

### Grid (`DataGrid.tsx`)
See §3. Public API is `DataGrid<T>` + `Column<T>`; `Column` gains `numeric`, `title`, and
`headerTitle`. `DataGrid` gains `loading`, `skeletonRows`, `label`, `density`, `onActivate`.

---

## 14. Layout skeletons

**Console** — 3 panes: queue 440px | the Balance 1fr | ledger 320px. Below 1440px the ledger
collapses into a tab in the right of the Balance pane. Minimum before overlay: 1100px.

**Docket** — queue 380px | case file 1fr, with a 5-tab strip at 30px.

**Registry** — catalog 1fr | agent detail 420px. The catalog column splits vertically:
catalog 1fr over a 240px **red-team** band. The scoreboard is a claim about the agents listed
above it, so it shares their column rather than becoming a fifth surface.

**Posture** — event feed 1fr | fleet-wide claims 440px. The left column is two panes (guardrail
screening, identity denials); the right is three (threat exchange, gateway routing, scope
manifest). The two columns' horizontal rules no longer share a y, which held while both carried
two claims; the exchange is a third claim about a boundary and belongs beside the other two
rather than interleaved with the case feed. 400 → 440 because the exchange grid declares four
fixed columns and a flexible one, and 400 forced the pane to scroll horizontally.

Pane dividers are a single 1px `--color-rule` line, no decoration, no gradient, no shadow, no
rounded pane corners.

---

## 15. Conformance checklist

Testable assertions. A surface is conformant only if every one holds.

**Tokens**
1. No `.tsx` file under `web/src` contains a colour literal — no `#rrggbb`, no `rgb(`, no `hsl(`.
   Every colour reaches a component as `var(--color-*)` or `var(--shadow-*)`.
2. Every reference to an oxblood token in `web/src` is reachable only from `contradicts`,
   `BLOCK`, or `blocked`. The tone tables in `primitives.tsx` are the only declaration sites.
3. No occurrence of `#0176d3`, `#1b96ff`, `#2d72d2`, `#215db0` anywhere under `web/src`, and no
   occurrence of the strings `Salesforce`, `Lightning`, `Palantir`, `Blueprint`, `Foundry` in any
   rendered string, class name, `title`, or `aria-label`. The single exemption is the
   `blueprint-exact` label on the commented-out A/B `@theme` block in `tokens.css` (§17), which
   never reaches a rendered byte. Source comments elsewhere should say "the reference system".
4. No `backdrop-filter` and no `blur(` in `web/src`. Exactly one `linear-gradient`, in `.struck`.
5. Every `--color-*`, `--shadow-*`, `--text-*` and `--spacing-*` referenced by a component is
   declared in `tokens.css`. `@theme static` guarantees each one is emitted even when unused, so
   a token named in this document is always resolvable.

**Geometry**
6. Every control height in the tree is one of 18, 20, 24, 30, 40, 50.
7. Every table row height is 24, 28, or 32; every table column header is 30.
8. Every `border-radius` is 0, 2, 3, 4, 6, or 9999px.
9. No layout value is 5, 10, 14, 18, or 30px (30 is permitted only as a height).
10. Every pane header in every surface is exactly 30px. No two adjacent chrome bands differ by
    1 or 2px.

**Type**
11. Every font-size is one of 10, 11, 12, 13, 14, 18, 22, 28, 44, 52.
12. At most two elements per surface exceed 28px, and they are the verdict and the exposure figure.
13. `font-variant-numeric: tabular-nums` resolves on every `td` and every element carrying money,
    a latency, a confidence, or a counter.
14. The only uppercase + letter-spaced treatment is `.label-micro` / `.label-brass` at 10px.

**Elevation**
15. No component sets a `border` on a card or a panel; hairlines are inset box-shadows or
    dedicated 1px divider elements.
16. Elevation 2–4 appears only on the command palette, popovers, and tooltips.
17. `--shadow-elev-1` through `-4` each contain both sheen insets; `--shadow-elev-0` contains
    neither.

**Behaviour**
18. `document.body` has `overflow: hidden`; every scroll container is a pane.
19. `DataGrid` emits `aria-sort` on **every** sortable column, `"none"` when unsorted.
20. `DataGrid` has exactly one row with `tabIndex=0` at all times; arrow keys move focus without
    a fetch; `Enter` activates.
21. A `DataGrid` in `loading` occupies the same pixel height as the same grid with
    `skeletonRows` rows of data.
22. No component renders a different number of DOM nodes when an optional value is absent —
    absent values render an em-dash.
23. Every icon-only button carries a `title` **and** an accessible name.
24. `prefers-reduced-motion: reduce` zeroes every animation and transition duration.
25. Exactly one pulsing LIVE indicator exists in the DOM at any time.

**Recording**
26. At 1920×1080, 100% zoom, the queue shows ≥ 20 rows.
27. Desaturating a full screenshot leaves the layout fully legible, and the only elements that
    lost information are the severity rail, the status pills, the LIVE dot, and the selected row.
28. No text under 10px. No body text at or above 16px.
29. `npx tsc --noEmit` in `web/` exits 0.

---

## 16. Deliberate deviations from source

| # | Source says | We do | Why |
|---|---|---|---|
| D1 | Blueprint `th` carries no background and no rule | Opaque `--color-surface` header + 1px rule | A transparent sticky header smears under video compression while scrolling |
| D2 | SLDS chevrons are two skewed pseudo-elements | `clip-path: polygon(...)` | Same silhouette, one element, no seam to maintain; we match structure, not implementation |
| D3 | SLDS cell buffer is 24px | 12px | 24px at a 380–440px queue pane costs a whole column |
| D4 | Blueprint focus is `rgba(33,93,176,.752)` (brand blue) | `rgb(184 147 74 / .75)` (brass) | N6 — no vendor brand blue. Alpha and offset are kept exactly |
| D5 | SLDS body base is 13px | 12px body / 11px table | Our panes are narrower than a Lightning record page |
| D6 | Blueprint dark ring is `rgba(255,255,255,.2)` | `rgb(226 234 247 / .10–.14)` | Pure white at 20% on our darker ground reads as a drawn border, which defeats the elevation model |
| D7 | Blueprint elevation-0 has no sheen | unchanged | Kept exactly; the sheen is what distinguishes a floating surface from a flat one |
| D8 | SLDS "selected and hovered rows are the same grey" | selected is one ramp step above hover + a 2px brass rail | Multi-row visibility matters more to us than SLDS fidelity |
| D9 | — | 240px red-team band on Registry, 440px right column on Posture with three rows | §14; both stated there. A pane that must scroll horizontally is a worse violation than an unaligned rule |

---

## 17. A/B palette

`tokens.css` carries a commented-out `@theme` block containing Blueprint's **literal** dark-theme
hex values under our token names. Swapping the two blocks is a one-edit A/B of "our graphite" vs
"Blueprint exact" with zero component changes. If the literal block ever ships, N6 is violated —
it exists to prove the ramp structure is right, not to be used.
