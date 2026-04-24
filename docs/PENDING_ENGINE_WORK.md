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
2. **Chroa semantics need resolved anchors, not just target degrees.** The
   engine still has `SpathiKe`/`SpathiGa` variants hard-coded to operate
   on the region's Ke or Ga regardless of drop location. Kliton and Zygos
   are also hard-coded around their current region-relative behavior. The
   desired model is "drop a symbol on an actual note, resolve the musical
   anchor, then apply that symbol's interval patch." The clicked note may
   stay fixed, or it may move to satisfy the interval rule.

This document is a plan for moving the engine to that semantic event model.

---

## Part 1 — Palette-to-engine mapping today

| Palette item | Palette payload | Engine behavior |
| --- | --- | --- |
| 24 pthora slots (3×8) | `{type:'pthora', genus, degree}` | `grid.applyPthora(moria, genus, degree)` — works **upward only** |
| Zygos | `{shading:'Zygos'}` | `Shading::Zygos` — partial; Di-style behavior only, drop moria ignored |
| Kliton | `{shading:'Kliton'}` | `Shading::Kliton` — partial; Di-style behavior only, missing Ga/Ni/effective-anchor cases |
| Spathi | `{shading:'Spathi'}` | JS maps to `SpathiGa` if drop is Ga, else `SpathiKe`; engine applies to the region's Ke/Ga (**not** the drop moria) |
| Ajem (Enharmonic) | `{shading:'Enharmonic'}` | **no-op** — JS warns, engine has no variant |
| Diesis Geniki (♯) | `{shading:'DiesisGeniki'}` | **no-op** — JS warns, engine has no variant |
| Yfesis Geniki (♭) | `{shading:'YfesisGeniki'}` | **no-op** — JS warns, engine has no variant |
| Clear | `{shading:''}` | `apply_shading(moria, None)` — clears region shading |

The JS-side translation hack for Spathi lives in
`web/ui/scale_ladder.js:_onPaletteDrop` and must be removed once the engine
unifies.

---

## Part 2 — Required engine model

The old plan treated a palette drop as "apply this symbol to this target
degree." That is too weak for the musical behavior we need. A symbol is
dropped on an actual note degree, but the clicked note is not always the
note that remains fixed. Some drops keep the clicked note where it was and
move notes around it; other drops move the clicked note so a required
interval is satisfied.

The engine should model drops as semantic events:

```rust
struct TuningEvent {
    id: EventId,
    drop_moria: i32,
    drop_degree: Degree,
    resolved_anchor_moria: i32,
    resolved_anchor_degree: Degree,
    kind: TuningEventKind,
}

enum TuningEventKind {
    PthoraReanchor(PthoraRule),
    ChroaPatch(IntervalPatch),
    GenikiModulator(ModulatorRule),
    ManualAccidental,
    IsonChange,
}
```

`drop_moria` is where the user placed the symbol. `resolved_anchor_moria`
is the pitch the engine uses as the local reference for rebuilding the
scale. These are often the same, but must not be assumed to be the same.

Do not flatten pthora/chroa effects into anonymous `CellOverride`s. Manual
accidentals, chroa patches, pthora reanchors, inferred transcription
events, and grid-wide modulators need separate provenance even when they
produce the same pitch.

### 2.1 Split region boundaries from region anchors

**Current problem:** `Region.start_moria` is both the region boundary and
the moria where `root_degree` sits. That makes true bidirectional pthora
hard, and it cannot represent a modulation where the new local Ni is at an
absolute moria that is not the region boundary.

**Proposed shape:**

```rust
pub struct Region {
    pub start_moria: i32,
    pub end_moria: i32,
    pub genus: Genus,
    pub anchor_moria: i32,
    pub anchor_degree: Degree,
    pub active_rules: Vec<EventId>,
}
```

`start_moria` / `end_moria` define the span. `anchor_moria` /
`anchor_degree` define where the interval pattern is pinned. Cell
generation walks upward and downward from the anchor through the active
genus and interval patches.

