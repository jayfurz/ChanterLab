# Calm Surface — UI design spec (issue #73)

**Status: awaiting owner review — no production code changes until approved.**

Restructures the choir-practice app's control surface for mobile calm and adds a real
desktop mode. Absorbs the designs of **#60** (scoring results panel), **#61** (one-tap
mute), **#62** (mobile de-densify / thumb-zone grouping half), and **#72** (desktop
layout, keyboard, PWA), building on the **#58** audit. Implementation is wave B, split
across two agents (§8).

Audiences: **owner** — read §0, §2, §3, §9 and open the mockups; **implementers** —
§7–§8 are your contract, §1 is your checklist.

Evidence gallery (all states captured live on 390×844 and 1400×900, 2026-07-04):
`docs/design/current/*.png`. Mockups: `mockup-mobile-collapsed.html`,
`mockup-mobile-expanded.html`, `mockup-mobile-scoring-report.html`, `mockup-desktop.html`
(self-contained, open in any browser; they reuse the app's real color tokens).

---

## 0. The problem, in numbers (measured, not felt)

* The expanded transport is **12–14 rows** (piece-dependent). On a 390×844 phone it
  covers **100% of the score** (`mobile-02-transport-expanded.png`).
* **Discovered defect while screenshotting:** `.full` is `max-height:70vh;
  overflow:hidden` — *hidden*, not *auto*. With the Complete Liturgy loaded (verse row +
  sections row) plus mic on and a saved-recording chip, content is 658px in a 591px box:
  **67px clipped, and the Sections row — the only navigation for a 422-measure service —
  shows 9px of its 48px height and cannot be scrolled to**
  (`mobile-12-sections-row-clipped.png`, measured via getBoundingClientRect). Any control
  restructure must give the panel a bounded, scrollable interior.
* Desktop (1400×900) is a stretched phone: bottom sheet spanning 1400px, Play stretched
  to ~200px in a mostly-empty mini-row, control rows wrapping into an uneven flex soup
  occupying the bottom ~45% (`desktop-02-transport-expanded.png`).
* The post-lap report strip renders at the **top** of the page while every control that
  reacts to it (Play, loop) is at the **bottom** (`desktop-07-score-report.png`,
  `mobile-07-score-report.png` — where it is additionally half-hidden behind the
  onboarding bubble and the expanded transport).
* Two independent testers, unprompted: "as a phone app the screen is pretty busy" and
  "I wonder how it would look as a desktop program?" (#62, #72).

What already works and must keep its spirit: the **collapse-on-Play transport** (mobile
starts collapsed since #58 wave 1; playing auto-collapses to the mini-row), the
**section bottom-sheet** (`mobile-11-section-sheet.png` is the calmest surface in the
app), the library overlay, and the dark/gold identity.

---

## 1. Control inventory

Every interactive control, its module owner, and usage-frequency class.
Classes: **ES** = every-session (touched most practice sessions), **PP** = per-piece
(touched when the piece changes), **SO** = setup-once (persisted taste setting),
**R** = rare/contextual.

| # | Control | id / hook | Owner module | Class | Reasoning |
|---|---------|-----------|--------------|-------|-----------|
| 1 | Play / Pause | `#play` | transport.js | ES | The core loop; touched dozens of times per session. |
| 2 | Stop | `#stop` | transport.js | ES | Ends a lap → produces the final score; pairs with Play. |
| 3 | Position readout | `#posOut` | transport.js | ES (passive) | Orientation while playing; feeds the smoke test. |
| 4 | Voice chip | `#voiceChip` | voices.js (text) / transport.js (click) | ES | Identity of "your part" + persistent 🔇 glyph; becomes the one-tap mute (#61). |
| 5 | Expand handle | `#expandHandle` | transport.js | ES | The drawer's own control. |
| 6 | Voice picker S/A/T/B (or mono Playing/Muted seg) | `#voicePicker` | voices.js | PP | A singer picks their part once; revisited on piece switch or when coaching another part. |
| 7 | Verse picker | `#versePicker` / `#verseRow` | voices.js | PP | Only multi-verse pieces; picked when drilling the alternate text. |
| 8 | Tempo slider | `#bpm` `#bpmOut` | wired in main.js, consumed by transport.js | ES | Slow-to-learn / speed-to-perform is a core practice move. |
| 9 | Loop from/to/on | `#loopFrom` `#loopTo` `#loopOn` | wired in main.js; written by sections.js & scoring-ui.js | ES | Drilling a passage is the product's core loop; also machine-written (section jump, worst-spot tap). |
| 10 | Mic | `#micBtn` | main.js | ES | Scored practice is the headline feature. |
| 11 | Headphones mode | `#hpMode` | main.js | SO | Default on; changes only when practicing on speakers. |
| 12 | Also play my part | `#hearMine` | main.js / voices.js / transport.applyMix | ES-adjacent | Learning-stage toggle (hear it while learning, mute when confident). Becomes the checkbox twin of the chip's one-tap mute. |
| 13 | Record | `#recBtn` | recording.js | R | Content capture, not practice; explicitly "grown a row per feature" territory. |
| 14 | Recording timer | `#recTime` | recording.js | R (passive) | Visible only while recording. |
| 15 | Save recording chip | `#recSave` | recording.js | R | Appears after a recording stops. |
| 16 | Rec Voice/Music balance | `#recBalance` `#recBalRow` | recording.js | R | Only shown while mic is on; affects the recording only. |
| 17 | Rec headphones hint | `#recHint` | recording.js | R | One-time hint. |
| 18 | Scoring strictness | `#strictnessPicker` | scoring-ui.js | SO | Persisted; a taste setting, not a practice move. |
| 19 | Instrument Synth/Voices | `#instrumentPicker` | transport.js | SO | Persisted; a taste setting. |
| 20 | View Split/Score/Scope | `#viewPicker` | loader.js (setView) | SO | Persona preference; most users never leave Split. |
| 21 | Library | `#libraryBtn` | library.js | PP | Session start, then occasional browsing. |
| 22 | Current piece + attribution | `#currentPiece` `#pieceAttrib` | loader.js | PP (passive) | Orientation + licensing duty. |
| 23 | PDF link | `#pdfLink` | loader.js | R | Checking the original engraving. |
| 24 | Section prev/next | `#secPrev` `#secNext` | sections.js | ES (liturgies) | Primary navigation for long services. |
| 25 | Sections button + label | `#sectionsBtn` `#sectionsLabel` `#sectionsRow` | sections.js | ES (liturgies) | Opens the (good) bottom sheet; currently the row that gets clipped. |
| 26 | Section sheet (list, close, scrim) | `#sectionSheet*` | sections.js | ES (liturgies) | Keep as-is. |
| 27 | Score report strip (totals, spots, close) | `#scoreReport*` | scoring-ui.js | ES (with mic) | The feedback readout; currently misplaced at page top. |
| 28 | Status line | `#status` | state.js (setStatus) | ES (passive) | The app's single aria-live voice; smoke test reads it. |
| 29 | Retry | `#retryStart` | main.js / loader.js | R | Failed-startup affordance. |
| 30 | Onboarding bubble + close | `#onboardHint*` | onboarding.js | R (first run) | Three-moment coach-mark sequence. |
| 31 | Windowed-render footer + Render full | `#scoreMore` `#renderFull` | loader.js | R | Large scores only; lives inside the score box. |
| 32 | Library overlay internals (search, facets, rows, licensing) | `#libSearch` etc. | library.js | PP | Keep as-is; already calm. |
| 33 | Hidden piece select | `#pieceSelect` | main.js | never (CI only) | `.sr-only`; smoke test drives it. **Must survive untouched.** |
| 34 | Header h1 + tag + sub-paragraph | static | — | passive | Costs ~100px of phone height every session; §6/§9. |
| 35 | Footer "Prototype only…" | static `.app-foot` | — | passive | Dev pointer; deletion proposed (§9). |

---

## 2. The always-visible set (mobile)

**Mini-row (collapsed transport), left → right:**

```
[ ▶ Play (flex) ] [ ■ ] [ m 12 ] [ § ] [ 🔇 S · Soprano ]
```

| Slot | What | Why it earns the space |
|------|------|------------------------|
| ▶ Play/Pause | unchanged `#play` | Only control touched every minute of every session. |
| ■ Stop | unchanged `#stop` | Ends the lap → triggers the score report; 44px. |
| m 12 | unchanged `#posOut` | Passive orientation; shrinks to `min-width:40px`. |
| § | **new** `#sectionsMini`, shown only for multi-section pieces | Opens the existing `#sectionSheet`. Long services are the collection's backbone (Complete Liturgy = 22 sections / 422 measures) and section access is currently the control most at risk of clipping (§0). Hidden (`[hidden]`) for sectionless pieces — zero cost for the 4-measure hymn case. |
| 🔇 S · Soprano | `#voiceChip`, behavior changes | **One-tap mute (#61):** tap toggles whether *your* part is audible. Multi-voice: toggles `#hearMine`'s checked state (then `applyMix()` + `updateVoiceChip()` + status repaint) so chip and checkbox can never desync — the checkbox input remains the single source of truth. Monophonic: calls the existing `setMelodyMuted(!melodyMuted)`. The 🔇/🔊 glyph flip is the state feedback; the #58-era persistent 🔇 glyph logic in `updateVoiceChip()` already does this. |

**Defended exclusions:** Tempo and Loop are every-session but are *adjustments made
while paused* — one tap away behind the handle, on the default tab. **Mic** was the
hardest call: it is every-session and the differentiator, but a sixth mini-row item
breaks the 390px budget (measured: Play ≥110 + 44 + 40 + 44 + ~110 + 5 gaps ≈ 390px),
and the mic already has three other prompts (scope hint text, onboarding moment (c),
first row of the Sound tab). If the owner overrules, the § slot is the one to trade —
see §9-2.

What the chip tap *loses* is "open the controls" — that stays on the handle, which
becomes a full-width status+chevron row (§6), a bigger target than today's bare chevron.

---

## 3. Grouping: tabs inside the existing drawer

**Decision: three tabs — Practice / Sound / More — inside the existing expandable
transport.** Not a second drawer, not an accordion.

Rationale, grounded in the existing mechanics:

1. **The transport already is a drawer** with beloved collapse-on-Play behavior
   (`setOverlay(false)` on play; mobile starts collapsed since #58 wave 1). A separate
   settings overlay would create a third modal system beside the library overlay and the
   section sheet, and would need its own dismissal/z-index/onboarding rules. The
   existing one can carry this.
2. **Accordion fails on evidence:** unbounded vertical stacking is exactly what produced
   the 67px clip defect (§0). Tabs give each pane a bounded, predictable height; the
   worst pane (Practice, 5 rows on a liturgy) fits in ~300px.
3. **Zero new visual vocabulary:** the tab strip reuses `.seg`/`.segbtn` (already used
   for verse/strictness/instrument/view). Gold active state = current tab.

**Pane contents** (top→bottom; † = contextual row, hidden exactly as today):

| Practice (default) | Sound | More |
|---|---|---|
| Your voice (`.row-voice`) | Mic + Headphones mode (`.row-mic`) | Library + piece + PDF (`.row-piece`) |
| Verse † (`#verseRow`) | Also play my part (from `.row-mic`, sync w/ chip) | Scoring strictness (`.row-strictness`) |
| Tempo (`.row-fine` group 1) | Sound Synth/Voices (`.row-instrument`) | View (`.row-view`) |
| Loop (`.row-fine` group 2) | Record (`.row-record`) | |
| Section row † (`#sectionsRow`) | Rec mix † (`#recBalRow`) + hint † | |

* Pane container: `max-height: min(46vh, 420px); overflow-y: auto` — **fixes the clip
  defect structurally**: every row is always reachable, and ≥50% of the screen always
  shows scope/score even while expanded.
* Tab state: default **Practice** on every load (calm default; no persistence — a
  Sound-tab user is one tap away). Switching tabs does not resize the collapsed state;
  the `ResizeObserver` in `initOverlay` already keeps `--transport-h` live for the
  expanded height changes.
* Frequency logic: everything ES that isn't mini-row-worthy landed in Practice;
  Sound = "what do I hear / capture"; More = persisted taste settings + piece
  meta. Library at 2 taps (expand → More → Library) is acceptable because a session
  usually keeps one piece; if piece-hopping becomes common, promote 📚 into the tab
  strip as a 4th action-tab (explicitly *not* chosen now — §9-5).

---

## 4. Scoring results (#60)

**Mobile — the strip moves to the transport's doorstep.** `#scoreReport` becomes
`position:fixed; left:8px; right:8px; bottom:calc(var(--transport-h) + 8px)` — the same
slot the onboarding bubble uses, directly above the controls that react to it. Content
unchanged: totals line + ≤3 worst-spot rows. Lifecycle unchanged: appears on lap
wrap/Stop, ✕ dismisses until next Play, next Play clears. Two additions:

* `showReport()` hides the onboarding bubble if visible (only possible collision:
  first-run moment (b) during a first mic'd loop; a report is better onboarding than the
  bubble). Moment (c) cannot collide — a report implies the mic was used, which
  suppresses (c).
* When looping, the totals line appends the running best: `Lap 3: 14 hit … (78%) · best 82%`
  (data already in `sessionLaps`/`bestLapHitPct`).

**Worst-spot tap-to-loop flow** (unchanged machinery, now legible): tap a spot row →
`loopWorstSpot()` sets loop to the ±1-measure neighborhood, parks the cursor, dismisses
the strip → the singer is looking at the mini-row directly below → taps Play. On mobile
the strip sits ~60px from Play, closing the loop the current top-of-page placement
breaks.

**Desktop — a rail card, not an overlay.** The report renders as a card in the right
rail directly beneath the transport card (same DOM node; the ≥1000px media query lays it
into the rail grid instead of fixed positioning). It never covers the score.

**How much per-note detail to surface:** none in the strip. The strip stays summary +
navigation (totals, worst spots). The rich per-note layer of #60 — coloring the
practiced voice's noteheads on the score/scope from `lastScore().details` (hit gold,
flat/sharp/missed distinctly), which is currently computed and thrown away — is **phase
2 of #60**, after this restructure lands: the score itself is the right canvas for
per-note detail, and a strip that tried to carry it would rebuild the density this spec
removes. Console `console.table` dump stays as-is for dev.

---

## 5. Desktop mode (#72) — ≥1000px

**Two-column grid.** Left: header (one line) + singscope + score, `1fr`. Right: a
**380px rail** — the transport, re-homed. The existing 760px media block remains as the
tablet layer; the new block is `@media (min-width:1000px)`.

```
┌────────────────────────────────────────────┬──────────────────┐
│ ChanterLab · piece title                    │ [▶ Play][■][m 12]│
│ ┌────────────────────────────────────────┐ │ [ § ][ 🔇 S·Sop ]│
│ │ singscope (full column width)          │ │ status line      │
│ └────────────────────────────────────────┘ │ ── report card ──│
│ ┌────────────────────────────────────────┐ │ ── PRACTICE ─────│
│ │                                        │ │ voice/verse/     │
│ │ score (fills remaining height)         │ │ tempo/loop/sects │
│ │                                        │ │ ── SOUND ────────│
│ │                                        │ │ mic/instrument/  │
│ │                                        │ │ record           │
│ └────────────────────────────────────────┘ │ ── MORE ─────────│
└────────────────────────────────────────────┴──────────────────┘
```

* **Same DOM, second presentation.** The rail is `#transport` made `position:static`
  and grid-placed. The tab strip is hidden; all three panes display stacked with small
  caps group labels (the `.label` pattern) — desktop has the vertical room, and stacking
  means the tab JS is mobile-only sugar, not a load-bearing dependency. Rail scrolls
  (`overflow-y:auto`) if the window is short.
* **Collapse behavior on desktop:** the rail never covers the score, so auto-collapse is
  unnecessary; `.collapsed` has no effect ≥1000px (CSS ignores it; `setOverlay()` keeps
  firing harmlessly). The *spirit* — playback shows a calm surface — is preserved
  because the rail is calm by construction. `--transport-h` body padding zeroes out.
* **Singscope placement: left column, above the score.** Its time axis is horizontal —
  crushing it into a 380px rail wrecks the one visualization that makes pitch practice
  legible; and keeping it above the score keeps the now-line vertically adjacent to the
  gold cursor.
* **Score height:** `fitScoreHeight()`'s vh budgets are viewport-based and stay sane in
  a narrower column (`isNarrow()` is already container-based: `el.osmd.clientWidth <
  560`); one contained change — at ≥1000px use the `score`-mode budget (66vh) for
  `split` so the column fills — is the single loader.js touch (§7).

**Keyboard map** (new `js/keys.js`; active at all widths, advertised on desktop):

| Key | Action | Notes |
|-----|--------|-------|
| `Space` | Play/Pause (`playPause()`) | `preventDefault` (page scroll); the big three below guard against focus in `input/select/textarea/[contenteditable]` and against library/section overlays being open. |
| `←` / `→` | Previous / next section (`jumpToSection`) | No-op for sectionless pieces (matches `#secPrev/Next` disabled logic). |
| `V` | Cycle verse (`setVerse(activeVerse % maxVerse + 1)`) | No-op for single-verse pieces. |
| `M` | Toggle mic (`toggleMic`) | |
| `R` | Toggle record | |
| `L` | Toggle loop on/off (mirrors `#loopOn` change handler) | Added: loop is the drill primitive; keyboard parity is cheap. |
| `1–4` | Select S/A/T/B | Added: matches the vbtn row; no-op mono/absent parts. |
| `Esc` | Close section sheet / library | Already implemented; unchanged. |

**Hover/tooltip policy:** every icon-only or abbreviated control keeps/gains `title`
(audit: most already have one). At ≥1000px, `keys.js` appends the shortcut to the title
(`"Play/Pause (Space)"`). No custom tooltip component — native titles, zero build cost.

**PWA manifest** (`training-prototype/manifest.webmanifest` + `<link rel="manifest">`):

```json
{
  "name": "ChanterLab — Choir Practice",
  "short_name": "ChanterLab",
  "description": "Practice your choir part: follow the score, sing, get scored.",
  "start_url": "./",
  "scope": "./",
  "display": "standalone",
  "background_color": "#14151a",
  "theme_color": "#14151a",
  "icons": [
    { "src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "icons/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

Icons: committed static PNGs (no build step) — dark `#14151a` rounded square, gold
`#d4af37` treble-clef/"CL" monogram; maskable variant with 20% safe-zone padding. Plus
`<meta name="theme-color" content="#14151a">` and a 180px `apple-touch-icon` for iOS.
**No service worker in this wave** — manifest-only is installable on Chromium (windowed
"desktop program", exactly what the tester asked for) and home-screen-able on iOS;
offline remains the roadmap item. CI note: the manifest and every icon it references
must exist in the commit that links them, or the smoke test's zero-unexpected-404 budget
fails (§7).

---

## 6. Onboarding + status line

**Status line** (`#status`, the app's one aria-live region, smoke-test-read): moves into
the transport's handle row — `[ status text (flex) ] [ ⌄ ]` — so "Lap 3: 78% · best
82%", "Playing — Soprano muted", and load progress appear next to the controls that
caused them, on both form factors (on desktop the handle row is the rail's status row;
the chevron hides ≥1000px). The `busy` spinner class and `setStatus()` semantics are
untouched; it's a relocation of the same node. The header keeps only the h1 (one line).
`#retryStart` moves adjacent (same failure surface, now next to the status text it
explains).

**Onboarding** (three moments, `onboarding.js`) survives structurally — both anchors
(`el.play`, `el.voiceChip`) remain on the always-visible mini-row, and the bubble's
`bottom: calc(var(--transport-h) + 10px)` contract still holds on mobile. Changes:

* **Moment (b) copy must change** — it currently says "Pick a different part **here**"
  anchored at the chip, but the chip's tap becomes mute-toggle. New copy:
  `"Your part is muted — you sing it. Tap the chip to hear it; pick parts under ⌄."`
  (anchor unchanged).
* Desktop override: `.onboard-hint { bottom: 24px }` at ≥1000px (the rail isn't
  height-tracked); `positionHint()`'s left-clamp already handles rail-anchored elements.
* `showReport()` hides the bubble (§4).

---

## 7. Implementation map (wave B)

### 7.1 What changes where

| File | Change | Nature |
|------|--------|--------|
| `index.html` | Transport region: add `#sectionsMini` to `.mini-row`; handle row becomes status+chevron; wrap existing `.row-*` rows into three pane divs `#panePractice #paneSound #paneMore` under a `.pane-strip` of three `.segbtn`s (**move nodes, rename nothing** — every existing id keeps working, `el` map untouched for existing entries); move `#scoreReport` markup adjacent to `#transport`; delete `.sub`, `.app-foot`, `#micNote` (§9); head: manifest link + theme-color meta + apple-touch-icon. | Structural |
| `style.css` | Pane styles (`.pane`, active state, `max-height:min(46vh,420px); overflow-y:auto`); report strip fixed positioning (mobile); handle-row layout; delete `.sub`/`.app-foot`/`.mic-note` standing rules; **new fenced `@media (min-width:1000px)` block**: body grid `1fr 380px`, rail (`#transport` static), stacked panes + hidden strip, report-as-card, scope/score column, `.onboard-hint{bottom:24px}`. | Mostly pure CSS; the ≥1000px layer is CSS-only by design |
| `js/state.js` | Add `el.sectionsMini`, `el.paneStrip`, `el.panePractice/Sound/More`. | Additive |
| `js/transport.js` | `initOverlay()`: remove the chip→`setOverlay(true)` binding (moves to voices.js); add pane-strip switching (3 lines: toggle `.active` on strip buttons + panes); handle-row click target update. Collapse/auto-collapse logic **unchanged**. | Small |
| `js/voices.js` | Chip one-tap mute: multi-voice → flip `el.hearMine.checked` + fire its change path (`applyMix`, `updateVoiceChip`, status repaint); mono → `setMelodyMuted(!melodyMuted)`. | Small |
| `js/sections.js` | Wire `#sectionsMini` → open sheet; show/hide it in `updateSectionsUI()` alongside `#sectionsRow`. | Small |
| `js/scoring-ui.js` | `showReport()` hides onboarding bubble; totals line appends `· best N%` when looping. | Small |
| `js/onboarding.js` | Moment (b) copy string only. | Copy |
| `js/keys.js` | **New**: keyboard map + desktop title-suffix pass (§5). Imported+init'd from main.js. | New file |
| `js/main.js` | Import/init keys.js. Everything else (incl. all `window.__training`/`__library` hooks) untouched. | Minimal |
| `js/loader.js` | One contained change in `fitScoreHeight()`: ≥1000px, treat `split` with the 66vh budget. **No other loader edits.** | One-liner |
| `manifest.webmanifest`, `icons/*` | New static files. | New files |

Untouched: `library.js`, `recording.js`, `model.js`, `scoring.js`, `scope.js`, tests.

### 7.2 MUST NOT break — explicit contract

`tests/smoke.mjs` DOM/hook dependencies (verified by reading the test):

1. `window.__training` and `window.__library` exist with their current method shapes
   (`playState`, `parsed`, `audioContextState`, `__library.select`, …) — main.js hooks
   untouched.
2. `#status` exists and `setStatus` writes its `textContent`; readiness is
   `/^Loaded:/.test(#status.textContent)`. Relocating the node is safe; renaming/nesting
   its text into child elements is **not** (setStatus uses `textContent`, keep it a
   single text node).
3. `#pieceSelect` remains present, `.sr-only`, populated with the 5 built-in option
   values (`control`, `trisagion_v`, `cherubic_v`, `anaphora_v`, `trisagion`), and its
   `change` listener still loads pieces (Playwright `selectOption`).
4. `#play` and `#stop` remain clickable buttons driving `playState`
   `'playing'`/`'stopped'`.
5. `#posOut` textContent advances during play and reads exactly `"m –"` after Stop.
6. **Zero-unexpected-404 error budget**: the only allow-listed failing fetch is
   `omr/out/ingest/manifest.json`. Therefore `manifest.webmanifest` and every icon it
   names must be committed in the same change that links them, and no other new fetch
   may 404.
7. Console/page-error budget: no new console errors (e.g. from keys.js touching missing
   elements — guard every `el.*` access as the codebase already does).

App-internal contracts to preserve: `--transport-h` (body padding + onboarding bubble +
report strip all key off it; the `ResizeObserver` in `initOverlay` must keep observing
`#transport`); `setOverlay()` semantics (auto-collapse on play, expand on pause/stop);
view-mode body classes (`view-split|score|scope`); `el` map ids; the mono
Playing/Muted seg being built inside `#voicePicker`.

### 7.3 Two-agent split (parallel)

* **Agent B1 — mobile surface** (the structural half): index.html *body*, style.css
  base+tablet sections, transport.js, voices.js, sections.js, scoring-ui.js,
  onboarding.js, state.js. Verifies on 390×844 (re-run the §0 clip measurement — must be
  zero clip in every state — plus the full before-gallery script).
* **Agent B2 — desktop shell** (the additive half): the fenced ≥1000px style.css block
  (**append-only**), `js/keys.js` (new), index.html *head* only, manifest + icons (new
  files), the loader.js one-liner. Verifies on 1400×900 + smoke test (manifest 404
  check) + keyboard walkthrough.
* **Seam discipline:** B2 never edits inside `<body>`'s transport markup or existing CSS
  blocks; B1 never touches `<head>`, new files, or loader.js. Land B1 first; B2 rebases
  (its surfaces can't conflict if discipline holds).

### 7.4 Risks

1. **style.css shared file** — mitigated by B2's append-only fenced block; still the
   likeliest merge friction. Land sequentially.
2. **`--transport-h` feedback loop**: pane switching changes expanded height; the
   ResizeObserver updates the var; the report strip and onboarding bubble ride it.
   Test: expand each tab with the report visible; bubble/strip must never overlap the
   transport.
3. **Chip behavior change** is the only *removed* affordance (chip-tap-expand). Risk:
   muscle memory of existing testers. Mitigations: handle row is now full-width; moment
   (b) copy teaches the new tap; #58's persistent 🔇 glyph gains a live toggle meaning.
4. **Breakpoint crossing** (resize across 1000px): OSMD re-render via the existing
   debounced resize handler; verify no zoom reset (OSMD gotcha: `load()` resets zoom —
   resize path only re-renders, safe, but verify).
5. **CI 404 budget** with the new manifest/icons (§7.2-6) — the classic silent-fail.
6. **Keyboard shortcuts vs. inputs**: `Space` in `#libSearch` must type a space —
   guard on `e.target` tag + overlay-open state.
7. **`fitScoreHeight` one-liner**: gate strictly on `min-width:1000px` matchMedia so
   mobile budgets are untouched.
8. **iOS safe-area**: the relocated report strip must include
   `env(safe-area-inset-bottom)` awareness only via `--transport-h` (it already
   incorporates the padding) — don't double-count.

---

## 8. Mockups

| File | Shows |
|------|-------|
| `mockup-mobile-collapsed.html` | New mini-row (Play/■/pos/§/chip-mute), status-in-handle, playing state calm surface. |
| `mockup-mobile-expanded.html` | The drawer with Practice/Sound/More tabs (tab switching works in the mockup), bounded pane height, score still visible above. |
| `mockup-mobile-scoring-report.html` | Post-lap report strip in its new slot above the transport; worst-spot → loop flow annotated. |
| `mockup-desktop.html` | 1400px two-column: scope+score left, 380px rail right with transport card, report card, stacked groups; keyboard map legend. |

All are self-contained HTML with the app's real tokens (`#14151a` bg, `#1e2027` panel,
`#d4af37` gold, `#e7c96b` gold-soft, `#2c2f38` line, `#9aa0a6` sub, `#4dd7ff` cyan) and
numbered annotation callouts.

---

## 9. Decisions for the owner (confirm or veto)

1. **Tabs-in-drawer** (Practice/Sound/More inside the existing transport) over a
   separate settings drawer or accordion. (§3)
2. **Mini-row set**: Play, Stop, position, § sections (contextual), voice chip. **Mic is
   NOT on the mini-row** — the deliberate hard call; trade § for 🎤 if you disagree. (§2)
3. **Chip tap = one-tap mute** (#61), losing chip-tap-to-expand (handle row takes over
   expansion). (§2)
4. **Tab names**: "Practice / Sound / More" (backlog suggested "Advanced"; "More" is
   honest — nothing in it is advanced). (§3)
5. **Library lives in More** (2 taps) rather than in the tab strip or mini-row. (§3)
6. **Desktop rail on the RIGHT at 380px**; singscope stays in the left column above the
   score, not in the rail. (§5)
7. **Report strip placement**: floating above the transport on mobile, rail card on
   desktop; **per-note score coloring deferred** to #60 phase 2 (on the score itself,
   not the strip). (§4)
8. **Deletions** (outright, this wave):
   * the header sub-paragraph ("Pick your voice — it turns gold…") — redundant with
     the shipped #64 onboarding; costs ~60px above the fold every session;
   * the `.app-foot` "Prototype only — see docs/…" footer — dev pointer (belongs in the
     README); attribution duty is already met by the library's About & licensing link +
     the per-piece attribution line (#47);
   * the standing `#micNote` paragraph — its content moves into the headphones
     checkbox's `title` and the status messages `onHeadphonesToggle` already emits.
9. **"SATB prototype" tag + h1**: propose shrinking to `ChanterLab` alone (piece title
   is the real headline). Soft call — ties into #62's branding decision; veto freely.
10. **Keyboard map additions** beyond #72's list: `L` (loop toggle) and `1–4` (voice
    select). (§5)
11. **PWA scope**: manifest + icons only, `display:standalone`, dark theme-color; no
    service worker this wave. (§5)
