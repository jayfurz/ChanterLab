# ChanterLab App, Repository, and Content-System Roadmap

Status: canonical roadmap, actively executing. `BASE-00` through `CAT-03`
completed 2026-07-10; `TRUST-01` schema v1 was owner-approved, implemented,
and promoted in the first ledger-bearing release
`rel-20260711T155237Z-a3fdb875e54f` on 2026-07-11. The release was built from
clean `main@9cd53e3`, validated against the private corpus, and live-smoked on
all production hostnames.

Audience: owner, implementation agents, reviewers, and operators.

This document supersedes neither `docs/choir-training-roadmap.md` nor
`docs/AGILE-RESET-2026-07.md`. Those are valuable historical records. This is
the current forward-looking roadmap for the whole choir-practice product,
Western-score ingestion system, Byzantine engine, and their operating model.

Executable plans live in [`docs/plans/`](plans/README.md).

## 1. Product Thesis

ChanterLab should become a trusted practice system in which:

1. A singer can find a piece, choose a voice, hear the other parts, loop a
   passage, sing, and receive useful pitch and timing feedback.
2. Every imported score has explicit provenance and an honest trust status.
3. A visible transcription problem can be reported at a specific measure,
   diagnosed as a parser failure class, fixed once, regression-tested, and
   safely reimported across the catalog.
4. Parser changes and catalog releases are reproducible, reviewable, atomic,
   and reversible.
5. Byzantine and Western notation eventually share one practice shell without
   weakening either musical model.

The current catalog is best described as thousands of **auto-imported scores
with strong structural validation**, not thousands of human-verified
transcriptions. Measure integrity is not transcription accuracy.

## 2. Strengths To Preserve

- Vector-first deterministic extraction for born-digital PDFs.
- Refusal of unsupported scans rather than fabricated confidence.
- The systemic fix, reimport, compare, and regress workflow.
- Direct links to original PDFs and source attribution.
- A focused singer-first interface with useful desktop and mobile layouts.
- Per-voice playback, muting, looping, verses, scoring, recording, and timing
  calibration.
- Client-side microphone processing and local recording by default.
- Evidence-driven detector choices; JavaScript remains the default until
  real-device evidence justifies changing it.
- Accepted/review separation and explicit parser warnings.
- Rust tuning/DSP tests and the growing semantic OMR regression corpus.

## 3. Status Vocabulary

These terms are not interchangeable:

- `implemented`: focused, rights-safe tests pass.
- `corpus-verified`: the private copyrighted corpus ran with zero unexpected
  skips and every output change was explained.
- `release-ready`: staged catalog diff, compatibility checks, and rollback
  proof were reviewed.
- `promoted`: the release pointer changed atomically and production smoke tests
  passed.
- `auto-imported`: a score passed machine gates but has not been fully reviewed
  by a person.
- `human-verified`: a named reviewer checked the relevant source and output.
- `known-issue`: a usable score with a documented residual problem.
- `review-required`: a score withheld from normal practice use.
- `manual-override`: a human-authored replacement is authoritative.

## 4. P0: Stabilize The Foundation

Roadmap IDs `BASE-*` and `CAT-*`.

1. Land the current chord-dot, divisi, above-staff lyric, focused-test, fixture,
   and retired-override work as reviewed commits.
2. Decide and execute the default branch and deployment model so the tested
   branch is the shipped branch.
3. Create one required CI workflow covering Rust, scoring, detector, browser,
   rights-safe OMR, and fresh-checkout behavior.
4. Add a second committed rights-safe score so CI performs a real cross-piece
   switch.
5. Make skips explicit; a skipped private corpus must never be reported as OMR
   verification.
6. Version catalog releases with release ID, parser commit, input inventory,
   manifest hash, source hashes, report summary, overrides, and tombstones.
7. Build reimports into immutable staging releases rather than the live tree.
8. Compare candidate and current releases before promotion.
9. Promote with an atomic pointer or rename and retain the previous release.
10. Prove rollback without rebuilding or re-extracting.
11. Generate corpus totals and documentation snapshots from release metadata.
12. Document and test backup/restore for source PDFs, MusicXML, reports, state,
    overrides, tombstones, manifests, and release pointers.

