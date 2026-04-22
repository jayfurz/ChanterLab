.PHONY: build-main build-worklet build

build-main:
	wasm-pack build --target web --out-dir web/pkg -- --features main --no-default-features

build-worklet:
	wasm-pack build --target no-modules --out-dir web/pkg-worklet -- --features worklet --no-default-features

build: build-main build-worklet
