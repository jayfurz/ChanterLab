# PRACTICE-04: Scoring V2

Status: blocked on owner scoring-policy decision. Priority: P1.

Dependencies: timing contract and required detector tests. Conflicts with audio
sample contract changes.

Owned files: `scoring.js`, scoring UI, scope sample contract, scoring tests.

## Owner Decisions

Approve octave/register policy, rhythm/entrance semantics, treatment of detector
dropout, strictness presets, and how results are communicated to singers.

## Goal

Separate intonation, voiced coverage, entrance timing, rhythm/duration, register,
and insufficient-audio evidence instead of collapsing them into one hit rate.

## Steps

1. Characterize current scoring with frozen fixtures.
2. Define independent metrics and confidence/insufficient-data outcomes.
3. Add configurable octave tolerance; strict register mode does not fold octaves.
4. Compare voiced time with note clock duration without blaming known detector
   dropout.
5. Add entrance and release timing with calibrated latency.
6. Update per-note coloring and reports without shame-oriented language.

## Acceptance

Old relaxed mode remains reproducible or has an explicit migration; synthetic
cases cover late/early, wrong octave, brief pitch, silence, dropout, glides, and
short notes; metrics explain themselves; field singers validate usefulness.