## 5. P0/P1: Content Trust

Roadmap IDs `TRUST-*`.

1. Replace one-dimensional integrity with a confidence vector covering measure
   consistency, voice topology, unresolved glyphs, pitches/accidentals, ties,
   beams, divisi, lyric coverage, and dropped/duplicated events.
2. Create a quality ledger keyed by immutable score and catalog release IDs.
3. Track trust status, parser version, source hash, reviewer, known issues,
   overrides, and verification evidence.
4. Surface trust and provenance in the library and current-piece metadata.
5. Expand the golden corpus by engraving feature, font family, layout, and
   known failure mode, not merely by piece count.
6. Turn every confirmed parser defect into semantic assertions for pitches,
   durations, voices, lyrics, and measures.
7. Add rights-safe synthetic PDF fixtures for ordinary CI.
8. Preserve private real-PDF regression runs for copyrighted edge cases.
9. Never re-bless hashes without semantic or visual evidence explaining the
   change.
10. Run a stratified human audit of accepted scores to estimate real accuracy.
11. Cluster the review queue by failure signature and fix the highest-impact
    systemic clusters first.
12. Record waivers explicitly; accepted-count growth alone is not success.

## 6. P1: Close The Correction Loop

Roadmap IDs `LOOP-*`.

1. Add `Report transcription issue` near the source-PDF control.
2. Capture piece, immutable score ID, release ID, parser version, measure,
   selected voice, playback position, and issue category automatically.
3. Support pitch, rhythm, missing note, extra note, voice, lyric, divisi,
   layout, and metadata reports.
4. Choose an owner-approved intake architecture: local export first or a small
   authenticated service. Do not silently introduce a backend.
5. Build a reviewer workbench showing source PDF crop, rendered MusicXML,
   confidence evidence, and report context side by side.
6. Let reviewers classify, accept, reject, correct, or link duplicate reports.
7. Maintain an audit trail for correction, override, tombstone, parser-fix, and
   release-promotion decisions.
8. Build a semantic catalog diff showing changed pieces, notes, voices, lyrics,
   warnings, trust transitions, and accepted/review movement.
9. Require explicit approval for unexplained churn or regressions.
10. Feed confirmed issues back into the golden corpus and parser backlog.

## 7. P1: Practice Experience

Roadmap IDs `PRACTICE-*`.

1. Add score-click measure looping.
2. Add count-in, metronome, tempo stepping, and automatic tempo ramping.
3. Add target-note replay and selected-part-only preview.
4. Add singer range checks and optional score transposition.
5. Make octave tolerance configurable; strict mode should detect wrong register.
6. Separate pitch accuracy, voiced coverage, entrance timing, rhythm, and
   insufficient-audio outcomes.
7. Avoid scoring detector failure as singer failure, while making missing audio
   visible.
8. Save recent pieces, favorites, preferred voice, tempo, loops, calibration,
   view mode, and practice history locally.
9. Add optional conductor-defined sections and annotations after local practice
   workflows are stable.
10. Preserve the calm surface; advanced controls stay secondary.

## 8. P1: Audio Reliability

Roadmap IDs `AUDIO-*`.

1. Keep JavaScript detection as default pending field evidence.
2. Turn stable detector accuracy, onset, cadence, and dropout metrics into test
   thresholds; keep CPU measurements informational across heterogeneous CI.
3. Test real singing, weak fundamentals, glides, low bass, noisy rooms, and
   accompaniment bleed.
4. Maintain a device matrix for iPhone/iPad Safari, Android Chrome, macOS
   Safari/Chrome, and Windows Chrome/Edge.
5. Cover audio-context suspension, background recovery, device changes,
   microphone denial, route changes, recording codecs, and interrupted playback.
6. Keep calibration results inspectable, explainable, resettable, and versioned.
7. Define performance budgets for long scores, library search, pitch analysis,
   sample voices, rendering, and memory.
8. Treat real-device field evidence as a release gate for iOS/audio changes;
   headless CI cannot certify audible quality.

## 9. P2: Production Engineering

Roadmap IDs `PROD-*`.

1. Graduate or rename `training-prototype` only after path, deployment, and
   rollback plans are approved.
