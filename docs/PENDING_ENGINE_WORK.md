# Pending engine work — palette semantics & bidirectional pthora

_Date:_ 2026-04-24
_Author:_ Claude (with user review pending)
_Scope:_ captures the Rust-engine work still owed after the palette rework
landed (commit TBD). Palette glyphs and layout are already on `master`; this
doc is the blueprint for everything that needs to change underneath them.

## Executive summary

The palette now exposes six chroa/modifier items (Zygos, Kliton, Spathi,
Ajem/Enharmonic, Diesis Geniki, Yfesis Geniki) and 24 pthorae (3 genera × 8
degrees). **Only Zygos, Kliton, and the 24 pthorae actually do anything in
the engine today.** Dropping Spathi works but via a legacy routing hack.
Ajem and the two Geniki modifiers are palette-only — their drops hit a
`console.warn` and no-op.

Two separate semantic bugs/gaps are also blocking the UX:

1. **Pthorae only propagate upward.** When you drop a pthora at moria M,
   only cells ≥ M adopt the new genus/root. In Byzantine practice the
   pivot is a re-anchor in *both* directions — cells below M are also
   re-interpreted, walking downward from the pivot until a pre-existing
   boundary or the grid edge.
2. **Spathi engine semantics don't match the palette's single glyph.** The
   engine still has `SpathiKe`/`SpathiGa` variants hard-coded to operate
   on the region's Ke or Ga regardless of drop location. The user model is
   "make the two intervals adjacent to the drop target become 4" — local,
   drop-centric, works on any degree.

This document is a plan for unifying both.

---

## Part 1 — Palette-to-engine mapping today

| Palette item | Palette payload | Engine behavior |
| --- | --- | --- |
| 24 pthora slots (3×8) | `{type:'pthora', genus, degree}` | `grid.applyPthora(moria, genus, degree)` — works **upward only** |
| Zygos | `{shading:'Zygos'}` | `Shading::Zygos`, correct |
| Kliton | `{shading:'Kliton'}` | `Shading::Kliton`, correct |
| Spathi | `{shading:'Spathi'}` | JS maps to `SpathiGa` if drop is Ga, else `SpathiKe`; engine applies to the region's Ke/Ga (**not** the drop moria) |
| Ajem (Enharmonic) | `{shading:'Enharmonic'}` | **no-op** — JS warns, engine has no variant |
| Diesis Geniki (♯) | `{shading:'DiesisGeniki'}` | **no-op** — JS warns, engine has no variant |
| Yfesis Geniki (♭) | `{shading:'YfesisGeniki'}` | **no-op** — JS warns, engine has no variant |
| Clear | `{shading:''}` | `apply_shading(moria, None)` — clears region shading |

The JS-side translation hack for Spathi lives in
`web/ui/scale_ladder.js:_onPaletteDrop` and must be removed once the engine
unifies.

---

## Part 2 — Required engine changes

### 2.1 Shading enum refactor

**Current:**

```rust
// src/tuning/shading.rs
pub enum Shading { Zygos, Kliton, SpathiKe, SpathiGa }
```

**Proposed:**

```rust
pub enum Shading {
    Zygos,
    Kliton,
    /// Local modifier: the two intervals adjacent to `target` (the drop
    /// degree) become 4 moria each. Remaining intervals recalculate from
    /// the new anchor positions so that the cells two steps away from the
    /// drop stay at their pre-shading moria.
    Spathi { target: Degree },
    /// Enharmonic / Ajem. Local modifier centered on `target`. See §2.3.
    Enharmonic { target: Degree },
    /// General sharp — raise all cells matching `target` across every
    /// octave by +6 moria. See §2.4.
    DiesisGeniki { target: Degree },
    /// General flat — lower all cells matching `target` across every
    /// octave by −6 moria.
    YfesisGeniki { target: Degree },
}
```

All variants now carry the drop target degree. `Zygos` and `Kliton` still
take no data because their current semantics depend on the region's
`root_degree` alone (they reshape the first tetrachord relative to the
region root, not the drop target) — leave those unchanged.

