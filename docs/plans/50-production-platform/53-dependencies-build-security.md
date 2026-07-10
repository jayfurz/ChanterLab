# PROD-03: Dependencies, Reproducible Build, And Security

Status: ready for inventory after `BASE-02`. Priority: P2.

Dependencies: canonical branch/workflows. Parallel-safe with OMR trust work.

Owned files: dependency inventories/locks, build workflows, headers/config,
security tests.

## Goal

Know exactly what is shipped and make builds and browser security policy
repeatable without breaking static deployment or audio workers.

## Scope

Inventory/pin Tone.js, OSMD, WASM, fonts, samples, Playwright, Python/PyMuPDF,
Rust crates, and generated packages; document update procedure and licenses;
add dependency scanning; define reproducible build hashes; introduce CSP and
safe headers compatible with AudioWorklets, workers, WASM, microphone, and PDFs.

## Acceptance

Fresh build matches documented output; dependency versions/licenses are known;
updates run full gates; CSP blocks unintended script/network sources without
breaking audio/worklets; secrets/private paths are absent; vulnerability waivers
have owner, reason, and expiry.