2. Update the root README and architecture documents to describe the choir app
   and its relationship to the Byzantine engine.
3. Characterize transport behavior before adding features or splitting it.
4. Split the extractor gradually into ingestion, geometry recognition, event
   reconciliation, lyrics, MusicXML emission, and reporting modules.
5. Split transport responsibilities into scheduling, graph construction,
   recovery, cursor, loops, and recording integration.
6. Refactor only behind expanded semantic and browser fixtures.
7. Pin and inventory vendored dependencies such as Tone.js and OSMD.
8. Add dependency scanning, reproducible build instructions, CSP, and safe
   asset/version headers.
9. Add automated accessibility coverage plus keyboard, screen-reader, contrast,
   reduced-motion, zoom, and text-fit checks.
10. Add responsive screenshot and nonblank-canvas gates at phone and desktop
    sizes.
11. Add privacy-conscious operational telemetry for load, audio, extraction,
    release, and report failures without collecting microphone audio.
12. Build offline/PWA support only after application assets and catalog releases
    are versioned and cache invalidation is proven.

## 10. P2/P3: Product Expansion

Roadmap IDs `EXPAND-*` and `ONEAPP-*`.

1. Define a common timed-score contract shared by Western and Byzantine
   practice modes while preserving notation-specific semantics.
2. Bring Byzantine notation into the same library, transport, and practice
   shell rather than maintaining unrelated products.
3. Integrate WASM DSP or PSOLA only where measured user value exceeds added
   complexity and device risk.
4. Introduce private born-digital PDF upload first.
5. Build upload jobs with progress, immutable inputs, parser release identity,
   confidence, review state, correction, failure explanations, and deletion.
6. Keep uploads private by default; later support invited-choir access.
7. Add accounts only when uploads, cross-device state, or choir sharing require
   them.
8. Add director repertoire assignment, section rosters, deadlines, aggregate
   progress, and private notes after singer workflows are proven.
9. Keep raster/scanned OMR as an independent research track with honest
   benchmarks and no promise of vector-pipeline accuracy.
10. Pursue score-informed multipart rehearsal assessment only after
    single-singer scoring, content trust, and device reliability are stable.

## 11. Rights, Privacy, And Operations

Roadmap IDs `RIGHTS-*`.

1. Confirm written permission for the currently served Antiochian-derived
   practice catalog; do not infer permission from public availability.
2. Preserve composer, source-book, edition, and source-PDF attribution.
3. Publish licensing, privacy, recording, takedown, deletion, retention, and
   contact policies before public upload features.
4. Keep uploads private by default and define a DMCA/takedown process before
   sharing is introduced.
5. Never upload microphone audio unless the user explicitly chooses a cloud
   feature.
6. Approve analytics fields and vendors before implementation; default to
   aggregate operational signals.
7. Keep copyrighted PDFs, derived MusicXML, crops, and private screenshots out
   of the public repository and public CI artifacts.

## 12. Program Success Measures

- Every production score maps to an immutable catalog release and parser SHA.
- Every catalog promotion has an reviewed semantic diff and proven rollback.
- Required CI covers Rust, browser, scoring, detector, and rights-safe OMR.
- Private corpus verification reports exact pass and skip counts.
- Confirmed transcription reports become fixtures or explicitly documented
  exceptions.
- Human sampling produces an estimated accuracy rate by score/layout family.
- Practice success is measured by repeat use, completed loops, and reduced
  problem measures, not only library size.
- Audio changes ship with device evidence and no unexplained recovery failures.
- Rights and provenance are visible and operational, not only documented.

## 13. Recommended Execution Order

1. Land the current parser fix set.
2. Consolidate branch/deployment and make unified CI required.
3. Define immutable catalog identity and release schema.
4. Implement atomic staging, promotion, rollback, and restore drills.
5. Add the quality ledger, trust vocabulary, and golden-corpus expansion.
6. Add in-app issue reporting and the reviewer workbench.
7. Add semantic catalog diffs and correction audit trails.
8. Deepen practice/scoring while running the audio/device lane in parallel.
9. Harden architecture, dependencies, accessibility, and observability.
10. Unify notation modes, then evaluate uploads, director tools, raster OMR,
    and multipart assessment behind explicit owner gates.
