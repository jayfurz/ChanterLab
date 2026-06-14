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