This supports:

- bidirectional pthora propagation from the drop point;
- chroas that affect notes below, above, or around the anchor;
- drops that move the clicked note before it becomes a new local anchor;
- later transcription, where an inferred event can be attached to a time
  range and replayed semantically.

### 2.2 Interval patches

Chroas should be represented as anchor-relative interval constraints, not
as one-off hard-coded mutations to a seven-element interval array.

```rust
struct IntervalPatch {
    symbol: ChroaSymbol,
    anchor_policy: AnchorPolicy,
    constraints: Vec<IntervalConstraint>,
    fixed_notes: Vec<RelativeDegree>,
}

struct IntervalConstraint {
    from: RelativeDegree,
    to: RelativeDegree,
    moria: i32,
}
```

`AnchorPolicy` resolves the clicked note into the effective anchor. Most
symbols use the clicked pitch directly. Some symbols normalize to their
usual written anchor. Some symbols intentionally move the clicked note
before the local scale is rebuilt.

The implementation does not need this exact type layout, but it does need
this separation of concerns:

1. identify the clicked pitch;
2. resolve the effective anchor;
3. apply symbol-specific interval constraints;
4. rebuild derived cells from the semantic state.

### 2.3 Chroa behavior to encode

#### Spathi

Spathi is one palette symbol. The old `SpathiKe` / `SpathiGa` split is an
implementation artifact.

General behavior: apply the local Spathi interval patch around the resolved
anchor. In common middle-of-scale cases this makes the two adjacent
intervals around the anchor become 4 moria and compensates outward so the
larger local span remains coherent.

Important non-canonical case: Spathi can be placed on Ni. In that usage it
flattens Pa above Ni so that `Ni -> Pa = 4`. That flattened Pa can then
become the landing pitch for the next modulation.

#### Zygos

Zygos normally resolves as if anchored on Di. If dropped on Vou, it should
act as if dropped on the corresponding Di.

On Di in the diatonic frame:

```text
Ni -> Pa  = 18
Pa -> Vou = 4
Vou -> Ga = 16
Ga -> Di  = 4
```

This raises Pa and Ga while keeping the surrounding frame coherent. It is
not simply an adjacent-note modifier.

#### Kliton

Kliton can be placed on Di, Ga, and Ni. It can also be used musically on a
different pitch when that pitch is functioning as the effective anchor.

Rule anchored on X:

```text
third-below -> second-below = 14
second-below -> first-below  = 12
first-below  -> X            = 4
```

So Kliton on Ni is:

```text
Di -> Ke = 14
Ke -> Zo = 12
Zo -> Ni = 4
```

This matters for modulation chains. Example: Spathi on Ni flattens the Pa
above Ni to `Ni -> Pa = 4`; the melody lands on that flattened Pa; Kliton
is then placed on that pitch, treating it as the new effective Ni. The
whole local scale has effectively modulated up by 4 moria, with Kliton
intervals below and normal `12,10` diatonic intervals ascending above the
new Ni.

#### Enharmonic / Ajem

Ajem is not only a neighbor accidental. In important cases it moves the
note it was dropped on:

- dropped on Zo: lower Zo so `Ke -> Zo = 6`, then recompute the interval
  above it;
- dropped on Vou: lower Vou so `Pa -> Vou = 6`, then recompute the
  interval above it;
- dropped on Ga or Ni: apply the corresponding local Ajem behavior around
  Vou or Zo.

The same "move the dropped note to satisfy the lower interval" behavior
also appears when a diatonic Ga pthora is dropped on Zo or Vou.

#### Soft chromatic pthora on Ke or Pa

When the Ke soft-chromatic pthora is placed on Ke, or the same pattern is
placed on Pa, the dropped note is flatted to only 8 moria above the note
below it. The note above is then recalculated from the new position.

This is another case where `drop_moria` and `resolved_anchor_moria` may
diverge, and where the clicked note may move before the scale is rebuilt.

