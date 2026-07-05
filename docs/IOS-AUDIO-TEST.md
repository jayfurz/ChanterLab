# iPhone audio field test — ChanterLab training app (issue #74)

Two symptoms, reported only on a real iPhone (desktop is clean, and the phone is
clean-but-silent without the mic):

1. **Silent unless the mic is on.** Play with the mic **off** produces **no sound
   at all**, even with the ring/silent switch set to **RING**. Turning the mic on
   makes sound appear.
2. **Crackle with the mic on.** Once the mic is on, playback is audible but
   **crackles / pops**.

We can't reproduce either on our machines (they need real iOS audio hardware), so
this is a **guided field test**. It ships a hidden diagnostics overlay that reads
the live audio state on your phone; you run a short checklist and paste the
results back. **Nothing here changes normal playback** — the overlay is inert
until you open it.

---

## 0. Open the diagnostics overlay

Two ways (either works):

- **URL:** open the app with `?audiodebug=1` on the end of the address, e.g.
  `https://chanterlab.com/training/?audiodebug=1`
- **Triple-tap** the grey status line (the "Loaded: …" text under the title)
  three times quickly. Triple-tap again to hide it.

A small dark panel appears top-left. It updates live. Buttons:

- **Recreate ctx** — closes and rebuilds the audio engine on the current
  hardware route (this is the candidate fix for the "silent" bug — see Test B).
- **HW rate** — logs the phone's current hardware sample rate.
- **Copy** — copies the whole readout + event log to the clipboard so you can
  paste it into the issue / a message.
- **✕** — hide.

### The three numbers that matter most

Read these off the panel while you test:

1. **`GRAPH OUTPUT … peakMax`** during a **no-mic Play**. This is the single most
   important number. It says whether the app is *producing* audio even when you
   hear nothing:
   - `peakMax` **> 0** while you hear **silence** → the sound engine is working;
     the phone is throwing the audio away at the route/session level → the
     **Recreate ctx** fix is the right lever.
   - `peakMax` **≈ 0** (stays 0.0000) during Play → the engine itself isn't
     producing → a different (scheduling) problem.
2. **`ctx.sampleRate`** and the **`state`** next to it, read **before and after**
   you turn the mic on. Watch for the rate changing (e.g. **48000 → 24000**) and
   for the state ever reading **`interrupted`** (an iOS-only state).
3. **`outputLatency`** before vs after the mic, and **`stalls`** on the bottom
   line. A jump in `outputLatency` when the mic flips the session, and any
   `stalls > 0`, both point at the crackle.

The panel also infers the audio **session** category (`ambient` vs
`media/playback` vs `play-and-record`) and whether the **silent-unlock** is
engaged — see Test D.

---

## Before you start

- Use the **same piece** each time (the default one is fine). Set a slow tempo so
  notes are easy to hear.
- After each sub-test, tap **Copy** and save the text (paste into Notes/Messages)
  labelled with the test name. The event log is timestamped, so one big paste at
  the end is fine too.
- "hpMode" below = the **🎧 Headphones mode** checkbox in the app's controls.

---

## Test A — the silence bug (do this first)

Goal: find out whether the engine is producing audio while you hear nothing.

| # | Ring/Silent switch | Headphones | Mic | Do | Read & note |
|---|---|---|---|---|---|
| A1 | **RING** | none (speaker) | **off** | Press **Play** | Do you hear anything? `GRAPH OUTPUT peakMax` after ~3 s? `ctx.sampleRate` / `state`? |
| A2 | **SILENT** | none (speaker) | **off** | Press **Play** | Same three: audible? `peakMax`? rate/state? |
| A3 | **RING** | wired or Bluetooth | **off** | Press **Play** | Audible? `peakMax`? rate/state? |
| A4 | **RING** | none | **on** | tap **🎤**, then **Play** | Audible now? crackle? `peakMax`? `ctx.sampleRate` vs A1? `state`? |

**What each outcome means:**

- **A1 silent but `peakMax > 0`** → engine works, route/session eats the sound →
  go to **Test B** (Recreate ctx) and **Test D** (silent-unlock).
- **A1 silent and `peakMax ≈ 0`** → engine isn't producing with the mic off →
  paste the log; this points away from the route and toward scheduling.
