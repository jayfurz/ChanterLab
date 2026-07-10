# iPhone audio field test — ChanterLab training app (issue #74)

**Status: retest after the F1/F2/F4/F5 fixes** (see
`docs/design/IOS-AUDIO-SESSION-ANALYSIS.md` for the full WebKit-source-level
analysis this protocol is built from). The original field report was two
symptoms on a real iPhone (desktop is clean, and the phone used to be
clean-but-silent without the mic):

1. **Silent unless the mic is on.** Play with the mic **off** produced no
   sound at all, even with the ring/silent switch on **RING**.
2. **Crackle with the mic on**, plus a phone-call-style 📞 route icon, a
   volume rocker that couldn't reach true silence, and everything else
   sounding "a little low."

What changed since the last pass:

- **F1** — the app now explicitly manages `navigator.audioSession.type`
  (Safari ≥16.4): `'playback'` at boot and immediately after the mic goes
  off; `'play-and-record'` right before the mic goes on. This should make the
  📞 icon and the call-volume floor **disappear the moment the mic goes off**,
  even if audio keeps playing — that used to stay stuck.
- **F2** — a detected sample-rate mismatch (mic-on OR mic-off) now
  **automatically recreates the audio engine** (not just the graph) and
  re-acquires the mic on the fresh context, instead of only logging the
  mismatch. The manual **Recreate ctx** button still exists as a fallback.
- **F4** — the old silent-looping-`<audio>` trick is now demoted to a
  legacy-iOS-only fallback: on Safari ≥16.4 it's never even created (F1's
  override does its job); pre-16.4 it's paused while the mic is on and
  re-engaged right on the mic-off tap.
- **F5** — a new in-app **Volume 🔊** slider (Sound tab) gives real 0%
  loudness in every mode, including while the mic is on and the hardware
  rocker is stuck at its call-mode floor.

Nothing here changes normal playback unpredictably — the diagnostics overlay
is inert until you open it, same as before.

---

## 0. Open the diagnostics overlay

Two ways (either works):

- **URL:** open the app with `?audiodebug=1` on the end of the address, e.g.
  `https://chanterlab.com/training/?audiodebug=1`
- **Triple-tap** the grey status line (the "Loaded: …" text under the title)
  three times quickly. Triple-tap again to hide it.

A small dark panel appears top-left. It updates live. Buttons:

- **Recreate ctx** — manually closes and rebuilds the audio engine on the
  current hardware route (F2 now does this automatically on a detected
  mismatch; this button is the manual fallback).
- **HW rate** — logs the phone's current hardware sample rate.
- **Copy** — copies the whole readout + event log to the clipboard so you can
  paste it into the issue / a message.
- **✕** — hide.

### The numbers and lines that matter most

1. **`session (inferred)` line.** On Safari ≥16.4 this should now read
   `override: play-and-record` while the mic is on and `override: playback`
   the instant it's off — a **confirmed** value, not a guess. Older iOS still
   shows the old inferred guess (`play-and-record (mic, inferred)` /
   `media/playback (silent-unlock, inferred)` / `ambient/default (inferred)`).
2. **`unlock strategy` line** — `audioSession-api` (≥16.4, F1 is doing the
   work, the old `<audio>` trick is never engaged) or `silent-element`
   (pre-16.4 fallback) or `none` (not iOS). This is new — confirm it says
   `audioSession-api` on your phone if it's a reasonably recent iOS.
3. **`GRAPH OUTPUT … peakMax`** during a no-mic Play — unchanged from before:
   `peakMax > 0` while you hear silence means the engine is producing audio
   and it's a route/session-level problem (should be rare now that F1 pins
   the session explicitly).
4. **`ctx.sampleRate`** / **`state`**, read before and after the mic goes on —
   watch for the rate changing and for the event log now showing
   `sample-rate-mismatch` immediately followed by `auto-recreate` (F2 firing
   automatically) rather than just a logged mismatch with no action.
5. **`volume = NN%`** on the bottom line — reflects the new Volume slider;
   confirm it tracks the slider position.

---

## Before you start

- Use the **same piece** each time (the default one is fine). Set a slow
  tempo so notes are easy to hear.
- Note the **Volume 🔊** slider position for each test — leave it at 100%
  unless a step says otherwise.
- After each step, tap **Copy** and save the text (paste into Notes/Messages)
  labelled with the step number. The event log is timestamped, so one big
  paste at the end also works.
- "hpMode" below = the **🎧 Headphones mode** checkbox in the Sound tab.

---

## The six-step retest (design doc §4)

For every step: note Control Center's route icon (📞 or speaker), whether the
rocker (and separately, the in-app **Volume** slider) can reach silence,
crackle y/n, subjective loudness, and paste one **Copy report**.

### 1. Baseline / silence-fix confirmation

Mic **OFF**, headphones mode **ON**, press **Play**. Flip the ring/silent
switch both ways.

**Expect:** audio unaffected either way; no 📞 icon; the hardware rocker
reaches zero; the overlay's `session (inferred)` line shows
`override: playback` (or, on old iOS, `unlock strategy = silent-element` with
`silent-unlock = engaged`).

### 2. Mic ON + headphones ON, Play — the missing data point

**Is the 📞 icon shown?** (The design doc's WebKit-source reading says the
session is call-mode for *any* capture, headphones or not — this step
confirms it on real hardware.)

**Expect:** no crackle; the hardware rocker may still have a floor (iOS
limit — expected); the in-app **Volume** slider should still reach true
silence even if the rocker can't; note whether Control Center's slider and
the rocker move independently.

### 3. Mic ON + headphones OFF, Play — the old crackle case