### 2.4 Pthora bidirectional propagation

**Current** (`src/tuning/grid.rs::apply_pthora`): splits the region at the
drop moria. The right half `[M, old_region.end)` adopts the new
`(genus, root_degree)`. The left half keeps its old genus/root.

**Required behavior:** a pthora drop is a local reanchor. The containing
region should be rebuilt in both directions from the resolved anchor until
the containing region boundary is reached. Adjacent pre-existing regions
should remain intact unless the user explicitly applies a new pthora inside
them.

This requires §2.1. Without an independent `anchor_moria`, the engine
cannot express "this whole region uses the new genus, anchored at moria M"
unless M is also the region start.

Recommended first implementation:

1. Find the region R containing `drop_moria`.
2. Resolve the pthora rule to `(anchor_moria, anchor_degree, genus)`.
3. Replace R with one region spanning `[R.start_moria, R.end_moria)`,
   preserving adjacent regions.
4. Build cells by walking intervals upward and downward from
   `anchor_moria`.

This gives the intended "repaint the current section" behavior while
preserving neighboring pthora-defined sections.

### 2.5 Diesis Geniki / Yfesis Geniki

These are grid-level modulators, not region shadings.

Rule: raise or lower every occurrence of the resolved degree across the
grid. The expected magnitude is currently `+6` for Diesis Geniki and `-6`
for Yfesis Geniki.

Represent these as persistent `ModulatorRule` events, not expanded
per-cell overrides. Expanding into `CellOverride`s would make clearing a
general sharp/flat ambiguous when the user also has manual accidentals on
some of the same cells.

### 2.6 WASM / JS boundary

The JS API should pass enough information for Rust to resolve the event.
The current string-only `applyShading(moria, shading)` is not enough once
the engine needs the clicked degree, resolved anchor, and symbol-specific
behavior.

Proposed boundary shape:

```js
grid.applySymbolDrop(JSON.stringify({
  type: 'chroa',
  symbol: 'Kliton',
  dropMoria: cell.moria,
  dropDegree: cell.degree
}));
```

`applyPthora` can remain as a convenience wrapper initially, but internally
it should create the same kind of semantic event.

**Serde migration:** old JSON presets containing `"SpathiKe"` or
`"SpathiGa"` should deserialize into equivalent Spathi event/rule data.
Keep the aliases until a future storage-version migration exists.

---

## Part 3 — Test plan

### Rust unit tests

1. `region_anchor_independent_from_start` — a region can span
   `[start,end)` while its `anchor_moria` sits in the middle.
2. `cells_walk_upward_and_downward_from_anchor` — degree positions on both
   sides of an anchor follow the active genus.
3. `pthora_bidirectional` — apply HardChromatic-Pa at moria 42. Assert
   cells below and above 42 follow the new intervals.
4. `pthora_preserves_adjacent_regions` — pre-populate multiple regions;
   confirm pthora only rewrites the region containing the drop.
5. `spathi_legacy_json_roundtrip` — old SpathiKe/SpathiGa presets load as
   Spathi semantic events/rules.
6. `spathi_on_ni_flattens_pa` — dropping Spathi on Ni yields
   `Ni -> Pa = 4`.
7. `zygos_on_di_patch` — assert the Di-anchored interval sequence
   `18,4,16,4` below Di.
8. `zygos_on_vou_resolves_to_di` — dropping on Vou resolves to the
   corresponding Di anchor.
9. `kliton_on_di_ga_ni` — assert the anchored rule on all three canonical
   anchors, including `Di -> Ke = 14`, `Ke -> Zo = 12`, `Zo -> Ni = 4`
   for Ni.
10. `kliton_on_effective_new_ni` — after Spathi-on-Ni flattens Pa,
    Kliton on that flattened Pa can treat it as the new effective Ni.
