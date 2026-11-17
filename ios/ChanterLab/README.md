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

## Sampled voices and recording

- **Voices**: `Resources/Voices/ah_040…080.m4a` are the web app's generated
  "ah" recordings (one every four semitones), re-encoded from Opus to AAC
  because iOS does not decode Ogg. They are decoded once at launch into a
  sample bank the Rust synth plays, repitched, for scheduled notes.
- **Recording** (`Sources/Audio/Recorder.swift`): the render and capture
  callbacks push into two lock-free rings; a writer queue mixes them at the
  chosen balance and encodes AAC. The audio graph is untouched, so recording
  cannot disturb playback or capture. The accompaniment is delayed by the
  output + input latency so the voice lines up with what the singer heard.
  The file is shared with the system share sheet.

## iPad

Universal app. Wide layouts get larger staves, a taller and faster lane, a
wider ladder and full voice names.

## Notation

`Sources/Notation` engraves the score natively from the engraving data the Rust
parser emits (clefs, key and time signatures, note values, stems, beams, dots,
accidentals, ties, rests, lyrics), using Bravura (SIL OFL, `Resources/Fonts`).
Measures are broken into lines to fit the screen; every staff shares one x per
rhythmic position. Not drawn: slurs, dynamics, text directions and section
headings, repeats; chords with seconds are not offset.

## Not ported yet

- Section check (whole-choir analysis)
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
| `CHANTERLAB_AUTOPLAY=1`, `CHANTERLAB_LOOP=1`, `CHANTERLAB_RECORD=<s>` | Practice: play the first piece (looping two measures), mic on, record for that many seconds |

With `simctl launch`, prefix each with `SIMCTL_CHILD_`. Stored settings can be
overridden with launch arguments, e.g. `-practice.view score -practice.piece <id>`.

## Verified so far

Simulator only, with synthetic tones: a 196 Hz tone reads Di on the diatonic
ladder; in Practice a 440 Hz tone over a looped passage of A4s scores 100 % with
the bars turning green. Real microphone capture, audible output, the echo
canceller and latency values have not been checked on a device.
