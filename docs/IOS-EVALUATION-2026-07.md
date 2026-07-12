# ChanterLab — iOS Strategy: Web-Only vs. Hybrid vs. Native Audio Core (engineering evaluation)

*2026-07-11 · GitHub issue #75 · This is the full engineering evaluation behind the one-page decision
memo `docs/IOS-NATIVE-DECISION.md` (#87, 2026-07-05). That memo made the call ("stay web-only,
five reopening tripwires"); this one supplies the evidence base an engineer would need to execute
any of the three options, grounded in the shipped code (file:line citations) and in current
WebKit/iOS platform facts (sourced, with dates — WebKit audio behavior changes by iOS version).*

**Bottom line up front: Option A (stay web-only) is reaffirmed**, with one new caveat the #87 memo
did not have — the iOS 26 PWA audio regression (§2.4) means "install to home screen" should not be
the recommended iOS entry point right now; a Safari tab is currently the *more* reliable surface.
Before any future native commitment, run the two-sided latency census in §8 — it costs a day or two
and turns every latency claim in this memo into a measured number for the owner's actual devices.

---

## 1. Ground truth: the audio path we would be porting

Everything below is the shipped code, not the plan.

**Capture → detection → scoring pipeline** (`training-prototype/`):

- Mic capture is `getUserMedia` with explicit constraints — `scope.js:62-68`: headphones mode
  (the default) requests `{ echoCancellation: false, noiseSuppression: false, autoGainControl: false }`;
  speaker mode re-enables EC+NS. The `hpMode` checkbox ships pre-checked
  (`training-prototype/index.html:171-172`).
- Default pitch detector: JS autocorrelation on an `AnalyserNode` (`scope.js:103+`), with an
  adaptive noise gate (`scope.js:105-113`) that exists specifically because the raw
  (no-processing) stream "on many devices is far quieter than the processed speaker-mode stream."
- Opt-in wasm detector (`?detector=wasm`, issue #80): an `AudioWorklet` front-end
  (`training-prototype/pitch_worklet.js`) hosting the legacy Byzantine app's Rust FFT detector.
  The Rust core is `src/worklet.rs` (`VoiceProcessor`: cascaded HPF, notch, gate, FFT detector,
  PSOLA), built by `wasm-pack` into `pkg-worklet/` (`Makefile:13`). Loading is main-thread
  fetch + transfer because "Safari's AudioWorkletGlobalScope does not reliably expose
  importScripts/fetch" (`pitch_worklet.js:13-17`, `scope.js:448-474`) — and the native
  `AudioWorkletNode` constructor rejects Tone's wrapped context, requiring an unwrap dance
  (`scope.js:476-497`). Two Safari-specific workarounds before a single sample is processed.
- Scoring is pure arithmetic over `{tSec, midi}` samples vs. target notes
  (`training-prototype/scoring.js:1-31`) — no audio dependency at all. This matters for Option C:
  the scorer ports for free; it is the *clocks feeding it* that are hard.

**The two-latency timing model** (the part any port must preserve exactly):

- **L_out** (lane sync): schedule-domain → audible-domain compensation,
  `training-prototype/js/transport.js:185-231`. On iOS, Safari "almost never exposes
  `outputLatency` (reports 0)" while the real path is ~0.1-0.2 s, so the app hard-codes a 120 ms
  fallback (`transport.js:207`) plus a field-tuned 220 ms default manual nudge
  (`transport.js:214-218`) — chosen because "speaker/Bluetooth output latency is commonly
  150-250 ms" and "the auto figure can't know Bluetooth/AirPlay hops" (`transport.js:200-201`).
- **L_in** (voice response): mic buffer + analysis window + one-euro group delay, default 65 ms
  owner-field-tuned (`transport.js:240`, mirrored at `scope.js:84`).
- Scoring uses the **sum** `Transport.seconds − L_out − L_in`, so the calibration wizard
  (`training-prototype/js/calibrate.js:1-19`) can measure the *full loop* by sing-to-the-beat and
  back out `L_in = measuredLoop − L_out` without ever being able to corrupt a score
  (`calibrate.js:10-13`, clamped application at `calibrate.js:217-218`). The wizard's
  `measureOffsetSec` (`calibrate.js:60-83`) is a ready-made on-device round-trip-latency
  instrument — §8 builds the validation experiment on it.

**iOS pain points already encoded in the code** — the empirical record of what web-on-iOS costs:

| Pain point | Where it lives |
|---|---|
| Quiet iOS Safari mic | Legacy app ships a mic pre-gain slider, default 6×, max 12×, UI hint: "iOS Safari mics are typically very quiet; try 6×–10×" (`web/index.html:180-181`, `web/app.js:199`). The training app's adaptive gate (`scope.js:105-113`) is the same problem solved differently. |
| Audio unlock on gesture | `unlockAudio()` gating every Play (`transport.js:603-615`, call sites `transport.js:1339,1389`); `Tone.start()` inside the mic gesture (`js/main.js:203`); pre-16.4 silent-`<audio>` unlock element (`transport.js:339-436`). |
| Ring-switch silence / call-mode stickiness | Audio Session API management, `'playback'` at boot (`js/main.js:795`), `'play-and-record'` before `getUserMedia` (`js/main.js:196`), `'playback'` after mic-off (`js/main.js:169`); helper `transport.js:300-337`. |
| Mic+speaker crackle (VPIO) | Root-caused to WebKit source in `docs/design/IOS-AUDIO-SESSION-ANALYSIS.md` §0-§1: `echoCancellation: true` ⇒ `kAudioUnitSubType_VoiceProcessingIO`, whose rate/buffer reconfiguration glitches the page's fixed-rate `AudioContext` (WebKit bug 154538 class). Mitigations F1/F2/F4/F5 shipped; residual is **unfixable from the web** (#74 field campaign). Honest steering copy at `js/main.js:212-218`. |
| Sample-rate flips under `getUserMedia` | Detection + automatic context recreation (`js/main.js:220-257`), graph rebuild "born under the mic" (`transport.js:276-298`). |
| Bluetooth latency | 220 ms default nudge + BT/AirPlay caveats (`transport.js:200-218`); route-flip retest protocol (`docs/IOS-AUDIO-TEST.md` step 5). |
| Wired-headphone guidance | hpMode default-on (`index.html:171-172`); "headphones are cleaner (and better for practice)" status (`js/main.js:216-218`); "🎧 Headphones give the cleanest recording" (`index.html:253`). |
| Background/screen-lock death | Field report (iPhone Safari, iOS 18.7): return from background hangs Play until refresh — Tone's transport clock runs on a Web Worker whose timers iOS kills in the background; the app ships a worker rebuild + watchdog (`transport.js:454-479`). |
| Call-volume floor | iOS floors call-mode volume at 1/16; in-app 0-125 % volume slider is the sanctioned workaround (`index.html:184-187`, `js/state.js:104-108`). |

Roughly **a third of `transport.js` and `main.js`'s audio code is iOS mitigation**. That is the
web-only tax already paid — sunk cost, and it now works (three field sessions, #74 closed
2026-07-05). The question is whether the *residual* problems justify a second engine.

## 2. Platform facts, July 2026 (dated — recency matters)

1. **Audio Session API is still Safari-only.** `navigator.audioSession` is supported in
   Safari/iOS 16.4 through 26.5 and in no version of Chrome (4-153) or Firefox (2-155) as of
   June 2026 ([caniuse](https://caniuse.com/mdn-api_audiosession), checked 2026-07-11). Our F1 fix
   therefore stays an iOS-only code path indefinitely — but it also means Apple has given the web
   a real session-control lever and we already use it.
2. **AudioWorklet on iOS is functional but not bulletproof over long sessions.** Godot users report
   WebKit page crashes on iOS 26.3 after 10-30 minutes of continuous audio
   ([godotengine/godot#116750](https://github.com/godotengine/godot/issues/116750), 2026). Our
   default detector deliberately does *not* use a worklet (plain `AnalyserNode` polling); the wasm
   worklet detector is opt-in (`scope.js:86-91`). Keep it that way until the worklet path has a
   long-session soak test on a real device.
3. **Background audio remains a hard web ceiling.** iOS suspends web audio when the screen locks or
   a standalone web app leaves the foreground (WebKit bug
   [198277](https://bugs.webkit.org/show_bug.cgi?id=198277), still relevant); our own iOS 18.7
   field report (`transport.js:454-465`) shows even *returning* from background needs recovery
   machinery. Only a native `AVAudioSession` background-audio entitlement survives screen lock
   reliably (Apple forums [658375](https://developer.apple.com/forums/thread/658375)).
4. **NEW since #87: iOS 26 shipped a PWA-specific audio regression.** Audio in *installed*
   (home-screen) web apps breaks after first launch on iOS 26.0 (2025-09-20) while the same app
   works in a Safari tab; improved in 26.1 (2025-11-05) and 26.2 (2025-11-12) but still not fully
   resolved as of January 2026
   ([MacRumors forums thread](https://forums.macrumors.com/threads/ios-26-audio-issues-in-pwa-web-apps-not-fixed-in-26-1-or-26-2-but-much-better.2466839/)).
   Consequence: our shipped PWA manifest (`training-prototype/manifest.webmanifest`, standalone
   display) is currently a *riskier* audio surface than a plain Safari tab. Do not push A2HS install
   in iOS onboarding copy until this is verified fixed on a current iOS point release.
5. **PWA install friction is unchanged.** No `beforeinstallprompt` on iOS; install is manual
   share-sheet → "Add to Home Screen"; Web Push exists since 16.4 but only for installed PWAs
   ([Mobiloud 2026 guide](https://www.mobiloud.com/blog/progressive-web-apps-ios),
   [Brainhub 2025](https://brainhub.eu/library/pwa-on-ios)).
6. **App Store payments context** (unchanged from #87, summarized): since the April 2025 ruling,
   U.S. apps may link out to external checkout commission-free; Ninth Circuit largely upheld this
   Dec 2025, SCOTUS cert granted for the 2026 term — see `docs/IOS-NATIVE-DECISION.md` §2b and its
   sources. Net: App Store presence is about discoverability/procurement, not escaping a payment cut.

## 3. Option A — stay web-only / PWA

**What now works on iOS** (post-#74, all field-confirmed): playback without mic through the ring
switch, call-mode exit on mic-off, auto-recovery from sample-rate flips, true-zero in-app volume,
background-return recovery, per-device timing calibration. §1's table is the receipts.

**What still breaks, honestly:**

| Problem | Status under A |
|---|---|
| Mic+speaker crackle (VPIO) | Unfixable from web (`IOS-AUDIO-SESSION-ANALYSIS.md` §1 Obs 2); confined to the non-default, actively-discouraged hpMode-off + speaker combo. Mitigated by steering, not solved. |
| Echo-cancellation quality control | None. We choose EC on/off per mode (`scope.js:62-68`); we cannot tune VPIO's AGC/ducking, and WebKit's EC is take-it-or-leave-it. |
| Background / screen-lock practice | Not available; won't be. Screen must stay on during practice. Acceptable for a sing-while-watching-the-score product, fatal only for a hypothetical ear-training/audio-only mode. |
| Quiet raw mic | Worked around (gain slider in legacy app, adaptive gate in training app); no `setInputGain` equivalent on the web. |
| PWA install | Manual A2HS; and per §2.4 currently audio-degraded on iOS 26 — recommend Safari-tab use for now. |
| AudioWorklet longevity | Default JS detector avoids it; wasm detector opt-in pending soak test (§2.2). |
| Latency | ~185-400 ms full loop (L_out 120-220 ms + L_in 65+ ms) — but *calibrated out* for scoring by design (§1). Latency hurts only the monitoring feel, and this product deliberately never monitors the mic (`scope.js:55-59`). |

**Cost:** zero new surface. Keeps the demonstrated same-day ship loop (web → ArgoCD pod →
chanterlab.com) with no review gate.

## 4. Option B — hybrid wrapper (WKWebView / Capacitor)

The framing in issue #75 said it and the evidence confirms it: **a plain wrapper does not fix the
audio**, because WKWebView runs the same WebKit WebAudio/getUserMedia stack.

**What B genuinely does NOT solve:**
- VPIO crackle: `getUserMedia` inside WKWebView makes the same `m_shouldUseVPIO =
  enableEchoCancellation()` decision. Worse, WKWebView *ignores the host app's*
  `AVAudioSession` category settings — WebKit manages the session itself (WebKit bug
  [167788](https://bugs.webkit.org/show_bug.cgi?id=167788)); the native shell cannot quietly
  reconfigure the session out from under its own web view.
- Background capture: WKWebView's `microphoneCaptureState` mutes shortly after
  `applicationDidEnterBackground` and cannot be re-activated from the background — while a native
  `AVAudioSession` capture in the same app keeps working (Apple Dev Forums
  [689182](https://developer.apple.com/forums/thread/689182), iOS 15 era, still the behavior).
  So B doesn't even buy background audio without going half-native anyway.

**What B does solve (small but real):**
- Gesture unlock: `WKWebViewConfiguration.mediaTypesRequiringUserActionForPlayback = []` removes
  the unlock dance for *playback* (the mic prompt remains).
- Permission UX: since iOS 15, `WKUIDelegate.decideMediaCapturePermissionFor` lets the app
  grant mic access once at the app level instead of Safari's per-origin prompting.
- Distribution: App Store listing, real icon, no share-sheet install — and it sidesteps the §2.4
  PWA audio regression only in the trivial sense that a WKWebView app is not a home-screen PWA
  (it may share related GPU-process audio plumbing; untested).

**What B costs:**
- App Store review per release (or a remote-content web view, which is itself guideline-fragile),
  Apple Developer account, certificates, a second (thin) codebase.
- **Guideline 4.2 minimum-functionality risk**: a bare wrapper around a website is a documented
  rejection category — the "thin wrapper for discoverability" play can simply be refused.
- **GPLv3 (see §6)** — applies to any App Store distribution, B or C.

Verdict unchanged from #87 §3(B): a marketing/procurement play dressed as an engineering step.
Execute it only when tripwire #2 (a paying customer requiring App Store procurement) fires.

## 5. Option C — native audio core (AVAudioEngine) + reused detector

The only option that actually removes the residual defect class, because the app would own the
`AVAudioSession` and the capture unit choice outright.

**Audio engine:** AVAudioEngine capture/playback, with either Apple's voice processing on our
terms (`inputNode.setVoiceProcessingEnabled(true)` — iOS 13+, per-node VPIO with duck/AGC options
we control) or plain RemoteIO + our own gate/notch (already in the Rust core, §1) for the
headphone path. Session category `.playAndRecord` with `.defaultToSpeaker`/`.allowBluetoothA2DP`
as *we* schedule it, `.measurement` mode where we want the raw mic. Background-audio entitlement
makes screen-lock practice possible for the first time.

**Latency & mic quality vs. today** — the comparison table the decision needs:

| Axis | Web iOS today (measured/shipped) | Native AVAudioEngine (documented) |
|---|---|---|
| Output latency (L_out) | Safari reports `outputLatency` 0; app assumes 120 ms + 220 ms field-tuned nudge (`transport.js:207,218`); BT adds 150-250 ms invisibly | Reported per-route by `AVAudioSession.outputLatency`; IO buffer configurable to ~5 ms (`setPreferredIOBufferDuration`); BT latency still physics, but *visible* to the app |
| Input+detection (L_in) | 65 ms default, calibrated per device (`transport.js:240`) | Mic buffer ~5-10 ms + same detector math; `.measurement` mode removes ~30 ms of Apple preprocessing ([Superpowered](https://superpowered.com/latency)) |
| Full round trip | ~185-400 ms, made scoring-safe by calibration (`calibrate.js:10-13`) | <10-20 ms achievable on wired/built-in routes ([Superpowered](https://superpowered.com/latency), [Onyx3 latency meter](https://onyx3.com/LatencyMeter/)); VPIO adds ~30 ms |
| Mic input level | Raw stream notoriously quiet — shipped 6×-10× boost hint (`web/index.html:180-181`), adaptive gate (`scope.js:105-113`) | `AVAudioSession.setInputGain` where hardware permits, plus our own pre-gain — deterministic |
| Echo cancellation | Binary on/off via constraint; VPIO internals untouchable | Per-node VPIO with configuration, or ship our own AEC only for speaker mode |
| Crackle class | Unfixable residual in speaker+mic mode | Eliminated: no context born at a stale rate — the engine renders at the hardware rate we configure |
| Background / screen lock | Suspended; recovery machinery on return (`transport.js:454-479`) | Background-audio entitlement; capture keeps running (forum 689182) |

Honest framing: **scoring accuracy does not need native latency.** The SUM-invariant calibration
(§1) already makes 300 ms of known latency harmless to scores. Native latency buys (a) tighter
*visual* sync out of the box, (b) the crackle fix, (c) mic-quality control, (d) background. It does
not buy better grades.

**Detector reuse — cheaper than #75's framing assumed.** The "wasm detector" is not wasm-native;
it is a Rust crate (`chanterlab-core`, `crate-type = ["cdylib", "rlib"]`, `Cargo.toml:9`) that we
*currently* compile to wasm (`Makefile:13`). The identical `VoiceProcessor` (`src/worklet.rs`)
compiles to an iOS static library with `cargo build --target aarch64-apple-ios` and binds to Swift
via UniFFI or a thin C ABI (prefer C ABI on the render thread — UniFFI marshalling overhead is a
known problem in realtime audio callbacks;
[Rust-in-iOS tutorials, 2023-2025](https://dev.to/almaju/building-an-ios-app-with-rust-using-uniffi-200a),
[audio_unit_rust_demo](https://github.com/timboudreau/audio_unit_rust_demo)). Pitch-detection
parity between platforms is therefore near-free. What is **not** free:

- **Transport/scheduling**: Tone.js's transport, per-part sample playback, loop/lap machinery —
  all rewritten against `AVAudioEngine`/`AVAudioPlayerNode` scheduling.
- **Recording mixer**: the two-leg what-you-hear recording graph (`js/recording.js:13-22`).
- **The bridge**: if the UI stays web (WKWebView + native audio), every timestamp crossing the
  bridge is a third clock domain on top of L_out/L_in — the scoring timing model would need a
  bridge-latency term and a re-derived calibration story. This is the sneaky-hard part.
- UI alternatives: (i) WKWebView UI + native audio bridge — maximum reuse, hardest clock story;
  (ii) Capacitor + custom audio plugin — same thing with framework help; (iii) SwiftUI rewrite —
  no bridge, total UI loss. All three inherit App Store review and §6.

## 6. GPLv3 × App Store (applies to B and C)

The repo is `GPL-3.0-only` (`LICENSE`, `README.md:26-28`). The FSF's long-standing position is
that Apple's App Store terms impose usage restrictions incompatible with the GPL — the precedent
is VLC's removal from the App Store in 2011 after a developer complaint, which VLC later resolved
by relicensing its core to LGPL
([FSF: App Store GPL enforcement, 2010](https://www.fsf.org/news/2010-05-app-store-compliance),
[FSF on the VLC case, 2011](https://www.fsf.org/blogs/licensing/vlc-enforcement),
[FSF on VLC's relicensing, 2012](https://www.fsf.org/blogs/licensing/left-wondering-why-vlc-relicensed-some-code-to-lgpl)).

For ChanterLab this is a solvable problem *today* and a trap *later*:

- The copyright is effectively single-holder — `git log` shows Justin Fursov / jayfurz (same
  person) as author of essentially all commits. A sole copyright holder can dual-license an App
  Store build, or add a GPLv3 §7 additional permission ("App Store exception") without anyone's
  consent.
- Vendored third-party code is permissively licensed (Tone.js MIT, OSMD BSD-3-Clause; the Neanes
  font has its own license per `README.md:30-31`) — no external copyleft blocker.
- **The trap**: the moment an external GPL-licensed contribution is merged without a CLA or the
  exception already in place, App Store distribution needs that contributor's consent. If B or C
  is ever plausible, add the §7 App Store exception (or start a CLA) *before* soliciting
  contributors — it costs one commit now and potentially a relicensing campaign later.

## 7. Maintenance cost for a single maintainer

| | A: web-only | B: wrapper | C: native audio hybrid |
|---|---|---|---|
| New surfaces | none | Xcode project, certs, review pipeline | all of B + Swift audio engine (est. 3-6 kLOC), Rust-iOS build lane, JS↔Swift bridge protocol |
| Audio engines to keep in sync | 1 | 1 (same engine, worse debugging: web inspector via cable) | **2** — every transport feature (loops, laps, count-in, recording, calibration) lands twice or forks |
| Release trains | 1 (same-day, no gate — Sprints 1-7 track record) | 2 (web + App Store review, days-long tail) | 2, with the native train gating audio fixes — the exact class of fix #74 showed needs *field iteration* (three sessions to converge) |
| Test burden | headless CI + one iPhone | + simulator/device matrix | + device matrix × route matrix (speaker/wired/BT) × session-config matrix, natively instrumented |
| Platform-risk exposure | WebKit regressions (e.g. §2.4) — mitigations shippable same-day | same, plus review delays on the fix | Apple API churn instead of WebKit churn; fixes gated on review |
| Realistic effort to first parity | — | 2-4 weeks | 3-6 months part-time, and #74-style field-tuning restarts from zero on the native stack |

The #74 campaign is the strongest single argument here: converging iOS audio behavior took three
field sessions with same-day code iterations between them. A review-gated release train breaks
precisely that loop — for a solo maintainer, C doesn't just add code, it removes the team's one
demonstrated superpower.

## 8. Recommendation and the cheap validation experiment

**Recommendation: Option A — stay web-only.** This evaluation reaffirms `docs/IOS-NATIVE-DECISION.md`
(#87) with the engineering detail filled in, and its five tripwires stand unchanged. Two additions:

1. **Do not promote PWA install on iOS until §2.4 is confirmed fixed** — recommend the Safari tab
   in onboarding copy; re-test A2HS audio on each iOS point release (10-minute check with the
   existing `?audiodebug=1` overlay).
2. **If any tripwire ever fires, land the GPLv3 §7 App Store exception (or a CLA) first** (§6) —
   one commit now, while the copyright is still single-holder.

**The validation experiment (run BEFORE committing to anything native — 1-2 days total):**

*Purpose: replace this memo's two soft numbers — "web full loop ~185-400 ms" and "native floor
<10-20 ms" — with measurements from the same physical devices, and decide whether the delta buys
anything the product can feel.*

- **Step 1 — web-side latency census (half a day, pure JS).** The calibration wizard already
  measures the full sing-to-score loop on-device (`calibrate.js:60-83` returns `deltaSec`;
  `finishMeasure` at `calibrate.js:212-219` splits it against `getDisplayLatency()`). Add a
  `?latencylab=1` mode that, after each wizard run, appends `{deltaSec, matched, L_out, L_in,
  audioSnapshot()}` (the #74 diagnostics snapshot, `js/main.js:392-430`) to the existing event
  ring with a Copy button. Run it on the owner's iPhone across the route matrix: wired headphones,
  Bluetooth, speaker+mic (crackle config), each ×3 runs. Output: the real web latency
  distribution per route, plus confirmation of how stable calibration is run-to-run.
- **Step 2 — native floor on the same hardware (half a day, ~zero code).** Run the free
  [Superpowered latency test app](https://superpowered.com/latency) (or
  [Onyx3's meter](https://onyx3.com/LatencyMeter/)) on the same iPhone and routes to get the
  native round-trip floor. Optionally, a ~200-line Swift scratch app (AVAudioEngine impulse
  loopback, with and without `setVoiceProcessingEnabled`) reproduces it first-party and doubles
  as a VPIO-crackle counter-example on the exact device that produced #74's field reports.
- **Step 3 — decision gate.** Native is worth revisiting only if (a) the measured web-vs-native
  delta translates into something a singer perceives that calibration cannot absorb (it should
  not — scoring is delta-invariant by construction, §1), or (b) Step 2 confirms native VPIO
  config eliminates the speaker-mode crackle *and* tripwire #1 (crackle at real-user scale) has
  actually fired. Otherwise the numbers go into this doc as an appendix and the web-only call
  stands on data, not estimates.

---

*Sources checked 2026-07-11. Code citations are against this commit's tree; WebKit behavior
citations are dated inline because they rot — re-verify §2 before acting on this memo after
~iOS 27.*
