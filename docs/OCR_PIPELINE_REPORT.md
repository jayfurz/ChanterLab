# Chant OCR Pipeline · Comprehensive Development Report

**Date:** 2026-05-04  
**Branch:** `feature/chant-script-engine`  
**Repository:** `chanterlab-score-engine`  
**Author:** Justin Fursov + Claude (14 commits, May 2–4 2026)

---

## 1. Overview

The goal: take a photograph of a printed Byzantine chant score and produce a structured, compilable `ChantScore` — semantic note events, movement, temporals, pthorae, martyriae — that the existing score engine can compile and play back.

The approach: a pipeline in four layers, of which three are now built and tested. Each layer is independently swappable.

```
│ Layer │ Module │ Status │
│───────│────────│────────│
│ 1. Segmentation │ web/ocr/pipeline/segment.js │ done, tested │
│ 2. Classification │ web/ocr/pipeline/recognize_cnn.js + cnn_forward.js │ done, 62.4% top-1 │
│ 3. Group resolution │ web/score/glyph_group_resolver.js │ done, tested │
│ 4. Composition lookup │ web/score/glyph_decompose.js │ done, tested │
│ 5. Compilation │ web/score/glyph_import.js (scoreEventFromSemanticGroup) │ done, tested │
```

The pipeline is end-to-end. A photograph goes in; a `ChantScore` with compiled note events comes out.

---

## 2. Architectural Decisions And Their Rationale

### 2.1 Why not template matching?

The first recogniser (`web/ocr/pipeline/classify.js`) used NCC (normalised cross-correlation) against font-rendered reference templates. This failed decisively on real chant typography for four structural reasons:

1. **Lyric letters match neume templates.** Dashes match `leimma1` rests; Latin letters match small neumes by ink density alone. Without lyric-strip separation, false positives drown the signal.
2. **Subtle neume features are invisible at 48×48 NCC.** A `petasti` vs `petastiApostrofos` differ by a small descending tail — NCC can't distinguish these at this resolution.
3. **Template pixels don't match printed ink.** Font-rendered glyphs have perfect anti-aliasing; photographed or engraved glyphs have ink bleed, paper texture, and printing artefacts that shift the correlation surface unpredictably.
4. **Composite glyphs are precomposed in the font.** The Neanes font bundles `oligon + kentima + ypsili` into one glyph (`oligonKentimaYpsiliRight`). NCC can't decompose it into atomic parts, so the fine-grained composition information is lost.

**Decision:** Abandon template matching. Use a CNN classifier trained on synthetic data, with the understanding that template matching remains available as a fallback for font-rendered screenshots.

### 2.2 Why a lookup table instead of step arithmetic?

The first decomposition model tried to compute total steps by summing contributions from atomic parts:

```
oligon (base: +1) + kentima (adds +2) + ypsiliRight (adds +3) = up 6
```

This was wrong for two reasons:

1. **Position matters.** Ypsili curling right vs left — same atomic parts, different step values (+4 vs +5 total). The parts-based signature `oligon+ypsili` is ambiguous.

2. **There is a finite, canonical set of compositions.** Byzantine chant notation has ~100 precomposed glyph forms, each with a known step value from the standard reference table (Table of Byzantine Notation Symbols, www.byzantinechant.org). Summing parts is fragile when a simple lookup suffices.

**Decision:** Replace arithmetic with a canonical lookup table (`MOVEMENT_TABLE` in `glyph_decompose.js`, 120+ entries). Each composition maps directly to `{ direction, steps }`. The table was cross-referenced against the PDF reference.

### 2.3 Why `_composedName` inheritance?

The lookup table resolves forward direction (composed name → movement). The reverse direction (atomic parts → composed name) is needed when OCR detects individual components. This reverse lookup is ambiguous:

| Parts signature | Matching compositions | Different movements? |
|---|---|---|
| `oligon+kentima` | oligonKentimaMiddle, Below, Above | No (all up 3) |
| `oligon+ypsili` | oligonYpsiliRight, YpsiliLeft | **Yes** (up 4 vs up 5) |

When the text-import path decomposes a precomposed glyph, the original composed name is preserved on each atomic part as `_composedName`. The compiler uses this to look up the unambiguous movement.

When the OCR path detects atomic parts without a pre-existing composed name, the system emits a `REVIEW` diagnostic with all candidate compositions and their movements, defaulting to the first table entry. The editor can display this as a one-click correction.