**Serde:** tagged representation (`{"type":"Spathi","target":"Ga"}`) is
preferred over stringly-typed to keep LocalStorage presets forward-
compatible.

**Migration:** JSON presets from the old format (`"SpathiKe"`, `"SpathiGa"`)
should map on deserialize to `Spathi { target: Ke }` / `Spathi { target:
Ga }`. Add a `#[serde(alias = ...)]` or custom Visitor.

### 2.2 `apply_spathi` — drop-centric

**Current** (`src/tuning/region.rs:104`):

```rust
fn apply_spathi(iv: &mut [i32], root: Degree, on: Degree) {
    let d = (on.index() as i32 - root.index() as i32)
        .rem_euclid(NUM_DEGREES as i32) as usize;
    if d < 2 || d + 2 > NUM_DEGREES { return; }
    // ...zero-out iv[d-1], iv[d], set to 4, recalc iv[d-2], iv[d+1]...
}
```

**Proposed:** keep the helper signature, but always pass the palette drop
target. Allow targets where the neighbor-recalc would walk off either end
of the tetrachord by clamping: if `d == 0`, only set `iv[d] = 4` (above);
if `d == NUM_DEGREES - 1`, only set `iv[d-1] = 4` (below). Anchor cells
outside the region aren't re-anchorable by this mechanism — that's
expected.

**Test matrix:** 7 tests (one per target degree), each on a diatonic
region rooted at Ni. Assert:

- The two intervals immediately adjacent to the target sum to (at most) 8.
- The second-adjacent intervals are recalculated so the second-neighbor
  cells stay at their pre-shading moria (where possible).

### 2.3 Enharmonic (Ajem) — local adjacency flattening

**User description, consolidated:**

> [Ajem] affects the notes right around where you drop them. Dropped on
> Zo: Zo→Ke becomes 6 (and Zo→Ni becomes 12; the 8-step flips to a 6).
> Dropped on Ga or Ni: raises Vou/Zo respectively by 2, so the 8-step
> below the raised note becomes 6. The Zo variant also works when dropped
> on Vou (same adjacency rule, symmetric on the descending side).

**Unified rule:** "On target degree D, shift the interval structure around
D so that the adjacency that is normally 8 moria becomes 6 and the
adjacency that is normally 10 moria becomes 12." Equivalently: raise or
lower the neighbor of D by ±2 moria so the asymmetry inverts.

**Valid drop targets (diatonic frame of reference):**

| Drop | Effect on neighbor | Resulting intervals |
| --- | --- | --- |
| Zo | raise Zo by 2 | Ke→Zo: 10→12; Zo→Ni: 8→6 |
| Vou | lower Vou by 2 (or raise Pa by 2) | Pa→Vou: 10→12; Vou→Ga: 8→6 |
| Ga | raise Vou by 2 | Pa→Vou: 10→12; Vou→Ga: 8→6 |
| Ni (either octave) | raise Zo by 2 | Ke→Zo: 10→12; Zo→Ni: 8→6 |
| Pa / Di / Ke | undefined — engine should no-op or warn |

**Implementation:**

- On `apply_shading(moria, Some(Enharmonic { target }))`, identify the
  adjacent degree whose position needs to shift (Vou or Zo depending on
  `target`) and install a `CellOverride { accidental: ±2 }` on that cell.
- Do *not* modify region intervals — this mod is entirely expressed via
  the override machinery, which already feeds into `cells()` and the
  tuning table.
- Removal: `apply_shading(moria, None)` clears the override if one was
  installed by a prior Enharmonic.

This sidesteps the region-intervals data model entirely and reuses
existing plumbing. Cleaner than adding a new kind of shading semantic.

### 2.4 Diesis Geniki / Yfesis Geniki — grid-wide accidental

**User description:**

> Modulator which causes all e's in a piece to be sharp / all b's in a
> piece to be flat.

**Rule:** Raise (`+6`) or lower (`−6`) every cell sharing the drop's
degree, across every octave in the grid.

**Implementation:**