**Expect:** the overlay logs `sample-rate-mismatch` followed automatically by
`auto-recreate` (and `auto-recreate:mic-reacquired` if the mic was on) — no
manual button press needed; after that, **no crackle**; 📞 still present
(expected while the mic is on); rocker floor present (iOS limit, expected);
the **in-app Volume slider reaches true silence** regardless; loudness is
now tamable via that slider.

### 4. Sticky-mode exit — F1's headline test

While step 3 is still playing, tap the mic **OFF** (keep the audio playing).

**Expect within about a second:** 📞 **gone**, a single (media) volume
domain, the hardware rocker reaches zero, and the overlay's event log shows
`audiosession-set` with `type: playback, reason: mic-off` right after
`mic-off`. Pre-fix this stayed stuck in call mode until all audio stopped —
**this is the fix to confirm first if you only have time for one test.**

### 5. Route flip

Repeat step 3, then connect/disconnect Bluetooth headphones mid-session.

**Expect:** auto-resume, and — once you next Stop — a `sample-rate-mismatch`
/ `auto-recreate` pair if the route changed the hardware rate. Report any
crackle onset before that next Stop (F2 only acts while stopped, by design —
it will never cut off audio mid-Play).

### 6. Volume matrix — F5's headline test

At a **fixed hardware rocker position**, and with the in-app **Volume**
slider at 100%, rate loudness 1–5 for: mic-off, mic+headphones-on,
mic+headphones-off. Then set the in-app Volume slider to **0%** in each of
those three states and confirm it reaches **true silence** every time
(including mic-on states, where the hardware rocker alone cannot). The
loudness spread across the three states, at a fixed slider position, should
also be far narrower than the original field report's.

---

## What to send back

Tap **Copy** at the end of each step (or once at the end covering all of
them) and paste the text. For each step note in plain words:

- **Audible? yes/no**, **crackle? none/light/heavy**, **📞 icon? yes/no**.
- Whether the **hardware rocker** and the **in-app Volume slider** each reach
  true silence.
- The `session (inferred)` and `unlock strategy` lines.
- For step 3/5: did `sample-rate-mismatch` → `auto-recreate` appear in the
  log without you pressing anything?
- For step 4: how long after mic-off did the 📞 icon clear?

That tells us, from your phone alone, whether F1 (session pinning), F2
(auto-recreate), and F5 (in-app volume) are each doing their job — without us
needing to reproduce any of it.

---

### Appendix — what the app does now (issue #74 + follow-up)

- **F1 — explicit `navigator.audioSession.type` management** (Safari ≥16.4):
  `'playback'` at boot and right after the mic turns off; `'play-and-record'`
  right before the mic turns on, before `getUserMedia`. This override
  short-circuits WebKit's whole capture/playback category state machine,
  including the sticky "PlayAndRecord while audio keeps playing" branch.
  Feature-detected — a complete no-op pre-16.4 and off iOS.
- **F2 — sample-rate mismatch now triggers an automatic context recreation**
  (not just the graph) on the next mic toggle while stopped, then
  re-acquires the mic on the fresh context. Guarded to one recreate at a time
  and to a stopped transport (never interrupts a running Play). The manual
  **Recreate ctx** button remains as a fallback.
- **F3 — echo cancellation is unchanged for speaker (headphones-mode-off)
  users.** This is deliberate, not an oversight: without it the mic would
  hear the accompaniment, risking feedback and corrupting the pitch
  tracker/scorer. The 📞 icon and call-volume floor while the mic is on in
  that mode are the accepted price — F1/F2/F5 pay it down everywhere else.
- **F4 — the silent-`<audio>` unlock element is now a fallback only.** Never
  even constructed on Safari ≥16.4 (F1 covers its job); on older iOS it's
  paused for the duration of any live mic track and re-engaged on the very
  mic-off tap, rather than being held open forever (which used to keep the
  session sticky in call mode after mic-off).
- **F5 — an in-app master Volume slider** (Sound tab, 0–125%, default 100%,
  persisted) sits before the limiter in the audio graph. This is the
  sanctioned answer to iOS's call-volume floor (never truly reaches zero via
  the hardware rocker) — the slider does reach true zero, in every mode.
  Recordings follow it (they're tapped after the limiter, i.e.
  what-you-hear-is-what-you-record).
- **`interrupted`/`suspended` auto-resume** via a raw-context `statechange`
  listener (unchanged from before).

This retest is what confirms all four are actually doing their job on real
hardware — headless testing can prove the code paths execute correctly and
that desktop stays byte-identical, but only a real iPhone can confirm the
📞 icon truly clears and the crackle is truly gone.

## Step 7 — buffer-size experiment (screen-recording clue, 2026-07-05)

Owner finding: starting an iPhone SCREEN RECORDING (Control Center) makes the
mic-on + headphones-off crackle vanish; it returns when recording stops.
Screen recording forces larger system audio buffers → the crackle is likely
buffer underrun in the voice-processing session. Test the same medicine:

1. Reproduce the crackle: mic ON, headphones-mode OFF, speaker, Play.
2. In the ?audiodebug=1 overlay note `outputLatency`, then start a screen
   recording and note `outputLatency` again — if it JUMPS while the crackle
   dies, the buffer hypothesis is confirmed. Stop the recording.
3. Tap **Buf: large** (recreates the context with latencyHint 'playback'),
   re-enable the mic, Play. Crackle gone? Note `outputLatency`.
4. If large works, try **Buf: med** — the smallest buffer that stays clean is
   the winner (less added latency). Report which one, plus the outputLatency
   readings from 2-4. If even 'large' crackles while screen recording stays
   clean, the effect is session-mode (VPIO) not buffers — also useful to know.
