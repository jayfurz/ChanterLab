# ChanterLab iOS app

WKWebView UI (https://chanterlab.com) + a native audio engine that replaces WebKit's audio stack
piece by piece. Background: `docs/IOS-EVALUATION-2026-07.md` §5 (Option C).

## Milestones

1. **Rust C ABI** — done. `src/ffi.rs` (feature `ffi`): the same HPF → gate → FFT detector the web
   worklet uses, as `clp_tracker_*`. `ios/build_core.sh` cross-compiles it (works from Linux).
2. **Native mic capture** — code done, simulator-verified with a synthetic tone only.
   `Sources/NativeAudio.swift` captures with AVAudioEngine and posts pitch frames to
   `window.__chanterlabNativeAudio`; `training-prototype/scope.js` uses it instead of getUserMedia
   whenever the `chanterlabAudio` message handler exists. **Real-mic capture is untested** (the
   simulator's audio input is unavailable over SSH) — first device run is the test.
3. **Native playback + clock** — not started. Accompaniment still plays through WebAudio, so the
   two audio stacks share one AVAudioSession; whether that fights or crackles is a device question.
4. **Recording, calibration, background audio** — not started. Recording is unavailable while the
   native mic is active (there is no MediaStream to tap).

## Build

    ios/build_core.sh                      # Rust static libs -> ios/ChanterLab/Core/
    cd ios/ChanterLab && xcodegen generate # then build ChanterLab.xcodeproj

Device builds must be started from Xcode on the Mac (codesign cannot reach the keychain over SSH).

Debug-only environment switches: `CHANTERLAB_URL` (load a dev server), `CHANTERLAB_TONE=<hz>` (feed
a sine to the detector instead of the mic), `CHANTERLAB_AUTOMIC=1` (press Mic after load).
