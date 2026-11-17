#!/usr/bin/env bash
# Cross-compile chanterlab-core's C ABI (feature `ffi`) for iPhone + simulator
# and drop the static libs where ios/ChanterLab/project.yml looks for them.
# Runs on Linux or macOS; needs `rustup target add aarch64-apple-ios aarch64-apple-ios-sim`.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for pair in aarch64-apple-ios:iphoneos aarch64-apple-ios-sim:iphonesimulator; do
  target="${pair%%:*}"; sdk="${pair##*:}"
  cargo rustc --release --lib --crate-type staticlib --features ffi --no-default-features --target "$target"
  mkdir -p "ios/ChanterLab/Core/$sdk"
  cp "target/$target/release/libchanterlab_core.a" "ios/ChanterLab/Core/$sdk/"
done