- **A4 audible with a *different* `ctx.sampleRate` than A1** → confirms the
  mic-flips-the-session mechanism; the rate delta is the crackle's root cause too.
- **`state` ever shows `interrupted`** → note exactly when; that's an iOS session
  interruption the app now tries to auto-recover from.

---

## Test B — does recreating the audio engine fix the silence?

Only meaningful if **Test A** showed **silent but `peakMax > 0`**.

1. Ring switch **RING**, mic **off**, no headphones.
2. Press **Play** — confirm it's silent (and `peakMax > 0`).
3. Press **Stop**.
4. Tap **Recreate ctx** in the panel. Note the `before→after` rate in the status
   line / log (e.g. `48000→24000`).
5. Press **Play** again.
6. **Is there sound now?** Note yes/no and the new `ctx.sampleRate`.

- **Sound now plays** → the "running-but-silent context" diagnosis is confirmed;
  we'll make the app recreate the context automatically on that condition.
- **Still silent** → paste the log; we rule that fix out and move on.

Repeat once with the ring switch on **SILENT** to see if it differs.

---

## Test C — the crackle (mic on)

1. Mic **on**, **Play**. Let it run ~15 s.
2. Watch the bottom line: **`stalls`** count and **`clock health`** (should sit
   near `1.00x`; dips mean the audio thread starved).
3. Note `outputLatency` and `baseLatency` now vs. what they were with the mic off
   (Test A1).
4. Try each combination and note *how bad* the crackle is (none / light / heavy):
   - hpMode **on** (raw mic) vs **off** (processed mic) — the checkbox.
   - **wired** headphones vs **Bluetooth/AirPods** vs **speaker**.
5. Tap **HW rate** and compare it to `ctx.sampleRate`. A mismatch (panel shows
   **⚠ RATE MISMATCH** or the two numbers differ) is the crackle's fingerprint.

The most useful crackle data point: **the combination where it's worst** plus the
`ctx.sampleRate` / `HW rate` / `stalls` for that combination.

---

## Test D — the silent-audio unlock (one variable, not the fix)

The app also plays an inaudible looping track on iOS to try to hold audio on the
"media" channel. Confirm whether it's engaged and whether it changes anything:

1. On any Play, check the panel line `silent-unlock = engaged` (and not
   `(not playing!)`).
2. If it says **engaged** but **Test A** was still silent, note that clearly —
   it tells us the media-channel trick alone isn't enough on your device.

---

## Test E — background / return (interruptions)

1. Mic on or off, **Play**.
2. Press the **Home** gesture to background Safari for ~5 s, then return.
3. Does audio resume? Does the panel log a **`statechange`** to `interrupted` /
   `suspended` and back? Note `state` after returning.

This checks the auto-resume-from-`interrupted` handling.

---

## What to send back

Tap **Copy** at the end (or after each test) and paste the text. For each test
note in plain words:

- **Audible? yes/no**, and **crackle? none/light/heavy**.
- The **three key numbers** for that moment: `GRAPH OUTPUT peakMax`,
  `ctx.sampleRate` (+ `state`), and `outputLatency` / `stalls`.
- For **Test B**: did **Recreate ctx** bring the sound back? the `before→after`
  rate.

That's enough to tell, from your phone alone, **which** of the candidate fixes
(recreate-on-silence, sample-rate rebuild, session/route handling, or the
media-channel unlock) is the real one — without us needing to reproduce it.

---

### Appendix — what the app already does defensively (issue #74)

- **Silent-audio playback-category unlock** on iOS (a looping inaudible `<audio>`
  element) to bias WebAudio onto the media channel.
- **Sample-rate mismatch detection** on mic start (context rate before/after +
  mic-track rate + a fresh-hardware-rate probe), logged to the panel.
- **Born-under-play-and-record rebuild**: enabling the mic while stopped rebuilds
  the playback graph so the next Play starts under the mic's session (and again
  on mic-off and on a `devicechange`).
- **`interrupted`/`suspended` auto-resume** via a raw-context `statechange`
  listener (Tone's own resume only handles `suspended`).
- **Recreate ctx** (manual, in the panel): the close-and-recreate workaround for
  the running-but-silent context class — promoted to automatic once your field
  test confirms it helps.

None of these is confirmed to fix the bug yet — that's what this test decides.