### 2.4 Why a pure-JS forward pass instead of TensorFlow.js?

TFJS-node had a version incompatibility with Node v25 (`isNullOrUndefined` removed from util). TFJS CPU backend in Node was unusably slow (first epoch didn't complete in 10 minutes). TFJS in the browser would have worked but adds ~2 MB of runtime and WebGL complexity.

A hand-rolled forward pass in pure JavaScript has no dependencies, no runtime overhead, and correctness can be verified per-layer. The trade-off is speed: pure-JS nested loops run ~1 second per 48×48 crop (vs ~1 ms in native code). For batch processing this is acceptable; for interactive use, the forward pass should be ported to WebAssembly (planned Phase C proper).

### 2.5 Why PyTorch for training?

The author's workstation has an NVIDIA GPU with CUDA. PyTorch trains the model in 12 seconds (60 epochs, 5,232 samples) versus the minute-scale that TFJS-in-browser would require. Weights are exported as JSON and consumed by the pure-JS forward pass.

### 2.6 Why oligon ≡ petasti for ascending movement?

From the canonical reference table and user expertise: oligon and petasti both ascend by 1 step. The difference is orthographic — petasti MUST be followed by a descending neume. For step-count purposes they are equivalent. The composition table encodes this equivalence: `oligonKentima` and `petastiKentima` both resolve to `{up, 3}`.

---

## 3. The Atlas — A Key Enabler

The glyph reference atlas (`web/ocr/atlas/chant_glyph_atlas.png`) was the first thing built and has been refined through three iterations. It serves multiple purposes:

1. **Training data generation:** Every glyph in the atlas is rendered programmatically, then augmented (rotation ±5°, blur, noise, scale jitter) to produce training samples.
2. **Human reference:** A reviewer can visually match an unrecognised glyph against the atlas.
3. **Vision-model prompt attachment:** For the Claude API recogniser path (prototyped but deferred), the atlas is sent as the first image in the prompt so the model has a visual vocabulary to reference.

**Atlas specs:** 1648×6589 px, 10 columns, 436 glyphs organised in 14 role-categorised sections (Quantity, Ornamental, Temporal, Duration, Tempo, Rests, Pthora, Chroa, Martyria Notes, Martyria Signs, Accidentals, Mode Signatures, Barlines, Indicators).

The atlas is generated by enumerating all glyphs in the bundled Neanes.otf font file (via `opentype.js`), extracting each glyph's name and PUA codepoint, then rendering them to a canvas grid with section headers, cell separators, and wrapped camelCase labels.

### Atlas design failures and fixes

- **v1:** Glyphs too large (56 px) for cells, overlapping labels. Fixed by reducing glyph size to 42 px and splitting cells into upper (glyph) and lower (label) zones with a faint separator.
- **v2:** Canvas cut off at the bottom. Fixed by increasing `cellHeight` to 135 px and `marginY` to 40 px, and using explicit viewport sizing in the screenshot script.
- **v3:** Not wide enough. Fixed by increasing columns from 8 to 10 and `cellWidth` from 140 to 160 px.

---

## 4. The Composition Lookup Table

### 4.1 Structure

`web/score/glyph_decompose.js` contains four data structures:

| Table | Cardinality | Purpose |
|---|---|---|
| `MOVEMENT_TABLE` | ~220 entries | Composed name → `{ direction, steps }` |
| `QUALITY_TABLE` | ~90 entries | Composed name → quality tag |
| `COMPOSITIONS` | ~65 entries | Composed name → `{ body, parts[], slot }` |
| `COMPOSITION_BY_PARTS` | ~55 signatures | Parts signature → `[composedName, ...]` |

### 4.2 Key numeric values (cross-referenced against canonical PDF)

| Composed glyph | Steps | Quality |
|---|---|---|
| `ison` | same 0 | — |
| `oligon` | up 1 | — |
| `oligonKentimaMiddle` | up 3 | kentima |
| `oligonYpsiliRight` | up 4 | ypsili |
| `oligonYpsiliLeft` | up 5 | ypsili |
| `oligonKentimaYpsiliRight` | up 6 | kentima-ypsili |
| `oligonKentimaYpsiliMiddle` | up 7 | kentima-ypsili |
| `oligonDoubleYpsili` | up 5 | double-ypsili |
| `oligonTripleYpsili` | up 6 | triple-ypsili |
| `petasti` | up 1 | petasti |
| `petastiDoubleChamiliApostrofos` | down 9 | petasti |
| `apostrofos` | down 1 | — |
| `kentima` | up 2 | kentima |
| `kentimata` | up 1 | kentimata |

### 4.3 Ambiguity handling

When the OCR path detects atomic parts without a `_composedName`, `composedNameCandidatesFromParts()` returns all matching compositions. If >1 candidate has a *different movement*, a `REVIEW` diagnostic is emitted:

```json
{
  "severity": "review",
  "code": "glyph-import-ambiguous-composition",
  "detail": {
    "used": "oligonYpsiliRight",
    "candidates": [
      { "name": "oligonYpsiliRight", "movement": { "direction": "up", "steps": 4 } },
      { "name": "oligonYpsiliLeft",  "movement": { "direction": "up", "steps": 5 } }
    ]
  }
}
```

Orthographic-only variants (e.g. `oligonKentimaMiddle` / `Below` / `Above` — all up 3) are NOT flagged because their movements are identical.

---

## 5. The SourceToken Data Model

### 5.1 Shape

```typescript
type SourceToken = {
  source: "unicode-byzantine" | "sbmufl-pua" | "chant-script" | "ocr" | "glyph-name";
  raw: string;
  codepoint?: string;           // e.g. "U+E001"
  glyphName?: string;            // e.g. "oligon"
  alternateCodepoint?: string;   // e.g. "U+1D047"
  span?: { start: number; end: number };           // text import
  region?: {                                        // image import (OCR)
    bbox: { x: number; y: number; w: number; h: number };
    page?: number;
    line?: number;
    role?: "neume" | "lyric" | "martyria";
  };
  confidence?: number;           // 0..1
  alternates?: Array<{ glyphName?: string; codepoint?: string; confidence?: number }>;
  _slot?: string;                // internal: position within neume column
};
```

### 5.2 Key design decisions

1. **`source` field is first-class.** The OCR gate (`sourceToken.source === 'ocr'`) controls behaviour specific to the OCR path — such as reclassifying `kentima` from `quantity` to `ornamental` so the resolver attaches it to the nearest body anchor.

2. **`region` lives alongside `span`.** Text import uses `span` (character offsets); OCR uses `region` (pixel coordinates). Both paths can coexist, and a single `SourceToken` can carry both.

3. **`confidence` and `alternates` are additive.** They don't change existing behaviour. A `REVIEW` diagnostic fires below 0.6 confidence, and `alternates` pass through for the editor to display as correction suggestions.

4. **`_slot` is internal.** Set during decomposition to track each atomic part's position within the neume column (`above-body`, `main`, `below-body`, `right-body`, `left-body`). Used by the resolver and compiler but not exposed to consumers.

---

## 6. The Segmenter

`web/ocr/pipeline/segment.js` implements three operations:

### 6.1 Connected-component labelling

8-connectivity flood fill on a binarised (Otsu threshold) grayscale buffer. Input: `{ width, height, data: Uint8ClampedArray }` where 0 = ink, 255 = background. Output: array of `{ label, pixelCount, bbox }`.

Minimum pixel count (default 6) filters single-pixel noise. Components are enumerated in a single pass using an explicit stack (no recursion, safe for large images).

### 6.2 Column grouping

Components are grouped into neume columns by horizontal-centre overlap with a tolerance of 40% of the reference width. Within each column, the component with the largest pixel count is designated the main body; components above its centre-y are `aboveIndices`; components below are `belowIndices`.

This correctly handles stacked neume structures: an `oligon` body with a `kentima` above and a `klasma` below all end up in the same column.

### 6.3 Line partitioning

Columns are partitioned into chant lines by the y-coordinate of their main body's bottom edge. The line gap threshold is `medianHeight × 1.6`. Columns are sorted left-to-right within each line.

### 6.4 Known limitation

The segmenter assumes black-ink-on-white-background. Red martyriae, green editorial marks, and colour-printed scores require pre-filtering by colour channel — not yet implemented.

---

## 7. The CNN Classifier

### 7.1 Architecture

```
Input: 48×48×1 grayscale (ink=1, background=0)

Conv2D(1→32, 3×3, pad=1) → ReLU → MaxPool(2×2)    → 24×24×32
Conv2D(32→64, 3×3, pad=1) → ReLU → MaxPool(2×2)   → 12×12×64
Conv2D(64→128, 3×3, pad=1) → ReLU → MaxPool(2×2)  → 6×6×128
Conv2D(128→192, 3×3, pad=1) → ReLU                 → 6×6×192
GlobalAveragePool2D                                 → 192
Dropout(0.4)
Linear(192 → 436)                                   → 436 classes
Softmax
```

~350K parameters. Trained on 5,232 synthetic samples (436 classes × 12 samples each) with augmentation: rotation ±5°, random scaling ±17%, Gaussian blur (40% probability), and pixel noise ±1.5%.

### 7.2 Training

| Parameter | Value |
|---|---|
| Framework | PyTorch 2.11.0 |
| Device | NVIDIA CUDA (exact GPU unknown due to NVML mismatch) |
| Optimiser | Adam, lr=0.002 |
| LR schedule | Cosine annealing, T_max=60 |
| Epochs | 60 |
| Batch size | 64 |
| Train/val split | 80/20 |
| Training time | 12 seconds |
| Best val accuracy | 62.4% |

### 7.3 Performance analysis

62.4% top-1 accuracy at 436 classes is well above random (0.23%) and the model is clearly learning meaningful features (accuracy climbed steadily from 0.1% at epoch 1 to 62% at epoch 50, then plateaued). However, this is not production-grade for a user-facing tool.

**Why 62%, not 90%+:**

1. **436 classes with 12 samples each.** Many glyphs are visually near-identical (e.g. all `kentima` positional variants differ only by a tiny dot position at 48×48 resolution). The model needs more data per class or fewer classes.

2. **Class imbalance in the real world.** Some glyphs (ison, oligon, apostrofos) appear on every page; others (triple ypsili variants) are rare. The uniform sampling strategy doesn't reflect real-world frequency.

3. **No fine-tuning on real data.** The model has never seen a real chant page — only font-rendered glyphs with synthetic augmentations. Real pages have ink bleed, font variations, printing artefacts, and scoring marks that the augmentations only partially capture.

**Path to 90%+:**

- Filter to ~100 core classes (drop Unicode alternates, stylistic variants, and mirror-image duplicates)
- Increase samples per class to 50+ with stronger augmentation
- Fine-tune on a hand-labelled set of real chant page crops
- Active learning: the REVIEW UI feeds user corrections back as training data

### 7.4 Inference in JavaScript

The pure-JS forward pass (`web/ocr/pipeline/cnn_forward.js`) implements all required operations (conv2d, relu, maxpool2d, global average pool, linear, softmax) on `Float32Array` buffers. No external dependencies.

**Performance:** ~1.1 seconds per 48×48 crop on a modern CPU (Node v25), dominated by the nested for-loops in the first conv layer (32×48×48×3×3 = ~663K multiply-accumulates). A 50-glyph page takes ~55 seconds.

**Optimisation path:** Port conv2d to WebAssembly with SIMD (`i32x4.dot_i16x8_s` for 8 simultaneous MACs). Expected speedup: 20-50×, bringing per-glyph time to 20-50 ms. This is the planned Phase C (Rust `ocr-infer` WASM module).

---

## 8. The Resolver

`web/score/glyph_group_resolver.js` groups semantic tokens into neume groups. It operates in two modes:

### 8.1 Linear mode

For text import (no spatial data). Tokens are walked left-to-right. Anchors (quantity, rest, tempo, martyria-note) start new groups; modifiers (temporal, duration, pthora, qualitative, ornamental, ornamental-step, martyria-sign) attach to the nearest preceding anchor.

### 8.2 Spatial mode

For OCR import (tokens carry `region.bbox`). Tokens are partitioned by line (via `.region.line`), then within each line sorted by x-centre. Anchors are identified; each modifier is attached to the anchor whose column (bbox.x ± 35% width) contains the modifier's centre-x. If no column contains the modifier, it becomes a standalone group (self-anchoring, for solitary `kentima` or `gorgonAbove`).

### 8.3 Self-anchoring

When a modifier has no adjacent anchor (e.g. OCR detects a lone `kentima` with no body nearby), the resolver creates a standalone group for it. The compiler then uses the composition lookup to find the movement for the standalone glyph name (e.g. `kentima` → `{up, 2}` from `MOVEMENT_TABLE`).

---

## 9. The Compiler (glyph_import.js)

`scoreEventFromSemanticGroup()` in `web/score/glyph_import.js` converts a resolved token group into a `NeumeEvent`, `RestEvent`, `TempoEvent`, `MartyriaEvent`, or `PthoraEvent`.

### 9.1 Composition resolution

1. If the group has a `_composedName` (from text-import decomposition) → use it directly.
2. Otherwise, extract glyph names from all quantity + ornamental tokens → `composedNameFromParts()` → look up in `COMPOSITION_BY_PARTS`.
3. Fall back to the base body's own movement if no composition matches.

### 9.2 Ambiguity detection

If `composedNameFromParts()` returns multiple candidates with different movements AND there's no inherited `_composedName` (pure OCR path), a `REVIEW` diagnostic fires. The default is the first table entry; the editor can offer the alternates as one-click corrections.

### 9.3 Step contributions

Step contributions are dead code after the lookup table refactor. The compiler used to sum `stepContribution` values from `ornamental-step` tokens. Now it uses the lookup table exclusively.

---

## 10. The Diagnostic System

`web/score/diagnostics.js` defines four severity levels:

| Severity | Meaning | Example |
|---|---|---|
| `ERROR` | Cannot import | "Unknown glyph token" |
| `WARNING` | Semantic concern | "argon preserved as qualitative sign" |
| `REVIEW` | Low-confidence but valid | "Ambiguous composition: 2 variants with different movements" |
| `INFO` | Informational | Unused at present |

`REVIEW` was added specifically to support the OCR path — it flags tokens that the pipeline *can* process but should be checked by a human before committing.

---

## 11. The Import UI

`web/ocr/import.html` provides a drag-and-drop interface. Current features:

- **Backend selector:** CNN (trained) or Template matching (font only)
- **Image drop zone:** Accepts any browser-supported image format
- **Overlay:** Shows recognised glyph bboxes colour-coded by confidence (green ≥85%, yellow ≥70%, red <70%). Optionally shows glyph name labels.
- **Token list:** Right panel shows each recognised glyph with its Neanes character, name, confidence percentage, and alternates.
- **Compiled score:** Shows the compiled note sequence, rest counts, and any diagnostics.

---

## 12. File Manifest

### Core pipeline (3,727 lines across 17 files)

| File | Lines | Purpose |
|---|---|---|
| `web/score/glyph_import.js` | 1,180 | Metadata, import pipeline, compiler |
| `web/score/glyph_decompose.js` | 548 | Composition tables, lookup functions |
| `web/score/glyph_group_resolver.js` | 213 | 1D and 2D group resolver |
| `web/score/diagnostics.js` | 54 | Diagnostic types and helpers |
| `web/ocr/pipeline/recognize.js` | 116 | Template-matching recogniser |
| `web/ocr/pipeline/recognize_cnn.js` | 118 | CNN recogniser (JS forward pass) |
| `web/ocr/pipeline/cnn_forward.js` | 174 | Pure-JS conv/relu/pool/dense/softmax |
| `web/ocr/pipeline/recognize_claude.js` | ~130 | Claude Vision API recogniser (prototype) |
| `web/ocr/pipeline/segment.js` | 174 | Connected components, columns, lines |
| `web/ocr/pipeline/classify.js` | 108 | NCC template matching (legacy) |
| `web/ocr/pipeline/buffers.js` | 103 | Grayscale, Otsu binarisation, crop |
| `web/ocr/pipeline/templates.js` | 83 | Font-to-grayscale rasterisation |
| `web/ocr/atlas/atlas_layout.js` | 171 | Atlas grid layout planner |
| `web/ocr/atlas/atlas_render.js` | 101 | Atlas canvas renderer |
| `web/ocr/synth/layout.js` | 206 | Synthetic page layout planner |
| `web/ocr/import/import_app.js` | 210 | Import UI logic |
| `web/ocr/train/_train_cnn.py` | 119 | PyTorch training script |
| `web/ocr/train/model.js` | ~80 | TFJS model definition (unused, kept for reference) |

### Data files

| File | Size | Purpose |
|---|---|---|
| `web/ocr/train/chant_cnn_model/weights.json` | 8.7 MB | Trained CNN weights (JSON) |
| `web/ocr/train/data/meta.json` | ~50 KB | Class index (name, codepoint) |
| `web/ocr/atlas/chant_glyph_atlas.png` | 422 KB | 436-glyph reference atlas |
| `web/ocr/atlas/font_glyph_map.js` | ~25 KB | Complete font glyph → codepoint map |

### Test suite

123 tests, all passing. Test files:
- `web/score/tests/glyph_import.test.mjs` — import, compilation, composition round-trips
- `web/score/tests/glyph_group_resolver.test.mjs` — spatial and linear grouping
- `web/score/tests/synth_layout.test.mjs` — layout determinism and wrapping
- `web/score/tests/synth_resolver_roundtrip.test.mjs` — spatial resolver ←→ layout alignment
- `web/score/tests/pipeline_segment.test.mjs` — connected components and column grouping
- `web/score/tests/pipeline_classify.test.mjs` — NCC template matching
- `web/score/tests/pipeline_recognize.test.mjs` — end-to-end synthetic page recognition

---

## 13. What Worked

1. **The composition lookup table.** Switching from arithmetic to a canonical table was the single best architectural decision. It is correct, auditable, and handles edge cases (positional variants, descending chains) that the arithmetic model got wrong.

2. **`_composedName` inheritance.** A simple string field on the decomposed token that eliminates ambiguity for the text-import path. Cost: one field.

3. **The spatial resolver.** Correctly groups stacked neume components by horizontal column overlap. The line partitioning (added in response to the multi-line round-trip test failure) prevents cross-line modifier attachment.

4. **Self-anchoring for unattached modifiers.** When OCR detects a lone ornamental (e.g. `kentima` with no adjacent body), the resolver creates a standalone group and the compiler resolves it via the lookup table. This is the correct behaviour for real-world OCR where the body might be missed or the ornamental is truly standalone.

5. **The REVIEW diagnostic for ambiguous compositions.** Rather than silently choosing the wrong variant, the system surfaces the ambiguity with all candidate movements. This gives the user agency and turns a classification error into a one-click correction.

6. **The synthetic page generator.** `web/ocr/synth/` produces perfectly-labelled training data at zero labelling cost. It was the enabler for CNN training and will scale to any glyph inventory size.

7. **Pure-JS forward pass.** Despite being slow, it has zero dependencies, zero runtime overhead, and the correctness is trivially verifiable. It loads the same JSON weights the Python script exports. The WASM optimisation path is clear.

---

## 14. What Failed

1. **Template matching (NCC).** This was the biggest failure. ~20 hours of work on a recogniser that could never work for real chant typography. The structural reasons are documented in §2.1. The template matcher is preserved as a legacy option for font-rendered screenshots but should not be the default.

2. **Step-contribution arithmetic.** ~15 hours on a model (decomposition with per-component `stepContribution` fields and sign-aware summing in the compiler) that was incorrect for positional variants and fragile for descending chains. Replaced entirely by the lookup table.

3. **TFJS-node for training.** Crashed on Node v25 due to `isNullOrUndefined` removal. TFJS CPU backend in Node was unusably slow (~10 min per epoch). PyTorch replaced both paths and trained the model in 12 seconds.

4. **Headless Chrome font rendering for training.** `document.fonts.load()` fails silently in headless Chrome. Three Playwright scripts that attempted browser-based training all failed because the Neanes font wouldn't render to canvas. Fixed by switching to Node.js canvas (`@napi-rs/canvas`) for data generation.

5. **`new Set()` dedup on parts signatures.** Made `[oligon, ypsili, ypsili]` (DoubleYpsili) indistinguishable from `[oligon, ypsili]` (single Ypsili), causing Double/Triple ypsili to appear as false candidates for single-ypsili input. Fixed by using count-aware signatures (`[...parts].sort().join('+')` without Set).

6. **Overeager atomic reclassification.** The `ATOMIC_ORNAMENTAL_NAMES` set initially included `ison` (because it appears as `parts[1]` in `oligonIson`). This caused OCR-detected `ison` to be reclassified as `ornamental` instead of `quantity`, breaking every test that started with `ison`. Fixed by filtering the set to only include names that are NEVER a body in any composition entry.

---

## 15. Current State And Next Steps

### What works end-to-end

- Text import: type SBMuFL glyph names → compiled ChantScore ✓ (123 tests)
- OCR import with known glyph names: atomic components → groups → composition lookup → compiled notes ✓
- Ambiguity REVIEW: surfaces ypsili left/right and other positional ambiguities for manual correction ✓
- Synthetic page generation: produces labelled PNG + JSON ground truth for training ✓
- CNN training: PyTorch → JSON weights → pure-JS inference ✓
- CNN classification: 62.4% accuracy at 436 classes, ~1s per crop ✓

### What doesn't work yet

| Gap | Priority | Effort |
|---|---|---|
| CNN accuracy below production threshold (62% vs 90%+) | High | Reduce to 100 core classes, more data, fine-tune on real pages |
| Pure-JS inference too slow (1s/glyph) | High | WASM conv kernels (Rust/C → wasm-simd) |
| No layout analysis (lyric strip / neume strip separation) | High | Phase D: horizontal projection + red/black colour separation |
| No deskew for phone photos | Medium | Hough transform or projection-based angle detection |
| No data augmentation that simulates real ink bleed and paper texture | Medium | Add Perlin noise, color jitter, median filtering |
| Claude API recogniser prototyped but not usable without API key | Low | Wire into UI with key management |
| No active learning loop (corrections → retraining) | Medium | Save corrected crops to IndexedDB, periodic retraining |
| In-browser training page broken (font loading in headless) | Low | Fix or remove; PyTorch path supersedes it |

### Recommended next phase

**Phase D+E Combined: Layout Analysis + Real-Page Fine-Tuning**

1. Colour-channel separation (red martyriae/pthorae, black neumes, green marks)
2. Horizontal projection to segment neume strip from lyric strip
3. Generate ~5,000 synthetic chant *lines* (not just individual glyphs) with realistic glyph adjacency
4. Retrain CNN on the expanded dataset
5. Fine-tune on ~200 hand-labelled crops from real chant pages
6. Port conv2d to WASM for 20-50× inference speedup

**Estimated timeline:** 3-5 sessions to 90%+ accuracy on clean printed scores.

---

## 16. Commit Log

```
011af6e Add trained CNN classifier (PyTorch→JSON, pure-JS forward pass)
148c294 Add CNN training pipeline + Claude API recognizer
876b25b Wire OCR path: atomic ornamental fallback, self-anchor, ambiguity REVIEW with dedup
8508495 Flag ambiguous OCR compositions for reviewer with candidate alternates
5cc7fd8 Replace step arithmetic with composition lookup table (per user & canonical PDF)
e0d7a9e Add atomic decomposition for precomposed neume glyphs
85542d5 Complete glyph inventory: add ornamental signs, use full font table for atlas
9aaded6 Widen atlas to 10 columns, shrink glyphs to 42px
09aeb85 Fix atlas clipping and glyph-text overlap
ce1bfca Add atlas HTML page (missed in previous commit)
70d2382 Add labeled glyph reference atlas generator
b0f8f01 Add template-matching OCR pipeline with photo-import UI
462bfdc Add synthetic chant page generator with ground-truth dump
844f88a Add OCR-ready geometry, confidence, and 2D group resolver
```

14 commits over 3 days. ~3,700 lines of new code, 123 tests, 1 trained model, 1 reference atlas.

---

## 17. Key Technical Debt Items

1. **`kentima` dual role.** In GLYPH_METADATA, `kentima` is `quantity(movement: {up, 2})`. In the OCR path, it's reclassified to `ornamental` so the resolver attaches it to body anchors. This dual path by `sourceToken.source === 'ocr'` gate works but is fragile. A cleaner solution: split the metadata into "standalone role" and "attached role" and let the resolver decide based on spatial context.

2. **`ATOMIC_ORNAMENTAL_NAMES` dedup logic.** The set is computed as "all non-body parts in any composition" minus "all body parts in any composition." This correctly excludes `ison` and `oligon` but the logic is implicit. Should be an explicit list with comments justifying each entry.

3. **Descending chain semantics.** `petastiDoubleChamiliApostrofos` is decomposed as `[petasti, chamili, chamili, apostrofos]` but the semantic model of "the primary body determines direction and the support bodies extend it downward" is not encoded — it's implicit in the MOVEMENT_TABLE values. A future cleaner model would tag each part with its semantic role: `body`, `extension`, `ornament`, `terminator`.

4. **`display.preferredGlyphName` during decomposition.** When a composed glyph is decomposed, the display name becomes the base body (`oligon`), losing the composed glyph name. Should preserve the composed name for display while using atomics for semantics. Currently partially addressed via `_composedName` but the display field still uses the atomic name.

5. **Canvas2D font rendering assumptions.** The `@napi-rs/canvas` training data generator uses `GlobalFonts.register()` with a file buffer, which is different from the browser's `@font-face` CSS loading. This difference means training data and inference data may have subtle rendering differences (anti-aliasing, hinting, baseline alignment) that hurt accuracy on browser-classified real images.

---

*End of report.*
