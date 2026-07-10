# AUDIO-01: Audio Reliability, Benchmarks, And Device Matrix

Status: ready after `BASE-02`. Priority: P1.

Dependencies: unified CI. Parallel-safe only while it avoids scoring/transport
owned files.

Owned files: detector/audio lifecycle tests, benchmark thresholds, device runbook.

## Goal

Make detector and WebAudio reliability measurable in CI and honestly gated by
real-device evidence where automation cannot substitute.

## Scope

1. Define stable accuracy, cadence, onset, dropout, and failure thresholds for
   synthetic/fake-mic tests; keep cross-runner CPU informational.
2. Add voice-like, weak fundamental, glide, low bass, noise, and bleed fixtures.
3. Test mic denial/retry, device changes, context suspension, background/page
   recovery, scheduler recreation, sample-rate changes, and recording lifecycle.
4. Maintain real-device evidence for iPhone/iPad Safari, Android Chrome, macOS,
   and Windows browsers.
5. Define budgets for pitch analysis, long-score playback, memory, recording,
   library search, and sample voices.
6. Keep JS default unless field evidence supports a WASM switch.

## Acceptance

Threshold regressions fail CI; device failures are recorded by OS/browser/model;
no release claims iOS/audible certification from headless tests; calibration is
inspectable/resettable; audio recovery does not create duplicate graphs/schedules.

