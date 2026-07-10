# ONEAPP-03: Evidence-Gated WASM DSP And PSOLA Integration

Status: deferred pending field evidence. Priority: P3.

Dependencies: audio benchmarks/device matrix and common practice shell.

Owned files: Rust/worklet adapter, audio graph, benchmark/field tests.

## Goal

Use shared Rust/WASM detection or PSOLA only if it produces a measured user or
device benefit over the current JavaScript practice path.

## Decision Gate

Compare clean/real singing accuracy, onset, glide tracking, low voice, dropout,
CPU/battery, iOS lifecycle, memory, audible artifacts, and implementation risk.
Approve separate detector and PSOLA decisions; neither implies the other.

## Acceptance

Default changes only with documented superiority on the target problem; fallback
remains available; worklet lifecycle/recovery is tested; PSOLA never becomes an
unannounced audible monitor; latency/calibration contracts remain consistent.

