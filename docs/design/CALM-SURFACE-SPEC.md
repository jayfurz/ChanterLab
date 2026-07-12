# Calm Surface — UI design spec (issue #73)

**Version 2 — 2026-07-11. Status: as-built contract + forward plan.**

v1 of this spec (2026-07-04, commit `a290430`) was the pre-implementation design gate
for Sprint 4. Its wave-B implementation shipped the next day — B1 `cdd1189`
(mini-row, tabbed drawer, one-tap mute; closed #62/#61) and B2 `0ce6f15` (desktop
rail, keyboard map, PWA; closed #72) — and reached `main` in the BASE-01 reconcile
(PR #91). The surface then kept evolving: per-note verdict coloring (#79), the guided
tour replacing the coach-mark bubbles, and the iOS-driven Sound-pane rows (#74).

v2 reconciles the spec with what actually shipped, adds the normative layers v1
lacked (design tokens, component states, calm rules during singing, accessibility),
records three **measured compliance violations** found in the 2026-07-11 as-built
audit, and phases the remaining work into reviewable PRs. **This document is the
UI contract for the training app surface**: implementation agents build against it;
changes to the surface that contradict it require amending it first.

---

## Table of contents

- [§0 How to read this document](#0-how-to-read-this-document)
- [§1 The problem, in numbers (v1 baseline, historical)](#1-the-problem-in-numbers-v1-baseline--historical)
- [§2 What "calm" means — design principles](#2-what-calm-means--design-principles)
- [§3 Design tokens](#3-design-tokens)
- [§4 Information hierarchy per surface](#4-information-hierarchy-per-surface)
- [§5 Component inventory with states](#5-component-inventory-with-states)
- [§6 Interaction rules during singing — the calm rules](#6-interaction-rules-during-singing--the-calm-rules)
- [§7 Scoring results surface (#60)](#7-scoring-results-surface-60)
- [§8 Keyboard and pointer map](#8-keyboard-and-pointer-map)
- [§9 Accessibility](#9-accessibility)
- [§10 As-built drift ledger (v1 → shipped)](#10-as-built-drift-ledger-v1--shipped)
- [§11 Forward plan — phases mapping to reviewable PRs](#11-forward-plan--phases-mapping-to-reviewable-prs)
- [§12 Evidence galleries and mockups](#12-evidence-galleries-and-mockups)
- [§13 Decision log](#13-decision-log)

---

## §0 How to read this document

* **Owner**: §2 (principles), §6 (calm rules + the three violations), §11 (what the
  next PRs are), §13 (decisions awaiting you).
* **Implementation agent**: §11 Phase 1 is fully specified — files, exact changes,
  acceptance criteria, and the MUST-NOT-BREAK contract. §3/§5 are your reference for
  any pixel you touch; §6 is the law every change is reviewed against.
* **Historian**: §1 is the measured 2026-07-04 baseline that motivated the redesign;
  §10 is what shipped versus what was drawn.

Roadmap anchors: `docs/APP-ROADMAP-2026.md` §7-10 — "Preserve the calm surface;
advanced controls stay secondary" — and `docs/plans/40-practice-audio/ORCHESTRATOR.md`
— "deepen repeated practice while preserving the calm interface". Every plan in the
40-lane that touches `index.html`/`style.css`/`transport.js` inherits §6 as an
acceptance gate.

---

## §1 The problem, in numbers (v1 baseline — historical)

Measured live on 390×844 and 1400×900, 2026-07-04 (`docs/design/current/*.png`):

* The expanded transport was **12–14 rows**, covering **100 % of the score** on a
  phone (`mobile-02-transport-expanded.png`).
* **Measured defect:** `.full` was `max-height:70vh; overflow:hidden`. With the
  Complete Liturgy loaded plus mic and a saved-recording chip, content was 658 px in
  a 591 px box: the Sections row — the only navigation for a 422-measure service —
  showed **9 px of its 48 px height and could not be scrolled to**
  (`mobile-12-sections-row-clipped.png`).
* Desktop was a stretched phone: a 1400 px-wide bottom sheet, Play stretched to
  ~200 px, control rows wrapping into flex soup over the bottom ~45 %.
* The post-lap report rendered at the **top** of the page; every control that reacts
  to it sat at the **bottom**.
* Two testers, unprompted: "as a phone app the screen is pretty busy"; "I wonder how
  it would look as a desktop program?" (#62, #72).

**Resolution, verified as-built 2026-07-11** (`docs/design/asbuilt-2026-07-11/`):
the tabbed panes are bounded (`max-height:min(46vh,420px); overflow-y:auto`) so no
row can ever be clipped unreachable (Sound pane measured 368/368 px on 390×844 —
fits; scrolls when taller); the desktop rail replaced the stretched sheet; the
report moved to the transport's doorstep. The baseline stands as the cautionary
record: density regrows one "just one more row" at a time — §4's placement rules
exist to stop that.

---

## §2 What "calm" means — design principles

The product's core loop is a singer, mid-phrase, eyes on a gold line. Everything
else is secondary. Concretely:

1. **One primary action.** Play/Pause is the only large gold button. Nothing else on
   the default view competes with it in size or saturation.
2. **The default view is the singing view.** Score + singscope + mini-row. Every
   control that is not touched *while sound is happening* lives one tap away, behind
   the handle, grouped by question ("what am I practicing" / "what do I hear" /
   "everything else").
3. **Stability over discoverability.** While a singer is mid-phrase, **nothing may
   move, appear over a control, or reflow** (§6 is the precise law). Feedback during
   playback is text in fixed slots and paint on existing surfaces — never geometry.
4. **Contextual controls vanish, not disable.** Sectionless pieces show no section
   controls; single-verse pieces show no verse row; mic-off shows no rec-mix row.
   Hidden means `display:none` — a greyed row is still noise. (Corollary: every
   element that can carry `hidden` MUST have a `[hidden]{display:none}` escape hatch
   if any author rule sets its `display` — see V2 in §6.)
5. **One vocabulary.** Segmented `.seg/.segbtn` for exclusive choices, `.chk` for
   independent toggles, `.btn` for actions, chips for status-that-acts. A new
   control reuses one of these or amends this spec first.
6. **Dark room, gold ink.** The dark/gold identity is the brand (§3); the score
   stays paper-white because notation legibility beats theme purity.

---

## §3 Design tokens

Single source of truth: `training-prototype/style.css` `:root` plus the derived
constants below. Anything not in this section is not part of the palette — a new
color/size/shadow is a spec amendment, not a local convenience.

### 3.1 Color

| Token | Value | Role |
|---|---|---|
| `--bg` | `#14151a` | App background; PWA `theme_color`/`background_color`. |
| `--panel` | `#1e2027` | Cards: report strip, sheets, calibrate panel. |
| `--ink` | `#e8e6df` | Primary text. |
| `--sub` | `#9aa0a6` | Secondary text: labels, status, meta. |
| `--gold` | `#d4af37` | THE accent: primary action, active segment, selected voice, "your part". Text on gold is `#161616`. |
| `--gold-soft` | `#e7c96b` | Hover/focus tint, section glyphs, group labels, tour ring. |
| `--line` | `#2c2f38` | 1 px borders everywhere; elevation is borders first, shadows second. |
| `--cyan` | `#4dd7ff` | The singer's live voice: scope trace, readout, mic-on state. Never used for anything else. |

Derived surfaces (fixed constants in rules): input well `#12141a`; button face
`#20232c`; overlay scrims `rgba(24,26,33,.96)` (transport), `rgba(10,11,15,.92)`
(library), `rgba(8,9,12,.66)` (tour dim); score paper `#fbfbf7`.

Semantic families:
* **Recording = red**, quarantined to the record control: `#ff4b3e` pulse dot,
  `#c0392b` border, `#3a1414` face, `#ffd7d0`/`#ff8a7a` text.
* **Verdict tints** (per-note coloring #79; single source `loader.js
  VERDICT_TINTS`): hit `#4f9d2e`, flat `#2f7fc4`, sharp `#e07a1c`, missed
  `#a35050`. These appear only on noteheads and in the report legend dots.
* **Diagnostics** (audio-debug overlay, never part of the normal UI): monospace
  greens/blues on near-black.

Rule: one accent per meaning. Gold = yours/active; cyan = your live voice; red =
recording; verdict tints = scoring. A feature needing a "new color" almost
certainly means one of these four meanings — reuse it.

### 3.2 Typography

Stack: `system-ui, -apple-system, Segoe UI, Roboto, sans-serif`; base
`15px/1.45`; diagnostics use `ui-monospace` (never in the product surface).

| Size | Weight | Use |
|---|---|---|
| 10 px | 700–800, uppercase, `.05–.09em` tracking | `.label` row labels, tour step, desktop pane group labels. Smallest text in the app — never smaller. |
| 11 px | 400–600 | Hints (scope hint, rec hint, attribution, licensing link). |
| 12 px | 400–700 | Status line, report totals/spots, meta rows, `.btn-mini`. |
| 13–13.5 px | 400–700 | Checkboxes, seg buttons, pane tabs, position readout, chips. |
| 14–15 px | 600 | Standard buttons, list rows, tour body. |
| 16 px | 650 | h1 (mobile), standard `.btn`, library search. |
| 17 px | 600 | Play (`.btn.big`). |
| 18–20 px | 650–700 | Voice letters (`.vbtn`), h1 desktop, scope readout. |

Rules: **no new sizes**; **`font-variant-numeric: tabular-nums` on every live
number** (position readout, lap counts, timers, library count) so ticking text
never changes width; single-line truncation is `ellipsis`, never wrap, for status /
chip / piece title.

### 3.3 Spacing, radius, hit targets

* Spacing steps: 2 / 4 / 6 / 8 / 10 / 12 / 14 / 16 / 20 px. Row gap 8 (10 for roomy
  rows); page gutter 10 px mobile, 20 px ≥760.
* Radius: 8 (inputs, small buttons), 10 (segs, menus), 12 (buttons, panels, tour
  spot), 14–16 (cards, sheets), 999 (chips, pills). Sheets square off the
  screen-edge side (`16 16 0 0`).
* Hit targets: **44 px minimum**; 48 px preferred (`.btn`, `.vbtn`, library rows);
  Play 52 px. The handle row is 26 px tall but full-width (the whole row toggles).
  `touch-action: manipulation` on every custom control.
* Safe areas: transport bottom padding and library head/foot include
  `env(safe-area-inset-*)`; `--transport-h` already incorporates it — consumers of
  the var must not double-count.

### 3.4 Elevation and blur

Borders first (`1px var(--line)`), shadows only for genuinely floating surfaces:
transport `0 -8px 28px rgba(0,0,0,.5)`; report/help/menus `0 8–10px 24–30px .5–.55`;
sheets/tour/calibrate `0 ±12–18px 40–50px .6`. Backdrop blur: 8 px transport, 4 px
library/calibrate, 3 px sheet/diagnostics. Desktop rail is **flat** (border only) —
it is architecture, not a floater.

### 3.5 Motion

| Duration | Use |
|---|---|
| 0.12 s | Control state (vbtn hover/active). |
| 0.2 s | Tour spot/card glide. |
| 0.22 s | Sheet slide-up, drawer opacity. |
| 0.25–0.3 s | Chevron rotate, drawer max-height. |
| 0.7 s / 1.1 s | Spinner / recording pulse (the only loops). |

`:active { transform: translateY(1px) }` is the standard press. Structural motion
(drawer, sheets) runs only on user action or at play-start (auto-collapse) — never
mid-playback (§6). `prefers-reduced-motion` is not yet honored — Phase 3 (§11).

---

## §4 Information hierarchy per surface

Same DOM everywhere; three CSS presentations. Breakpoints: `<760` phone,
`760–999` tablet (roomier phone, tabs kept, content capped 820 px),
`≥1000` desktop (two floated columns; the fenced append-only block at the end of
`style.css`).

### 4.1 Mobile (<760 px)

Cold load (`asbuilt…/mobile-01-cold-load.png`) — transport starts collapsed:

```
┌──────────────────────────────────────┐
│ ChanterLab                        (?)│  header: h1 + help menu only
│ ┌──────────────────────────────────┐ │
│ │ singscope (27vh in split view)   │ │  gold lane = your part
│ │  …mic hint text (bottom edge)…   │ │
│ └──────────────────────────────────┘ │
│ ┌──────────────────────────────────┐ │
│ │ score (paper, internal scroll)   │ │
│ │                                  │ │
│ └──────────────────────────────────┘ │
│         (reserved: report airspace)  │  fixed slot above transport
├──────────────────────────────────────┤
│ Loaded: 4 voices, 4 measures…      ⌄ │  handle row = status + chevron
│ [ ▶ Play      ] [■] [m –] [§] [🔇 S·Soprano] │  mini-row
└──────────────────────────────────────┘
```

**Always-visible set** (the mini-row, defended in v1 §2, unchanged): Play/Pause
(flex), Stop, position readout, `§` section shortcut (**contextual** — hidden for
sectionless pieces), voice chip (**one-tap mute**, 🔇/🔊 glyph is the state).
Mic is deliberately NOT here (v1's hardest call, confirmed by shipping): a sixth
item breaks the 390 px budget, and mic has three other prompts. The handle row
(status + chevron, full-width tap target) owns expansion.

Expanded (`mobile-02…04.png`): three tabs inside the drawer — **Practice / Sound /
More** — each pane bounded `min(46vh,420px)` and independently scrollable, so ≥50 %
of the screen always shows scope/score. Default tab is Practice on every load; no
persistence. Playing auto-collapses the drawer to the mini-row.

**What leaves the default view and where it goes (as-built pane map;**
† = contextual, hidden exactly as before):

| Practice (default) | Sound | More |
|---|---|---|
| Your voice (S/A/T/B or mono Playing/Muted) | Mic + Headphones mode + Also play my part | Library + current piece + PDF † |
| Verse † | Volume (#74 F5) | Scoring strictness |
| Tempo | Playback sync (#74) | View Split/Score/Scope |
| Loop from–to–on | Voice response (#74) | |
| Section row † | Calibrate wizard (disabled, hidden — see §6 V2) | |
| | Sound Synth/Voices | |
| | Record + timer + save chip | |
| | Rec mix † + rec hint † | |

Placement rule for future controls (this is how density stays dead): classify
every new control as **ES** (every-session) / **PP** (per-piece) / **SO**
(setup-once) / **R** (rare) — v1 §1 has the worked 35-row example. ES-while-paused
→ Practice; hearing/capture → Sound; SO/meta → More; **nothing** joins the mini-row
without naming which of the five items it displaces. Timing sliders (SO) sit in
Sound rather than More as an accepted exception — they are ear-adjacent and were
field-tuned; revisit if Sound grows past one pane-height again (§13 D4).

### 4.2 Tablet (760–999 px)

The same tabbed layout with more air: 20 px gutters, 44 px buttons, pane cap
`min(52vh,460px)`, transport content max-width 820 px centered. No layout branch.

### 4.3 Desktop (≥1000 px)

Two floated columns (`desktop-01-cold-load.png`); floats, not grid — grid's row
auto-placement couples row heights across columns (documented in the CSS fence):

```
┌───────────────────────────────────────────┬──────────────────────┐
│ ChanterLab                            (?) │ status line          │ ← rail = #transport,
│ ┌───────────────────────────────────────┐ │ [▶ Play][■][m –][🔇 S]│   static, border-left,
│ │ singscope (full column width)         │ │  ↑ mini-row: sticky  │   internal scroll
│ └───────────────────────────────────────┘ │ ── PRACTICE ──────── │
│ ┌───────────────────────────────────────┐ │ voice S A T B        │
│ │ score                                 │ │ tempo ───────●────   │
│ │ (fills remaining height)              │ │ loop [1]–[4] ☐ on    │
│ │                                       │ │ ── SOUND ─────────── │
│ │                                       │ │ mic · volume · sync  │
│ │                                       │ │ record …             │
│ │                                       │ │ ── MORE ──────────── │
│ └───────────────────────────────────────┘ │ library · view …     │
└───────────────────────────────────────────┴──────────────────────┘
   1fr, 20px gutters                            380px
```

* Rail = the same `#transport` node made static; tab strip hidden; all three panes
  stacked with small-caps gold group labels (`.pane::before` from `data-pane`);
  mini-row sticky at the rail's scrolled top; chevron hidden (collapse mechanics
  are visually neutralized — `setOverlay()` still fires harmlessly).
* Singscope stays in the left column above the score (its time axis is horizontal;
  a 380 px rail would crush it), keeping the now-line adjacent to the gold cursor.
* The report card lays into the rail (currently at its top — **that placement is
  V1, the displacement violation**; Phase 1 defers the card during playback, §11).
* PWA: manifest + committed icons, `display:standalone`, dark theme; no service
  worker yet (offline remains a roadmap item).

---

## §5 Component inventory with states

Composite widgets first, then shared primitives. "Hidden" always means
`display:none` via `[hidden]` (see §6 V2 for the one broken case). The v1 §1
35-row control-by-control table (ids, owner modules, frequency classes) remains
accurate for ids/ownership; this table is the states layer on top.

| Component | States | Notes |
|---|---|---|
| Play `#play` | `▶ Play` / `⏸ Pause` label swap | Same geometry both states; only gold `.primary.big`. Space. |
| Stop `#stop` | enabled (always) | Ends lap → final score → report. |
| Position `#posOut` | idle `m –` / ticking `m N` | Passive; tabular-nums; smoke asserts exact `m –` after Stop. |
| Voice chip `#voiceChip` | audible 🔊 / muted 🔇 × voice letter+name | Tap = one-tap mute (#61): multi-voice flips `#hearMine`; mono calls `setMelodyMuted`. Gold pill, ellipsizes ≤48 vw. |
| `§` mini `#sectionsMini` | hidden / visible (multi-section pieces) | Opens `#sectionSheet`; gold glyph. |
| Handle row | status text: loading (`.busy` spinner) / `Loaded: …` / `Playing — X muted…` / `Lap N: X% · best Y%` / error + Retry visible | Whole row toggles the drawer; chevron rotates 180° when collapsed; hidden ≥1000. Status is one text node (`setStatus` writes `textContent` — smoke reads it; keep it a single node). Triple-tap opens audio diagnostics. |
| Pane strip `#paneStrip` | active tab (gold) ×3; `aria-selected` maintained | Hidden ≥1000 (panes stack). Default Practice every load. |
| Panes ×3 | active/inactive; internal scroll when content > cap | Bounded `min(46vh,420px)` / 52vh tablet / unbounded stacked desktop. |
| Voice picker | 4×`.vbtn` idle/hover/**active** (gold + ring) — or mono 2-seg Playing/Muted | Rebuilt per piece; keys 1–4. |
| Verse row † | hidden / seg with active verse | Multi-verse pieces only; key V cycles. |
| Tempo / Volume / Sync / Response sliders | value + live `<output>` in label | Gold accent; no state classes. |
| Loop | from/to number inputs + `on` checkbox | Machine-written by section jumps and worst-spot taps; key L toggles. |
| Mic `#micBtn` | off / **on** (cyan face) | Cyan = live-voice semantic; key M. |
| Headphones / Also-play-my-part | checked/unchecked | `#hearMine` is the chip's source of truth — they can never desync. |
| Record `#recBtn` | idle / **recording** (red face, pulsing dot, timer visible) / stopped (Save chip + size until next start) | Suffix `(music only)` with mic off. Key R. |
| Rec mix row † | hidden / visible while mic on | Affects recording legs only. |
| Instrument / Strictness / View segs | 2–3 segments, one active | Persisted (localStorage). View sets `body.view-*` classes. |
| Library button + overlay | closed / open (search, facet chips on/off, windowed list, collapsible groups, count live region) | Full-screen modal, Esc closes, `body.lib-lock`. |
| Section row † / sheet | row hidden/visible; prev/next disabled at ends; sheet closed/open, active item gold-tinted | Sheet is the app's calmest surface — the pattern to copy. |
| Score report `#scoreReport` | hidden / shown: totals line (`· best N%` when looping) + ≤3 spot rows or "Clean lap" / coloring chip hidden ∨ off ∨ **on** (+ legend) | Non-modal. Fixed above transport (mobile); rail card (desktop). ✕ dismisses until next Play; next Play clears. Spot tap → loop ±1 measure, park cursor, dismiss. |
| Per-note coloring (#79) | off (default per report) / on: noteheads tinted by verdict | Cleared on next Play / voice / verse / piece switch. |
| Score busy overlay | hidden / spinner + phase text | Over the score box only; `aria-live=polite`. |
| Windowed-render footer | hidden / info + Render-full / working | Inside the score box, pill. |
| Guided tour | idle / running (spotlight ring + card; Back/Next/Skip) | `pointer-events:none` except card; `body.tour-active` gates keys.js; auto-runs first visit, never under WebDriver. |
| Help `#helpBtn` | closed / menu open (Tour, Written guide) | `aria-expanded` maintained. |
| Calibrate dialog | **disabled this wave** (entry row hidden — see §6 V2) | Speaker-echo redesign needed before re-enable. |
| Audio diagnostics | hidden / open via `?audiodebug=1` or status triple-tap | Field tool; never part of the product surface. |
| Retry `#retryStart` | hidden / visible on failed startup | Adjacent to the status text it explains. |
| `#pieceSelect` | `.sr-only`, 5 built-in options | CI-only affordance. **Must survive every restructure** (§11 contract). |

---

## §6 Interaction rules during singing — the calm rules

`playState === 'playing'` is a contract. A singer mid-phrase is doing the hardest
thing the app asks; the surface's job is to be furniture.

**R1 — Nothing repositions.** No control may change position, size, or visibility
while playing. This includes indirect displacement (something else appearing in
flow). Verified mechanism today: mobile auto-collapse happens *at* Play (a
transition into the playing state, allowed), then the surface is frozen.

**R2 — Feedback is paint, not geometry.** Allowed while playing:
  * the gold cursor advancing + the score's scroll-follow (the score box is the
    only surface that may scroll, and only to follow the cursor);
  * the singscope canvas (trace, now-line, readout text/color);
  * text swaps inside fixed slots: `#posOut` digits (tabular-nums), the status
    line (single line, ellipsis, constant height), Play's `▶/⏸` label;
  * the voice chip's 🔇/🔊 glyph when the singer taps it;
  * the recording pulse/timer if a recording is running (user started it).

**R3 — New surfaces only at boundaries, and only if displacement-free.** The
mobile report strip may appear at a **lap boundary** (it lives in reserved fixed
airspace above the transport and displaces nothing). Nothing may appear over a
control. Modals (library, sheet, calibrate) are user-opened only.

**R4 — Renders are deferred.** Score re-renders triggered while playing (window
extension, coloring) queue behind `requestRender()`'s mid-playback deferral; no
OSMD re-layout under a moving cursor. (OSMD gotcha: `load()` resets zoom — resize
re-render only.)

**R5 — Focus stays put.** No programmatic focus moves during playback; keyboard
shortcuts act without stealing focus from the score region.

### Measured violations (as-built audit, 2026-07-11)

* **V1 — Desktop rail displacement at lap wrap.** `showReport()` fires on every
  loop lap wrap; on ≥1000 px the report card is a static float **above** the rail,
  so when it appears mid-loop the entire rail — including sticky Play — jumps
  **225.4 px down** (measured: `#play` top 300.0 → 525.4 px at 1400×900;
  `desktop-02-report-card.png`). Breaks R1 in the product's headline flow
  (mic + loop drilling). Fix in Phase 1 (§11): defer the desktop card to Stop;
  the status line (which the rail keeps at its top) already carries
  `Lap N: X% · best Y%` live.
* **V2 — Ghost "Calibrate timing" row.** The wizard's entry row is `hidden` in
  markup (wizard deliberately disabled after field-testing) but **renders on both
  form factors** (`mobile-03-sound-pane.png`, `desktop-01-cold-load.png`): the
  author rule `.row{display:flex}` overrides the UA `[hidden]` default, and
  `.row-calibrate` is the one hideable row without its
  `[hidden]{display:none}` escape hatch (`.row-verse`, `.row-sections`,
  `.row-recbal` all have one). A dead control on the calm surface — and it opens
  a dialog whose wizard is known-broken on speakers. One-line CSS fix, Phase 1.
* **V3 — The status line is not a live region.** v1 called `#status` "the app's
  single aria-live voice"; as-built it has no `aria-live` (and never did — the
  claim was aspirational). Everything a screen-reader user needs during practice
  (playing state, lap scores, errors) lands in this node silently. Phase 1 adds
  `aria-live="polite"` (§9).

---

## §7 Scoring results surface (#60)

As-built (v1 §4's design, shipped, plus #79 landing early):

* **Lifecycle**: report appears on lap wrap and on Stop; ✕ dismisses until the
  next Play; next Play hides it and clears any verdict coloring. With loop on, the
  totals line appends `· best N%`; the status line mirrors
  `Lap N: X% · best Y%`. Every lap also appends a practice-history entry
  (localStorage, capped 200).
* **Content**: one totals line (`Lap 3: 14 hit · 2 flat · 1 sharp · 3 missed of
  20 (70%) · best 78%`) + up to 3 worst-spot rows (measure + defect counts) or
  "Clean lap — no rough spots."
* **Worst-spot tap → drill loop**: sets loop to the ±1-measure neighborhood, parks
  the cursor, dismisses the strip; the singer is looking at Play, one tap from the
  drill. This is the loop the top-of-page placement used to break.
* **Per-note coloring (#79)**: a per-report, off-by-default "🎨 Show on score"
  chip paints the lap's noteheads by verdict (tints §3.1) with a legend; cleared by
  the next Play or any voice/verse/piece switch. The score is the canvas for
  per-note detail — the strip stays summary + navigation, by design.

Remaining scope for #60 (Phase 2, §11): a **session summary** at Stop for
multi-lap sessions — the per-lap trajectory currently visible only in the console
table / localStorage. Desktop placement inherits Phase 1's deferral (card at Stop
only); mobile keeps lap-boundary strips (R3-compliant).

---

## §8 Keyboard and pointer map

Active at all widths (`js/keys.js`); advertised via title suffixes only ≥1000 px
(re-applied on breakpoint change; MutationObserver re-suffixes rebuilt
voice/verse buttons).

| Key | Action | Guarded no-op when |
|---|---|---|
| `Space` | Play/Pause | typing in input/select/textarea/contenteditable; library or section sheet open; tour running; any ⌘/Ctrl/Alt chord; key auto-repeat |
| `←` / `→` | Prev / next section | section nav disabled (sectionless piece) + guards above |
| `V` | Cycle verse | single-verse piece |
| `M` | Toggle mic | (guards above) |
| `R` | Toggle record | (guards above) |
| `L` | Toggle loop on/off | (guards above) |
| `1–4` | Select S/A/T/B | monophonic piece (no `.vbtn`s) |
| `Esc` | Close library / sheet / tour / calibrate | owned by each overlay, not keys.js |

Pointer policy: native `title` tooltips everywhere (no tooltip component);
`:hover` affordances are color/border only — geometry never changes on hover.
Every shortcut drives the same element/exported function the touch path uses, so
disabled/hidden logic is inherited, never re-implemented.

---

## §9 Accessibility

As-built inventory (audited 2026-07-11) and the gaps, phased in §11.

**In place:**
* Live regions: `#scoreBusy`, `#scoreReport`, `#libCount`, `#tour` (`polite`);
  `#recTime`, `#audioDebug` explicitly `off`.
* State attributes maintained by JS: `aria-expanded` (handle, help),
  `aria-selected` (pane strip), `aria-pressed` (record, coloring chip),
  `aria-controls` (handle→panes, § buttons→sheet, library button→overlay).
* Dialog semantics on library / sheet / calibrate (`role=dialog`,
  `aria-modal=true`, Esc, scrim, body scroll lock); the tour is deliberately
  non-modal (`aria-modal=false`, spotlighted control stays usable).
* Hit targets §3.3; `aria-label` on icon-only controls (Stop is `title`-only —
  Phase 3 sweep); `.sr-only` keeps the CI select accessible-but-invisible.
* Live numbers are tabular; status/report text single-line stable (no reflow for
  screen magnifiers).

**Gaps (fix phase in brackets):**
1. `#status` lacks `aria-live="polite"` — §6 V3. **[P1]**
2. `role=tab` without tab keyboard semantics: pane strip and the seg pickers
   (voice-mono/verse/strictness/instrument/view) declare `role=tab`, but only the
   pane strip maintains `aria-selected`, and none implement roving
   tabindex/arrow-keys. Recommendation: pane strip gets real tab semantics
   (arrows + roving tabindex); seg pickers drop `role=tab` for
   `role=radiogroup`/`aria-checked` (they are exclusive choices, not tab panels).
   **[P3]**
3. No `:focus-visible` styling — custom buttons ride UA defaults, near-invisible
   on the dark theme; `#libSearch` swaps border-color instead of a ring. Add a
   token ring: `outline:2px solid var(--gold-soft); outline-offset:2px`. **[P3]**
4. No `prefers-reduced-motion` handling — disable tour glide, sheet slide,
   chevron spin, recording pulse (keep opacity change); spinners may stay. **[P3]**
5. Contrast: dark theme is broadly high-contrast (`--ink` ≈ 13:1, `--sub` ≈ 7:1 on
   `--bg`); verify with tooling the marginal pairs — `--sub` on `#20232c` button
   faces, `--gold-soft` on `--panel`, 10 px uppercase labels (size, not ratio, is
   the risk), cyan-on-paper if verdict tints ever move onto the score paper
   (flat `#2f7fc4` on `#fbfbf7` is the one to measure). **[P3]**
6. Emoji inside accessible names ("🎤 Mic", "⏺ Record", "𝄞 PDF") — screen readers
   announce the emoji; sweep to `aria-hidden` spans or plain labels. **[P3]**

---

## §10 As-built drift ledger (v1 → shipped)

What shipped versus what v1 drew. Everything not listed shipped as specced.

| v1 § | Drawn | Shipped | Verdict |
|---|---|---|---|
| §2 mini-row | Play ■ pos § chip | identical | ✅ as specced (B1) |
| §3 tabs-in-drawer | 3 tabs, bounded panes | identical; pane cap + tablet 52vh | ✅ as specced (B1) |
| §4 report | fixed above transport; coloring "deferred to #60 phase 2" | placement as specced; **coloring arrived early as #79** (in-strip chip + legend) | ✅ + early |
| §5 desktop | CSS **grid** `1fr 380px` | **floats** (grid couples row heights across columns; documented in the CSS fence); mini-row additionally **sticky** at rail top | ⚠ amended, better |
| §5 keyboard | Space ←→ V M R + L, 1–4 | identical, plus tour/overlay guards | ✅ as specced (B2) |
| §5 PWA | manifest + icons, no SW | identical | ✅ as specced (B2) |
| §6 onboarding | keep 3-moment coach bubbles, reword moment (b) | **replaced whole-cloth by the guided tour** (`tour.js`: spotlight + card, replayable from the ? help menu, written guide page) — bubble copy problem mooted | ⚠ superseded |
| §6 status relocation | status into handle row | identical (+ #74 triple-tap diagnostics gesture) | ✅ as specced (B1) |
| §7.1 map | 12-file change map | executed; `onboarding.js` never existed (tour.js instead) | ✅ |
| §9 deletions | tagline, footer, micNote; h1 "ChanterLab" alone | all executed | ✅ |

**Post-B additions the surface absorbed** (not in v1; all pane-placed, mini-row
untouched — the placement rules held): ? help menu (header); Volume slider
(#74 F5); Playback-sync + Voice-response sliders with field-tuned defaults;
calibrate wizard (built, then disabled — §6 V2); audio diagnostics overlay
(`?audiodebug=1`); WASM detector default; library tone/key metadata (#76/#85) and
hymn-type facet.

---

## §11 Forward plan — phases mapping to reviewable PRs

One phase = one PR to `main`, sequential (they share `style.css`/`scoring-ui.js`).
Every phase inherits the MUST-NOT-BREAK contract (below) and — per
`docs/plans/40-practice-audio/ORCHESTRATOR.md` — user-facing practice changes get
an owner/singer field check before the issue closes.

### MUST-NOT-BREAK contract (all phases; v1 §7.2, still exact)

1. `window.__training` / `window.__library` hooks keep their method shapes.
2. `#status` stays one text node `setStatus` writes via `textContent`; readiness
   is `/^Loaded:/`. (Adding attributes is safe; nesting child elements is not.)
3. `#pieceSelect` stays present, `.sr-only`, populated with the 5 built-in ids,
   actionable by Playwright `selectOption`.
4. `#play`/`#stop` remain clickable buttons driving `playState`; `#posOut` reads
   exactly `m –` after Stop.
5. Zero-unexpected-404 budget (only `omr/out/ingest/manifest.json` is
   allow-listed); no new console/page errors.
6. `--transport-h` keeps tracking `#transport` (ResizeObserver), and
   `setOverlay()` semantics are untouched.

### Phase 1 — calm-compliance fixes (S; closes the §6 violations)

Four changes, each traceable to a measured defect. No visual redesign.

1. **Defer the desktop report card during playback** (V1).
   `js/scoring-ui.js`, in `showReport(entry)` — first line, before any DOM writes:

   ```js
   // Calm rule R1 (spec §6): on desktop the card is a static float above the
   // rail — appearing mid-loop shoves Play down 225px. The rail's status line
   // already carries "Lap N: X% · best Y%" live; the card waits for Stop.
   if (playState === 'playing'
       && window.matchMedia('(min-width:1000px)').matches) return;
   ```

   `playState` is already imported from `./transport.js`. No stashing needed:
   `stop()` → `finalizeScoringOnStop()` → `scoreCurrentLap()` → `showReport()`
   shows the final lap's card at Stop; per-lap details stay in
   `sessionLaps`/practice history. Mobile behavior unchanged (R3 allows it).
2. **Hide the disabled calibrate row** (V2). `style.css`, next to the
   `.row-verse[hidden]` rule:

   ```css
   .row-calibrate[hidden]{display:none}
   ```

   And adopt the standing rule (add as a comment beside it): any element that can
   carry `hidden` while an author rule sets its `display` ships its
   `[hidden]{display:none}` escape hatch in the same change.
3. **Make the status line audible** (V3). `index.html`:
   `<span id="status" class="status" aria-live="polite">Loading…</span>`.
   `setStatus` writes `textContent`, which live regions announce; smoke's
   `/^Loaded:/` read is unaffected.
4. **Regression assertions**, `tests/smoke.mjs` (both are one-line `evaluate`s
   against the already-loaded page):
   * `getComputedStyle(document.querySelector('.row-calibrate')).display === 'none'`;
   * `document.getElementById('status').getAttribute('aria-live') === 'polite'`.

   The deferral itself needs live scored audio, which headless CI cannot produce
   — it is covered by the singer checkpoint: loop 2+ laps with mic on at ≥1000 px
   wide and confirm Play never moves; card appears on Stop.

**Acceptance**: smoke green incl. the two new assertions; the 2026-07-11 gallery
shots re-taken show no calibrate row and (desktop, simulated report) an
undisplaced rail; contract items 1–6 intact.

### Phase 2 — #60 close-out: session summary at Stop (M)

For sessions with ≥2 scored laps, the Stop-time report gains a lap-trajectory
block between the totals line and the worst spots (data already in
`sessionLaps`; render max last 5, oldest first):

```
│ Lap 5: 17 hit · 1 flat · 2 missed of 20 (85%) · best 85%   ✕ │
│ 🎨 Show on score                                             │
│   lap 1 ▹ 60%   lap 2 ▹ 70%   lap 3 ▹ 70%   lap 4 ▹ 80%     │
│   lap 5 ▹ 85% ★best                                          │
│ [ m 12   2 missed · 1 flat ]                                 │
│ [ m 7    1 missed          ]                                 │
```

Plain text rows in the existing 12 px report vocabulary — no chart, no new
colors; ★ marks the best lap. Single-lap sessions render exactly as today.
Worst spots stay those of the final lap (owner may prefer best-lap — §13 D2).
Files: `js/scoring-ui.js` (render block), `style.css` (one `.report-laps` row
style), smoke untouched. Closes #60 (the panel design absorbed here; per-note
coloring already shipped as #79).

### Phase 3 — accessibility & motion hardening (M)

§9 gaps 2–6 as one sweep: pane-strip arrow keys + roving tabindex; seg pickers
`role=tab`→`radiogroup`; `:focus-visible` gold-soft ring token;
`prefers-reduced-motion` block; tooled contrast pass on the §9-5 pairs (fix any
AA misses by nudging within the token family); emoji-in-name sweep. Pure
additive CSS/attribute work plus one keydown handler on `#paneStrip`; no layout
changes, so it can run parallel to 40-lane audio work if the collision rules are
respected (it owns `index.html`/`style.css` for its window).

**Explicit non-goals** (owner direction 2026-07: the training app is the
product): no visual rebrand, no build step, no component framework, no service
worker in these phases, no rail-width or breakpoint changes.

---

## §12 Evidence galleries and mockups

| Artifact | What it shows |
|---|---|
| `docs/design/current/*.png` (29 shots, 2026-07-04) | The pre-implementation baseline: 12-row transport, clipped Sections row, stretched-phone desktop, top-of-page report. Historical — do not re-shoot into this directory. |
| `docs/design/asbuilt-2026-07-11/*.png` (9 shots) | The shipped surface: mobile cold-load/three panes/playing/report; desktop cold-load/report-card/playing. **Note:** the report content in `mobile-06`/`desktop-02` is representative sample data injected into the real component (a scored lap needs live singing, which headless capture cannot produce); geometry and styling are real. `desktop-02` is the V1 displacement evidence. |
| `docs/design/mockup-mobile-collapsed.html`, `mockup-mobile-expanded.html`, `mockup-mobile-scoring-report.html`, `mockup-desktop.html` | v1's annotated intent mockups (self-contained, real tokens). Superseded by the implementation for geometry; still the best statement of intent-with-rationale callouts. |

Screenshot policy: built-in public pieces only (`control_satb` etc.); never the
private corpus.

---

## §13 Decision log

v1 §9 put eleven decisions to the owner; shipping wave B confirmed them. Ledger:

| # | Decision (v1) | Outcome |
|---|---|---|
| 1 | Tabs-in-drawer over settings-drawer/accordion | ✅ shipped |
| 2 | Mini-row = Play ■ pos § chip; mic excluded | ✅ shipped, held through 5 later features |
| 3 | Chip tap = one-tap mute; handle row owns expansion | ✅ shipped |
| 4 | Tab names Practice / Sound / More | ✅ shipped |
| 5 | Library lives in More (2 taps) | ✅ shipped; no piece-hopping complaints on record |
| 6 | Desktop right rail 380 px; scope stays left | ✅ shipped (floats amendment, §10) |
| 7 | Report above transport / rail card; coloring deferred | ✅ shipped; coloring early via #79 |
| 8 | Delete tagline, footer, micNote | ✅ shipped |
| 9 | h1 → "ChanterLab" alone | ✅ shipped |
| 10 | Keyboard extras L, 1–4 | ✅ shipped |
| 11 | PWA manifest-only, no SW | ✅ shipped |

**Open decisions for the owner (v2):**

* **D1 — Desktop report deferral (Phase 1-1). DECIDED 2026-07-11:** owner
  deferred to the recommendation — the card waits for Stop; the status line
  carries per-lap totals live. Alternative (rejected: permanent ~220 px dead
  rail space): always-reserved card slot.
* **D2 — Phase 2 worst spots. DECIDED 2026-07-11:** owner deferred to the
  recommendation — final lap's worst spots, with the best-lap score shown
  alongside.
* **D3 — Calibrate wizard row**: Phase 1 hides it (honoring the existing `hidden`
  intent). When the wizard's speaker-echo redesign happens, its row returns to
  Sound below the timing sliders — no spec change needed.
* **D4 — Sound-pane growth**: the timing sliders (setup-once) sit in Sound as an
  ear-adjacency exception. If Sound outgrows one pane-height on a 390×844 phone
  again, the agreed relief valve is moving Playback sync / Voice response to More
  — flagged here so it's a decision, not a drift.