- `apply_shading(moria, Some(DiesisGeniki { target }))` iterates over
  every cell with `cell.degree == Some(target)` and installs a
  `CellOverride { accidental: +6 }`.
- `YfesisGeniki` same with `-6`.
- These are grid-level operations, not region-level. The `shading` field
  on `Region` doesn't fit — these probably want a separate
  `grid.modulators: Vec<Modulator>` field, or a flattening pass that
  expands them into `overrides` at apply-time.

**Open question for user:** Should `+6` (♯) actually be `+6` moria, or a
different value? Byzantine "general sharp" is usually the general sharpening
modulator of 6 moria (= one enharmonic step). Confirm.

**Open question:** Is the modulator *persistent* or a one-shot? Option A:
persists on the grid state as a modulator object that can be individually
cleared. Option B: expands into per-cell accidentals on apply, no state
carried. Option A is more faithful to the notation but more state to
manage. Option B is simpler but "clearing a general flat" means finding
and clearing every cell override matching the degree — which is error-
prone if the user also set a manual accidental on one of those cells.

Recommend A with a distinct `grid.modulators` list.

### 2.5 Pthora bidirectional propagation

**Current** (`src/tuning/grid.rs::apply_pthora`): splits the region at
the drop moria. The **right** half `[M, old_region.end)` adopts the new
`(genus, root_degree)`. The left half keeps its old genus/root.

**User expected semantic:** the drop is a pivot — everything in both
directions from M adopts the new genus/root. The drop moria anchors
`root_degree` (so the cell at M is labeled as the pthora's target
degree), and intervals propagate upward *and* downward.

**Boundary behavior options:**

- **(a) Overwrite any pre-existing region.** A pthora drop replaces every
  region that overlaps with its propagation domain, up to the grid edges.
  Simplest. Destructive — prior pthorae in either direction are lost.
- **(b) Stop at the nearest pre-existing region boundary on each side.**
  The new region replaces only the region that contained M; adjacent
  regions upstream/downstream (if present) are left alone. Preserves
  intent when chaining pthorae.
- **(c) Stop at the nearest pre-existing region boundary, but also
  propagate into an adjacent region if its intervals happen to match the
  new pthora's descending pattern** (the "Pa pthora on Di: notes below
  stay where they are" case the user described on 2026-04-24).

(a) is implementable today. (b) is what a competent engine should do and
matches the mental model ("this pthora re-paints the current section").
(c) is a curiosity — under Byzantine practice the invariance the user
described is a *consequence* of the cell-moria coincidences, not a rule
enforced by the engine. (b) plus "preserve moria of cells whose moria
would end up unchanged" gives (c) for free.

**Recommend (b).** Concrete behavior:

1. Find the region R containing M.
2. Replace R with **up to three** regions:
   - left stub: `[R.start, M)` — genus is R's old genus/root (preserved).
   - new pivot: `[M, M + 72)` — new pthora's genus/root, with
     `start_moria = M` and the first interval of the rotated pattern
     anchored so the cell at M is the pthora's target degree.
   - right stub: `[M + 72, R.end)` — genus is R's old genus/root
     (preserved).
3. The pivot's descending side is computed by walking the rotated
   interval pattern **backwards** from M. Add a fourth region if needed
   for the span immediately below M down to R.start.

Hmm, re-reading (2) I realize it's actually a **four-way split**: left
of `M-72` → R's old genus, `[M-72, M)` → new genus descending, `[M, M+72)`
→ new genus ascending, right → R's old genus. That's getting messy.

