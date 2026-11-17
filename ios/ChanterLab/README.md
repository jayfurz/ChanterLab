# ChanterLab for iOS

A native SwiftUI app. Tuning, pitch detection, synthesis, MusicXML parsing and
lap scoring are the Rust core (`chanterlab-core`, feature `ffi`) behind a C ABI,
so the app and the web build compute the same things from the same code or from
ports checked against it.

## What is native

| Screen | Contents |
|---|---|
| **Scales** | Ladder with hold-to-play keys, sung-pitch scope, Byzantine presets (incl. 12/24-ET) and Hindustani presets, key editing (accidentals, enable/disable, pthora, chroa), exercises, drone, metronome, reference pitch, voicings |
| **Practice** | Catalog (same manifest as the web app, cached), part playback, loop / sections, tempo, transpose, verses, engraved score that follows playback and takes the scoring colours, scrolling note lane with lyrics and sung trace, lap scoring with worst measures |

One `AVAudioEngine` (`Sources/Audio/AudioEngine.swift`) owns playback and
capture. With the mic on and no headphones it runs Apple's echo canceller so
the accompaniment stays out of the pitch tracker; with headphones it takes the
raw mic. The echo canceller follows route changes.

## Notation

`Sources/Notation` engraves the score natively from the engraving data the Rust
parser emits (clefs, key and time signatures, note values, stems, beams, dots,
accidentals, ties, rests, lyrics), using Bravura (SIL OFL, `Resources/Fonts`).
Measures are broken into lines to fit the screen; every staff shares one x per
rhythmic position. Not drawn: slurs, dynamics, text directions and section
headings, repeats; chords with seconds are not offset.

## Not ported yet

- Sampled "ah" voices for accompaniment (synth only)
- Recording and export, section check (whole-choir analysis)
- Scales: glyph score practice

## Build

The Rust static libraries are built on any machine with the iOS targets
(`rustup target add aarch64-apple-ios aarch64-apple-ios-sim`):

```sh
ios/build_core.sh            # → ios/ChanterLab/Core/{iphoneos,iphonesimulator}/
cd ios/ChanterLab
xcodegen generate            # → ChanterLab.xcodeproj (not committed)
open ChanterLab.xcodeproj    # run on a device from Xcode (signing needs the GUI keychain)
```

`Sources/chanterlab_core.h` mirrors `src/ffi.rs` by hand; change both together
and rerun `ios/build_core.sh`.

## Debug launch switches (DEBUG builds, environment variables)

| Variable | Effect |
|---|---|
| `CHANTERLAB_MUTE=1` | Silence output (simulator audio plays through the Mac's speakers) |
| `CHANTERLAB_TONE=<hz>` | Feed a sine to the detector instead of opening the mic (the simulator has no usable input over SSH) |
| `CHANTERLAB_TAB=practice` | Open on the Practice tab |
| `CHANTERLAB_AUTOMIC=1` | Scales: mic on at launch |
| `CHANTERLAB_PRESET=<label>`, `CHANTERLAB_EDIT=1`, `CHANTERLAB_EXERCISE=<id>` | Scales: load a scale, open edit mode, start a drill |
| `CHANTERLAB_AUTOPLAY=1`, `CHANTERLAB_LOOP=1` | Practice: play the first piece (looping two measures), mic on |

With `simctl launch`, prefix each with `SIMCTL_CHILD_`. Stored settings can be
overridden with launch arguments, e.g. `-practice.view score -practice.piece <id>`.

## Verified so far

Simulator only, with synthetic tones: a 196 Hz tone reads Di on the diatonic
ladder; in Practice a 440 Hz tone over a looped passage of A4s scores 100 % with
the bars turning green. Real microphone capture, audible output, the echo
canceller and latency values have not been checked on a device.
