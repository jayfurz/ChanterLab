# Cross-Cutting Acceptance Gates

Status: required reference for all orchestrators.

## Gate Levels

- **Implemented:** focused rights-safe tests pass.
- **Corpus verified:** private corpus ran with no unexpected skips and every
  changed output was reviewed or waived.
- **Release ready:** staged semantic diff, compatibility, manifest validation,
  and rollback proof were approved.
- **Promoted:** atomic switch completed and production smoke passed.

Agents must report the achieved level exactly.

## Code Gate

- `git diff --check` passes.
- Focused tests cover new behavior and failure guards.
- Existing Rust, scoring, detector, browser, and rights-safe OMR suites pass as
  relevant to the owned files.
- Generated/private files are absent from `git status` and staged content.
- Each commit is coherent and includes its tests.

## OMR Gate

- Always-run unit and synthetic fixtures cover notes, chords/dots, durations,
  accidentals, ties, beams, shared staves, divisi, lyrics, and refusal paths.
- Private tests report exact pass and skip counts; any missing private fixture
  means corpus verification was not achieved.
- Parser changes record old/new code SHA, release ID, changed-piece list,
  accepted/review movement, warning/confidence distributions, and overrides.
- New accepted-to-review transitions, voice collapses, integrity decreases, or
  unexplained bytes require review.
- Changed branches are checked at named measures against source PDF and rendered
  output.
- Re-blessing requires semantic assertions or visual evidence.

## Catalog Release Gate

Every immutable candidate contains:

- Release ID and parser git SHA.
- Catalog input and source inventory hashes.
- Manifest, state, report summary, overrides, and tombstone hashes.
- Status/count/confidence summary and semantic diff from current.
- Validation that every manifest MusicXML exists, parses, and matches a report.
- Test evidence and approved waivers.

Promotion is an atomic pointer/rename, never an in-place partial rewrite. The
previous release remains intact. Rollback must be demonstrated by switching
back without extraction and verifying previous manifest/MusicXML hashes.

## Frontend Gate

- Fresh-checkout CI loads and switches between two committed rights-safe scores.
- Playwright covers 360/390px phone and approximately 1400x900 desktop.
- No unexpected console, page, or network errors.
- Score and scope canvases have nonblank pixel checks.
- Relevant flows cover library search, voice switch, play/stop, loop, verses,
  sections, scoring report, keyboard, mic denial, and audio recovery.
- Text fits, controls remain reachable, and no incoherent overlap appears.

## Audio Gate

- Fake-mic browser verification remains the deterministic CI gate.
- Stable accuracy, cadence, onset, and dropout metrics have thresholds; CPU is
  informational unless measured on a controlled runner.
- Audio changes include a real-device matrix. Headless CI cannot certify iOS
  backgrounding, routes, audible glitches, or codecs.

## Rights And Privacy Gate

- No copyrighted source or derived private artifact enters the public repo or
  public CI artifacts.
- Provenance survives release generation.
- New collection/storage has approved purpose, fields, retention, deletion,
  access, and incident behavior.
- Microphone audio remains local unless a user explicitly selects a cloud
  feature governed by an approved policy.