**Simpler equivalent:** new region spans the **whole** of R, rooted such
that `target_degree` sits at moria M. Left stub + right stub of R are
gone (they adopt the new genus). Adjacent regions beyond R stay. This is
option (b') — between (a) and (b). Probably the right call.

**Either way this is a non-trivial refactor** to `apply_pthora` — worth
its own commit with substantial test coverage.

---

## Part 3 — Test plan

### Rust unit tests

1. `spathi_on_each_degree` — 7 cases, one per target in Ni..Zo, asserting
   the adjacent-4 rule.
2. `spathi_legacy_json_roundtrip` — old SpathiKe/SpathiGa presets load as
   the new `Spathi { target: Ke|Ga }`.
3. `enharmonic_on_zo` — dropping Enharmonic on Zo installs `+2` override,
   `Ke→Zo` interval resolves to 12, `Zo→Ni` to 6.
4. `enharmonic_on_vou` — dropping Enharmonic on Vou installs `-2`
   override on Vou, check interval rearrangement.
5. `enharmonic_on_ga` — dropping Enharmonic on Ga raises Vou by 2.
6. `enharmonic_on_unsupported_degree` — dropping on Pa/Di/Ke returns
   `false` and doesn't mutate state.
7. `diesis_geniki_raises_every_occurrence` — on a 3-octave default grid,
   apply `DiesisGeniki { target: Zo }`, assert every Zo cell moves +6.
8. `pthora_bidirectional` — apply HardChromatic-Pa at moria 42. Assert
   cells at moria 30, 18, 6, 72, 84 all follow the new intervals (not
   just ≥42).
9. `pthora_preserves_adjacent_regions` — pre-populate two regions;
   confirm pthora only affects the region containing the drop moria.

### Web-side smoke (manual)

1. Drop each of the 24 pthora slots on each of the 7 default degree cells.
   Verify the ladder reflects the expected intervals.
2. Drop Spathi on Ni, Pa, Vou, Ga, Di, Ke, Zo, Ni′. Each should produce a
   local adjacent-4 change (currently only Ke and Ga work).
3. Drop Enharmonic on Zo, Vou, Ga, Ni. Verify +2/-2 accidental appears
   on the corresponding cell and the Hz reflects the shift.
4. Drop Diesis Geniki on Zo in any octave — all three Zo cells (−1, 0,
   +1 octaves) should show `+6` accidental.
5. Repeat 4 with Yfesis Geniki, expect `−6`.

---

## Part 4 — Suggested commit ordering

Split the engine work into separate landable commits so each is reviewable:

1. **`fix: pthora propagates bidirectionally from drop moria`** — §2.5.
   No palette changes. Pure Rust + tests. Fixes the "only affects above"
   bug independently of everything else.
2. **`refactor: unify Spathi into one Shading variant with drop target`** —
   §2.1 (partial), §2.2. Deletes the JS translation hack in
   `scale_ladder.js`. Adds serde back-compat for SpathiKe/SpathiGa.
3. **`feat: Enharmonic (Ajem) local modifier via CellOverride`** — §2.1
   (Enharmonic variant), §2.3. Deletes its `console.warn` in JS.
4. **`feat: Diesis/Yfesis Geniki grid-wide modulators`** — §2.1 (Geniki
   variants), §2.4. Deletes the last two `console.warn`s. Introduces
   `grid.modulators` if option A is taken.

Each commit should include its own unit tests from Part 3.

---

## Part 5 — Open questions for user review

1. **Pthora propagation boundary** (§2.5) — option (b) or (b') as
   described? I'll default to (b') unless told otherwise.
2. **Geniki modulator state** (§2.4 open question 2) — persistent state
   (option A) or expand-on-apply (option B)?
3. **Geniki magnitude** (§2.4 open question 1) — is `±6` moria the right
   value for the general sharp/flat?
4. **Enharmonic on Pa/Di/Ke** (§2.3) — reject silently, or pick a
   sensible default (e.g. on Pa, raise Ni by 2)?
5. **SpathiKe/SpathiGa serde aliases** (§2.1) — support indefinitely, or
   mark deprecated and drop in a future major rev?

---

## Appendix — Things explicitly NOT in this plan

- **Martyria rendering on the ladder.** Separate pass; needs its own
  design (role-degree vs. positional-degree, two-part glyph composition,
  chromatic alternation). Tracked in §6 of the field report.
- **Palette visual refinements** (per-column degree labels in the 3×8
  grid, alternate-form toggles, chroa row mobile collapse).
- **Mobile palette layout.** The 320px wide panel will be cramped on
  phones. Phase 7 polish item.
