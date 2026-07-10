# PRACTICE-01: Characterize Transport And Add Core Drilling

Status: ready after `BASE-02`. Priority: P1.

Dependencies: required browser/audio CI. Blocks: additional transport features
and transport modularization.

Owned files: transport behavior tests first; then transport/main/index/style as
an exclusive lane.

## Goal

Lock current scheduling, loop, cursor, recovery, recording, and scoring timing,
then add score-click looping, count-in, metronome, tempo steps, and tempo ramping.

## Steps

1. Characterize current state transitions and timing contracts in tests.
2. Add measure-click selection without breaking note drill/cursor behavior.
3. Add count-in and metronome through the existing audio graph.
4. Add explicit tempo-step controls and optional per-lap ramp.
5. Keep controls secondary and stable across compact/expanded mobile transport.
6. Test loops across split measures, verses, sections, stop/restart, and recovery.

## Acceptance

Existing timing/recovery tests remain green; click-to-loop is keyboard accessible;
count-in does not score or record as singing; ramps are deterministic per lap;
layout does not shift unexpectedly; iOS background recovery remains functional.

