# iOS Audio Session Analysis — explaining the iPhone field results and designing the fix

**Issue:** #74 follow-up (owner's iPhone field test after commit e499b6a's mitigations).
**Status:** analysis + fix design only — no code changes in this doc. Implementation lands after the
current Calm Surface UI wave frees `transport.js` / `main.js` / `index.html` / `scope.js`.
**Scope of evidence:** WebKit source (verified line-by-line, July 2026 `main`), bugs.webkit.org,
Apple Developer Forums, W3C Audio Session spec, MDN/BCD — links in [Sources](#sources).

---

## 0. The one-page mechanism

iOS has **one** `AVAudioSession` per app, and WebKit computes its *category* and *mode* from what the
page is doing. The decision logic (verified in
[`MediaSessionManagerCocoa.mm`](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/audio/cocoa/MediaSessionManagerCocoa.mm),
`updateSessionState`) is, in priority order:

| Page state | AVAudioSession category | mode | consequences |
|---|---|---|---|
| `navigator.audioSession.type` set (Safari ≥ 16.4) | **that override wins over everything below** | — | our biggest lever |
| any capture active (`captureCount`) — *or* audio still playing while the category is already PlayAndRecord (**sticky!**) | `PlayAndRecord` | **`VideoChat`** (or `VoiceChat` if the receiver is the preferred speaker) | **call-volume domain**, 📞 route in Control Center, volume floor |
| an audible `<audio>`/`<video>` element playing | `MediaPlayback` | Default | media-volume domain, **immune to the ring/silent switch** |
| only WebAudio | `AmbientSound` | Default | **muted by the ring/silent switch** — the original "silent unless mic on" bug |

Two further facts complete the picture:

1. **`echoCancellation` selects the capture audio unit.** In
   [`CoreAudioCaptureUnit.cpp`](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/mediastream/cocoa/CoreAudioCaptureUnit.cpp):
   `m_shouldUseVPIO = enableEchoCancellation();` — EC **true** → `kAudioUnitSubType_VoiceProcessingIO`
   (Apple's telephony voice-processing unit, VPIO); EC **false** → plain `kAudioUnitSubType_RemoteIO`
   on iOS. VPIO brings AEC, its own AGC/loudness management, its own preferred sample
   rates/buffering, and **ducking of all "other audio"** (WebKit explicitly configures
   `kAUVoiceIOProperty_OtherAudioDuckingConfiguration` at the minimum ducking level — so other audio
   gets *slightly* quieter, not muted).
2. **Two render pipelines share that one session.** Plain WebAudio (our Tone.js graph) renders
   through the normal CoreAudio output unit; HTMLMediaElement audio (our silent unlock element)
   renders through the media pipeline in the GPU process. (Only remote WebRTC `MediaStreamTrack`s
   render *through* the VPIO unit — `RemoteAudioMediaStreamTrackRendererInternalUnitManager` — not
   WebAudio.) In a call-mode session the effective volume applied to each pipeline diverges: the
   session output tracks the **call volume** (which iOS floors at 1/16 — it can never reach zero,
   confirmed by Unity/Vivox), while the media pipeline stays coupled to the **media volume**. Apple's
   own forums document "three distinct volume levels" in these mixed states and concede the gain is
   "manipulated at a lower level than we really have access to."

Everything the owner observed follows from this table.

### App-side facts verified in our code (read July 2026, branch `choir-training`)

- `training-prototype/js/main.js` `toggleMic()` line ~154: `TrainingScope.setMicProcessing(!el.hpMode.checked)`.
- `training-prototype/scope.js` `micConstraints()`: `processing === true` (⇔ **hpMode OFF**, speaker
  mode) → `{ echoCancellation: true, noiseSuppression: true, autoGainControl: false }`;
  `processing === false` (⇔ **hpMode ON**, the *default* — `index.html` ships the checkbox
  `checked`) → `{ echoCancellation: false, noiseSuppression: false, autoGainControl: false }`.
- The #74 silent unlock element (`transport.js` `iosMediaUnlock`) is a looping, `volume = 1`,
  unmuted `<audio>` playing a silent WAV — to WebKit's session logic that **is** "an audible audio
  media type playing" (it never inspects samples), and it **never stops** once engaged.
- `rebuildAudioForMic` rebuilds the *graph* only — the `AudioContext` and therefore its fixed
  `sampleRate` survive. `recreateAudioContext` (new context) exists but is owner-triggered only.
- Playback chain: per-part `Gain(0.25)` → `Limiter(-1 dBFS)` → destination. There is **no master
  volume control** anywhere in the app.

---

## 1. The four field observations, each explained

### Obs 1 — "Sound now plays without the mic" ✅ explained

Before e499b6a, with the mic off the page was WebAudio-only → category `AmbientSound` → the hardware
ring/silent switch mutes it (WebKit treats Web Audio as "interface sounds"; see
[bug 237322](https://bugs.webkit.org/show_bug.cgi?id=237322) and Jeremy Keith's write-up). The
context dutifully reported `running` — audibility is a separate, session-level axis.

The silent looping `<audio>` element changes the computed category to `MediaPlayback`
(`hasAudibleAudioOrVideoMediaType` branch), which ignores the silent switch. **The unlock element is
the mitigation that fixed the silence.** The other two shipped mitigations can't account for it:
auto-resume only fires on `interrupted`/`suspended` (the failing state was `running`), and the
mic-toggle graph rebuild never executes with the mic untouched.

### Obs 2 — mic ON + headphones-mode OFF: crackle, LOUD, 📞 icon, volume floor, "playing both" ✅ explained

hpMode OFF → `echoCancellation: true` → WebKit builds the **VPIO** capture unit, and active capture
puts the session in `PlayAndRecord` + mode `VideoChat`/`VoiceChat` — the configuration iOS treats as
**a phone call**:

- **📞 icon**: Control Center's route/volume UI shows the call-style route for
  playAndRecord + voiceChat/videoChat sessions ("tells the system: I'm making a call").
- **Volume rocker can't reach zero**: in call mode the rocker adjusts the **call volume**, which iOS
  floors at 1/16 (documented by Unity/Vivox as an OS limitation; the classic VoIP workaround is
  app-side muting — i.e. an in-app volume control, see Fix F5).
- **LOUD**: the call-volume loudness curve is tuned for speech intelligibility on speakerphone and,
  with VPIO active, sits well above media playback at the same rocker position (Apple forum threads
  describe the level jumps when VPIO engages/disengages; WebKit bug
  [218012](https://bugs.webkit.org/show_bug.cgi?id=218012) is the mirror image — media volume
  collapses when the category flips).
- **"Playing both" / two volume domains**: one session, **two render pipelines**. The Tone.js graph
  follows the session (call) volume; the silent unlock element keeps a media-pipeline leg alive whose
  media-volume domain remains active — so the owner sees the 📞 slider *and* finds the "regular"
  volume still relevant. Our own unlock element is a **contributor** to this confusion. Worse, it
  keeps `isPlayingAudio` true forever, and the session logic is sticky: *audio playing while the
  category is PlayAndRecord keeps the category PlayAndRecord* — so after the mic is switched off
  mid-session, the call-mode volume weirdness **persists** until all audio stops.
- **Crackle**: VPIO changes the hardware I/O configuration (its own preferred sample rates and
  buffer sizes; routes like AirPods drop the whole session to lower rates). Our `AudioContext` keeps
  the sample rate it was **born** with; when the device rate underneath moves, the output unit
  requests different frame counts and Web Audio glitches — the
  [bug 154538](https://bugs.webkit.org/show_bug.cgi?id=154538) failure class ("Web Audio becomes
  distorted after sample rate changes"; documented workaround: recreate the context). The shipped
  mitigation rebuilds the **graph** but not the **context**, so the stale-rate condition — and the
  crackle — survives it. That is exactly why crackle remained only in the VPIO configuration.

### Obs 3 — mic ON + headphones-mode ON: no crackle ✅ explained

hpMode ON → `echoCancellation: false` → WebKit uses plain **RemoteIO** capture: no VPIO, no
voice-processing rate/buffer reconfiguration, hardware stays at the rate the context was born with →
clean playback. (Note: by the WebKit code the session is *still* `PlayAndRecord` + `VideoChat`
whenever any capture runs — EC only chooses the capture unit. So the 📞 icon and the call-volume
domain are **expected even in hp mode** while the mic is on; the owner didn't report on the icon in
this configuration — the retest protocol below collects that data point.)

### Obs 4 — everything except mic-on+hp-off plays "a little low" ⚠️ mostly explained

Three stacked causes, in decreasing confidence:

1. **Reference-point effect**: the owner's loudness anchor is the VPIO call mode, which is boosted;
   correct media playback sounds quiet next to it.
2. **mic ON + hp ON** sits in `PlayAndRecord` *without* VPIO — a configuration independently
   documented as noticeably quiet (Godot issue #88893 "iOS: Low audio volume when using Play and
   Record session category"; Apple forum: play-and-record alone = low, VPIO = different again).
3. **Our own conservative mix**: four parts at 0.25 into a −1 dBFS limiter, no master gain. On a
   phone speaker that is simply not loud, in any session category.

Unexplained residue: whether iOS additionally applies a "mix with others"-style attenuation to the
media category while our unlock element holds the session (bug 218012 comments point at
`MixWithOthers` being applied in some configurations). Not load-bearing for the fix — F1+F5 address
observation 4 from both ends regardless.

---

## 2. Which shipped mitigation fixed the silence, and the one-step field check

**Verdict: the silent-looping `<audio>` unlock element** (mechanism in Obs 1). The auto-resume and
rebuild mitigations are good resilience but cannot explain this recovery.

**One-step confirmation (10 seconds, no build changes):** with the mic **off** and a piece playing
audibly, flip the hardware **ring/silent switch to silent**.
- Audio keeps playing → category is `MediaPlayback`, i.e. the unlock element is doing the job. ✔
- Audio stops → the element is *not* holding the session (category fell back to `AmbientSound`), and
  the silence fix came from somewhere else — report immediately, this analysis needs revisiting.

(Corroborating signal, zero effort: the `?audiodebug=1` overlay already prints
`session (inferred) = media/playback (silent-unlock)` and `silent-unlock = engaged`.)

---

## 3. Fix design, ordered by confidence

> Files named for the implementer; **no edits now** — the Calm Surface wave owns these files.
> Effects are stated against the four axes: 📞 icon · volume domains · crackle · loudness.

### F1 — Manage `navigator.audioSession.type` explicitly (HIGH confidence, biggest win)

Safari/iOS ≥ 16.4 exposes the W3C Audio Session API (`navigator.audioSession.type`), Safari-only
(no Chrome/Firefox — BCD). In WebKit it sets `AudioSession::setCategoryOverride`
([`DOMAudioSession.cpp`](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/Modules/audiosession/DOMAudioSession.cpp):
`'playback'` → `MediaPlayback`, `'play-and-record'` → `PlayAndRecord`, `'auto'` → none), and the
override **short-circuits the entire computed state machine**, including the sticky PlayAndRecord
branch. This is precisely the workaround WebKit engineers recommend on bug 218012.

**Code changes** (new helper in `transport.js`, or a tiny `js/ios-audio.js` module):

- Boot (iOS + feature-detected): `navigator.audioSession.type = 'playback'` inside a try/catch.
- `main.js toggleMic()` — mic turning **on**: set `type = 'play-and-record'` *before*
  `setMicProcessing`/`micStart` (i.e. before any `getUserMedia`), so the session never transitions
  mid-stream.
- Mic turning **off**: after `TrainingScope.micStop()` has stopped the tracks, set
  `type = 'playback'`.
- **Never** set `'playback'` while a mic track is live: the spec's element-update steps *end the
  microphone track* when the type is not `play-and-record`/`auto` (§6.3 of the draft). Today's
  WebKit `setType` doesn't visibly enforce that, but future WebKit may.
- Caveat: `setType` silently no-ops unless the Microphone permissions-policy is enabled for the
  document — fine for our top-level page, but don't wrap the app in an `<iframe>` without
  `allow="microphone"`.

**Expected effects:** 📞 icon — *gone whenever the mic is off*, including immediately after mic-off
during playback (kills the sticky call mode; unchanged while the mic is on — WebKit forces mode
`VideoChat` for any PlayAndRecord session, so the API cannot remove the icon during capture).
Volume domains — mic-off states pinned to the media domain (single rocker, can reach zero); the
dual-domain window shrinks to mic-on only. Crackle — no direct effect. Loudness — mic-off playback
becomes plain, predictable media playback; also fixes the ring-switch silence *without* the unlock
element on ≥ 16.4 (belt-and-braces with F4).

### F2 — Recreate the AudioContext (not just the graph) on mic-driven rate mismatch (HIGH confidence for the crackle)

The detection already shipped (`toggleMic`'s `mismatch` flag); it currently only logs, and the
`hwProbe` arm runs only under the debug flag. Promote it to action:

**Code changes** (`main.js` + `transport.js`):

- In `toggleMic` (both on and off paths), on iOS run `probeHardwareRate()` unconditionally (one
  throwaway context per mic toggle is well inside iOS's budget).
- If `mismatch && playState === 'stopped'`: call `recreateAudioContext()` automatically, then
  **re-acquire the mic on the fresh context** (today's owner-triggered flow drops the mic and asks
  the owner to re-enable — automate: `micStop()` → recreate → `setMicProcessing` → `micStart`
  with the new `rawContext`), and log `auto-recreate` to the diagnostics ring.
- While playing, defer to the next stop (log `recreate-deferred`), or accept the crackle for the
  remainder of the pass — never yank a running transport.

**Expected effects:** crackle — the stale-rate class (bug 154538) is eliminated in speaker mode;
📞/domains/loudness — none. Keep the manual "Recreate ctx" button as the field fallback.

### F3 — Keep the constraint strategy exactly as-is; do NOT drop echo cancellation for speaker users (HIGH confidence)

`echoCancellation: false` provably avoids VPIO (WebKit source + the owner's clean hp-ON result), so
it is tempting to set EC false everywhere and exit call mode's side effects. **Don't.** hp-OFF users
sing over the phone's speaker: without AEC the mic hears the accompaniment, which (a) risks feedback
and (b) feeds the backing voices straight into our autocorrelation pitch tracker and the scorer —
corrupting the product's core loop. EC exists *for* the speaker case. The VPIO side effects are the
price; F1/F2/F5 pay it down. Optional copy tweak while in the Sound tab: label speaker mode's status
line with "iOS treats speaker practice like a call — use the in-app volume slider" so the 📞 icon
and rocker floor read as expected behavior, not a bug.

### F4 — Silent-unlock element lifecycle: demote it to a fallback (MEDIUM-HIGH confidence)

The element is now a liability in two ways (media-domain leg during call mode → "playing both";
`isPlayingAudio` perpetually true → sticky PlayAndRecord after mic-off).

**Code changes** (`transport.js`):

- If `navigator.audioSession` is available (iOS ≥ 16.4): **don't engage the element at all** — F1's
  `'playback'` override provides the mute-switch immunity it existed for. Keep `iosMediaUnlock` as
  the legacy path for older iOS only.
- On the legacy path, `silentEl.pause()` when the mic turns on (the session is PlayAndRecord anyway —
  the mute switch is ignored regardless), and re-`play()` it inside the next user gesture after
  mic-off (`unlockAudio` already runs inside every Play/mic gesture, so the hook exists).
- Update `silentUnlockState()`/the overlay so the field report shows which strategy is active
  (`audioSession-api` vs `silent-element` vs `none`).

**Expected effects:** volume domains — removes the second (media) leg while the mic is on, and stops
the category from sticking after mic-off on legacy iOS; 📞 — indirectly helps it clear after mic-off;
crackle/loudness — none. Risk: legacy-path resume timing (mitigated by re-engaging inside gestures).

### F5 — In-app accompaniment volume slider (HIGH confidence as UX mitigation; ship it)

iOS's call-volume floor means the rocker *cannot* silence the accompaniment in mic-on modes — the
canonical VoIP answer is app-side gain (what Vivox tells developers to do). It also answers "a
little low" (obs 4 cause 3) by making our conservative mix adjustable.

**Spec:**

- `transport.js buildAudio()`: insert one `masterVolume = new Tone.Gain(v)` between the per-part
  gains and the `Limiter(-1)`: `Gain(0.25)/part → masterVolume → Limiter → destination`. Pre-limiter
  placement means boosting can't clip (the limiter still guarantees the bus), and the recording tap
  (post-limiter, issue #67's "what you record is what you hear") keeps its invariant unchanged.
- Range 0–1.25 (a little headroom above today's level), default 1.0, log-ish taper; live-apply with
  `masterVolume.gain.rampTo(v, 0.05)`; persist under a new `state.js` key (mirror `INSTRUMENT_KEY`);
  re-apply inside every `buildAudio()` so it survives graph rebuilds and context recreation.
- UI: one row in the **Sound** pane (`#paneSound`, `index.html`) — `🔉 Accompaniment` +
  `<input type="range">` — beneath the mic/headphones row, styled per the Calm Surface spec
  (coordinate with the in-flight #73 redesign; the pane already exists in the new tab strip).
- Expose in `window.__training` (`volume()` / `setVolume(v)`) for the headless smoke test.

**Expected effects:** loudness — direct user control in every mode, including true zero in call
mode; 📞/domains/crackle — none.

### Implementation order

F1 → F2 → F5 → F4 → F3(copy only). F1 and F2 are independent and each field-testable alone; F4
depends on F1 being in place.

---

## 4. Owner field-test protocol (after implementation)

For every step: note Control Center's route icon (📞 or speaker), whether the rocker can reach
silence, crackle y/n, subjective loudness, and paste one `?audiodebug=1` **Copy report** (it now
logs session strategy, rates, and auto-recreate events).

1. **Baseline / silence-fix confirmation** — mic OFF, hp ON, Play. Flip the ring/silent switch both
   ways. Expect: audio unaffected; no 📞; rocker reaches zero; overlay shows
   `audioSession-api` strategy (or `silent-element` on old iOS).
2. **Mic ON + hp ON, Play** — the missing data point: **is the 📞 icon shown?** (Code says the
   session is call-mode even without VPIO.) Expect: no crackle; rocker floor may exist; note both
   sliders (Control Center vs rocker) — do they move independently?
3. **Mic ON + hp OFF, Play** (the old crackle case) — expect: overlay logs
   `sample-rate-mismatch` + `auto-recreate` on mic-on (if rates moved), then **no crackle**; 📞
   still present (expected while mic on); rocker floor present (iOS limit); **in-app slider reaches
   true silence**; loudness tamable.
4. **Sticky-mode exit** — while step 3 is still playing, toggle mic OFF (keep playing). Expect
   within ~a second: 📞 gone, single (media) volume domain, rocker reaches zero. Pre-fix this
   stayed stuck — this is F1's headline test.
5. **Route flip** — repeat step 3, then connect/disconnect Bluetooth headphones mid-session. Expect:
   auto-resume + (on next stop) rebuild/recreate; report any crackle onset.
6. **Volume matrix** — at a fixed rocker position, rate loudness 1–5 for: mic-off, mic+hp-on,
   mic+hp-off. Post-fix the spread should be far narrower than the field report's.

---

## 5. Risks / unknowns only on-device testing can resolve

1. **📞 in hp-mode ON** — WebKit source says call mode applies to *any* capture; if confirmed, the
   icon while the mic is on is unavoidable and must be handled by copy, not code.
2. **`type='playback'` at boot side effects** — interaction with autoplay/gesture unlock ordering,
   and whether future WebKit enforces the spec's end-mic-tracks rule more aggressively on type
   flips mid-capture.
3. **Exact rate values under VPIO on the owner's device** (48k → 24k/16k?) — determines whether F2's
   auto-recreate actually fires; the overlay's `mic-on` events will show it.
4. **Auto-recreate + immediate mic re-acquire ordering** — a race between context teardown and a
   fresh `getUserMedia` is possible; may need a ~100 ms settle or a `statechange` wait.
5. **Whether the residual "a little low" persists** after F1+F5 (the possible `MixWithOthers`
   attenuation on the media category is outside our control).
6. **Owner's iOS version** — F1 needs ≥ 16.4; the F4 fallback covers older, but the fallback path
   itself then needs one field pass.
7. **Two-slider behavior details** (which slider scales Tone output in call mode) — informs the
   step-2/3 protocol notes; purely observational, the fixes don't depend on the answer.

---

## Sources

**WebKit source (primary, verified directly):**
- [MediaSessionManagerCocoa.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/audio/cocoa/MediaSessionManagerCocoa.mm) — category/mode state machine: capture ⇒ PlayAndRecord+VideoChat; sticky PlayAndRecord while `isPlayingAudio`; audible element ⇒ MediaPlayback; WebAudio-only ⇒ AmbientSound; `categoryOverride` short-circuit.
- [AudioSessionIOS.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/audio/ios/AudioSessionIOS.mm) — AVAudioSession mapping: PlayAndRecord options (AllowBluetooth/A2DP/AirPlay, DefaultToSpeaker), VideoChat→`AVAudioSessionModeVoiceChat` when receiver preferred.
- [CoreAudioCaptureUnit.cpp](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/mediastream/cocoa/CoreAudioCaptureUnit.cpp) — `m_shouldUseVPIO = enableEchoCancellation()`; `kAudioUnitSubType_VoiceProcessingIO` vs `kAudioUnitSubType_RemoteIO`; `kAUVoiceIOProperty_OtherAudioDuckingConfiguration` at min ducking.
- [DOMAudioSession.cpp](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/Modules/audiosession/DOMAudioSession.cpp) — `navigator.audioSession.type` → `setCategoryOverride` mapping; Microphone permissions-policy gate.

**WebKit bugs:**
- [Bug 218012 — Audio volume reduces considerably on accepting the mic permissions](https://bugs.webkit.org/show_bug.cgi?id=218012) (category flip cause; recommended workarounds: audioSession type dance, processing constraints off).
- [Bug 230902 — REGRESSION iOS 15: MediaStreamTrack audio volume too low](https://bugs.webkit.org/show_bug.cgi?id=230902).
- [Bug 237322 — Web Audio muted when the iOS ringer is muted](https://bugs.webkit.org/show_bug.cgi?id=237322).
- [Bug 154538 — Web Audio becomes distorted after sample rate changes](https://bugs.webkit.org/show_bug.cgi?id=154538) (recreate-context workaround).
- [Bug 179411 — getUserMedia echoCancellation constraint history](https://bugs.webkit.org/show_bug.cgi?id=179411).

**Audio Session API:**
- [W3C Audio Session draft](https://w3c.github.io/audio-session/) (§5.4 auto-type selection; §6.3 mic tracks ended under non-capture types) · [explainer](https://github.com/w3c/audio-session/blob/main/explainer.md).
- [MDN — Audio Session API](https://developer.mozilla.org/en-US/docs/Web/API/Audio_Session_API) · [BCD data: Safari/iOS 16.4+, no Chrome/Firefox](https://github.com/mdn/browser-compat-data/blob/main/api/AudioSession.json).
- [Safari 16.4 release notes](https://developer.apple.com/documentation/safari-release-notes/safari-16_4-release-notes) · [WebKit PR #7190 (youennf, experimental AudioSession API)](https://github.com/WebKit/WebKit/pull/7190).

**Apple platform behavior:**
- [Apple Dev Forums 721535 — volume issues with Voice Processing IO](https://developer.apple.com/forums/thread/721535) ("three distinct volume levels"; gain applied below developer access).
- [Unity/Vivox — why iOS system volume cannot reach 0 in PlayAndRecord](https://support.unity.com/hc/en-us/articles/25191298269332-Vivox-Why-iOS-system-volume-cannot-be-reduced-to-0-when-in-channel) (floor = 1/16; app-side mute is the sanctioned workaround).
- [Godot #88893 — low volume under PlayAndRecord](https://github.com/godotengine/godot/issues/88893).
- [Mastering VoIP audio with CallKit/WebRTC on iOS](https://medium.com/@tsivilko/mastering-voip-audio-with-callkit-and-webrtc-on-ios-0f2092402331) (playAndRecord+voiceChat = "I'm making a call" system treatment).
- [Apple Community — how the iPhone volume domains work](https://discussions.apple.com/docs/DOC-250004676) · [Adjust the volume on iPhone](https://support.apple.com/guide/iphone/adjust-the-volume-iphb71f9b54d/ios).

**Ecosystem corroboration:**
- [Jeremy Keith — Web Audio API update on iOS](https://adactio.com/journal/19929) (mute-switch behavior; silent-element hack; audioSession pointer from Jen Simmons).
- [Tone.js #767 — resume from 'interrupted'](https://github.com/Tonejs/Tone.js/issues/767).
- [feross/unmute-ios-audio](https://github.com/feross/unmute-ios-audio) (the silent-element technique the shipped mitigation is based on).
- [webrtcHacks — Guide to WebRTC with Safari](https://webrtchacks.com/guide-to-safari-webrtc/).
