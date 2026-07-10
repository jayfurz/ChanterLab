# Scope note: these targets cover the legacy Byzantine engine (Rust/WASM) and
# root-level JS lint only. They do NOT run the OMR Python pipeline's pytest
# suite or training-prototype's own tests/lint (see
# training-prototype/omr/tests/ and .github/workflows/training-smoke.yml).
# `make check` is not full repository validation; unifying that is BASE-02
# scope (docs/plans/00-baseline/02-unified-required-ci.md).
.PHONY: build-main build-worklet build test test-rust test-js lint lint-rust lint-js fmt clippy eslint check

build-main:
	wasm-pack build --target web --out-dir web/pkg -- --features main --no-default-features

build-worklet:
	wasm-pack build --target no-modules --out-dir web/pkg-worklet -- --features worklet --no-default-features

build: build-main build-worklet

# ── Quality gates (mirror .github/workflows/pages.yml) ──────────────────────

fmt:
	cargo fmt --check

clippy:
	cargo clippy --all-features --all-targets -- -D warnings

lint-rust: fmt clippy

# Requires `npm ci` once to install ESLint.
eslint:
	npm run lint

lint-js: eslint

lint: lint-rust lint-js

# --all-features covers the worklet FFT detector and serde tests that the
# default feature set skips.
test-rust:
	cargo test --all-features

test-js:
	npm test

test: test-rust test-js

# Everything CI runs.
check: lint test