11. `ajem_on_zo_moves_dropped_note` — Zo moves so `Ke -> Zo = 6`.
12. `ajem_on_vou_moves_dropped_note` — Vou moves so `Pa -> Vou = 6`.
13. `soft_chromatic_ke_on_ke_moves_drop` — Ke moves to 8 above Di and
    the note above recalculates.
14. `diesis_geniki_raises_every_occurrence` — on a 3-octave default grid,
    apply Diesis Geniki to Zo and assert every resolved Zo occurrence moves
    +6 without overwriting manual accidentals.

### Web-side smoke (manual)

1. Drop each of the 24 pthora slots on each of the 7 default degree cells.
   Verify the ladder reflects the expected intervals.
2. Drop Spathi on Ni and verify Pa above Ni is flattened to a 4-moria
   interval.
3. Drop Zygos on Di and Vou; Vou should resolve to the corresponding Di
   behavior.
4. Drop Kliton on Di, Ga, Ni, and on a pitch that is functioning as a new
   effective Ni after a Spathi modulation.
5. Drop Enharmonic/Ajem on Zo and Vou. Verify the dropped note moves to
   make the lower interval 6.
6. Drop Diesis Geniki on Zo in any octave; all Zo occurrences should be
   raised by 6 without erasing unrelated manual accidentals.
7. Repeat 6 with Yfesis Geniki, expect `-6`.

---

## Part 4 — Suggested commit ordering

Split the engine work into separate landable commits so each is reviewable:

1. **`refactor: split region boundary from anchor`** — add
   `anchor_moria` / `anchor_degree`; preserve current behavior with tests.
2. **`fix: pthora propagates bidirectionally from resolved anchor`** —
   rebuild the containing region from the anchor while preserving adjacent
   regions.
3. **`refactor: introduce semantic tuning events`** — add event/rule
   storage and provenance, still mapping current Zygos/Kliton/Spathi
   behavior through compatibility rules.
4. **`feat: encode chroa interval patches`** — implement Spathi, Zygos,
   Kliton, and Ajem through anchor-relative patches; remove the JS Spathi
   routing hack.
5. **`feat: add pthora cases that move the dropped note`** — cover Ajem on
   Zo/Vou, diatonic Ga on Zo/Vou, and soft-chromatic Ke/Pa behavior.
6. **`feat: Diesis/Yfesis Geniki grid-wide modulators`** — persistent
   modulator events with clear provenance.

Each commit should include its own unit tests from Part 3.

---

## Part 5 — Open questions for user review

1. **Fallback anchors per symbol** — default policy should be musical:
   when a symbol is placed on a non-canonical pitch, treat the clicked
   pitch as the effective anchor if the phrase is using it that way.
   Exact fallback tables still need to be written symbol by symbol.
2. **Geniki magnitude** — `+6` / `-6` moria is the current assumption for
   general sharp/flat.
3. **Event clearing UX** — clearing a visible symbol should remove the
   semantic event, not manual accidentals that happen to produce the same
   pitch.
4. **Storage migration** — support legacy SpathiKe/SpathiGa aliases until
   a formal preset storage version exists.
5. **Transcription timeline** — future recording analysis should attach
   inferred pthora/chroa events to time ranges with confidence scores, but
   this does not need to be implemented in the current engine pass.

---

## Appendix — Things explicitly NOT in this plan

- **Martyria rendering on the ladder.** Separate pass; needs its own
  design (role-degree vs. positional-degree, two-part glyph composition,
  chromatic alternation). The semantic event model should make this
  easier because the current note can be resolved against the active
  genus, anchor, and chroa/pthora context.
- **Recording transcription / replay.** Future pass. The event/provenance
  model is intentionally compatible with detecting melody plus optional
  ison, classifying likely accidentals or pthorae, and replaying either
  original pitch, snapped pitch, or snapped pitch with explicit notation.
- **Palette visual refinements** (per-column degree labels in the 3×8
  grid, alternate-form toggles, chroa row mobile collapse).
- **Mobile palette layout.** The 320px wide panel will be cramped on
  phones. Phase 7 polish item.
