/* transport.js — audio synths/mix, playback scheduling, the follow cursor,
 * and the Play/Pause/Stop + transport-overlay state machine.
 */
import { el, setStatus, GOLD, VOICE_DEFS } from './state.js';
import { parsed, clampMeasure, measureBeatRange, isMonophonic } from './model.js';
import { osmd, osmdSteps, ensureRenderWindow, flushDeferredRender } from './loader.js';
import { selectedVoice, melodyMuted, buildScopeLane } from './voices.js';
import { beginScoringSession, scoreLapAndRoll, finalizeScoringOnStop, scoreSummaryShown } from './scoring-ui.js';
import { currentSections, setActiveSection, sectionIndexForMeasure } from './sections.js';
import { onPlaySucceeded, onStopped } from './onboarding.js';

let synths = [];           // Tone.PolySynth per part
export let gains = [];     // Tone.Gain per part
let master = null;         // Tone.Limiter master bus — the only node between the
                           // summed voices and the speakers (issue #65)
let scheduledIds = [];
let cursorWindow = [];     // absolute osmdSteps indices inside the current loop window
export let playState = 'stopped';
export let userHoldUntil = 0;
let lastFollowScroll = 0;  // throttles the per-note follow-scroll (issue #65)
const FOLLOW_SCROLL_MS = 140;

  /* ---------- Audio (Tone.js) ----------------------------------------- */

  // Current Tone AudioContext state ('running' | 'suspended' | 'closed' | …).
  // Exposed for headless tests via window.__training.audioContextState()
  // (issue #63) — a post-Play assertion that doesn't rely on actually
  // hearing sound (CI has no audio device).
export function audioContextState() {
    return (typeof Tone !== 'undefined' && Tone.getContext) ? Tone.getContext().state : 'unknown';
  }

  // Unlock the browser AudioContext SYNCHRONOUSLY within the calling gesture's
  // handler chain (iOS Safari requirement — no detours through setTimeout/rAF
  // before this call). Every audio-starting user-gesture path (Play/Resume —
  // see startPlayback/resume below — and anywhere else audio starts from a
  // tap/click/change) must call this FIRST, before touching the transport.
  // Returns true once the context is actually running; false means the
  // browser's autoplay policy still blocked it (rare, but real on some mobile
  // browsers even after a genuine tap) — callers must NOT pretend to play in
  // that case: no scheduling, no transport start, just prompt a retry tap
  // (issue #63).
  async function unlockAudio() {
    await Tone.start();
    if (Tone.getContext().state !== 'running') {
      setStatus('Tap again to enable sound.');
      return false;
    }
    return true;
  }

export function buildAudio() {
    disposeAudio();
    synths = [];
    gains = [];
    // Give the scheduler more headroom so a heavy main-thread tick (OSMD cursor
    // stepping over a big SVG — the measured 87ms tasks in issue #65) can't fire
    // note events past-due and glitch. 0.1→0.2s doubles the lookahead budget at
    // the cost of ~100ms of extra output latency (both audio AND the follow
    // cursor shift together, so they stay in sync — imperceptible for follow-
    // along practice). Set here (idempotent) so it's applied before first Play.
    if (typeof Tone !== 'undefined' && Tone.getContext) Tone.getContext().lookAhead = 0.2;
    // Master bus: a brickwall limiter at -1 dBFS is the ONLY node between the
    // summed voices and the speakers. Four unison voices at 0.25 each sum to
    // ~1.0 at their peaks (measured 0.90 on the default 4-part piece, 0.89 with
    // "also hear my part"); real-time phase drift or a hotter piece crosses 1.0
    // and hard-clips at the device — the "popping/crackle" of issue #65. The
    // limiter catches those transients transparently (it doesn't engage until
    // ~-1 dBFS, so normal material is untouched) and guarantees the bus can
    // never clip. It sits on the SYNTH bus only — the scoring/scope path taps
    // the mic (scope.js), never this bus, so scoring is unaffected.
    master = new Tone.Limiter(-1).toDestination();
    parsed.parts.forEach(() => {
      const gain = new Tone.Gain(0.25).connect(master);
      const synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: 'triangle' },
        // Explicit, gentle envelope. The few-ms attack keeps note onsets crisp
        // without a zero-length edge (which would click); the shorter release
        // (was 0.25s) trims the note tail so dense same-pitch chant stops piling
        // overlapping releases into the limiter, keeping headroom. Measured 0
        // discontinuities on the 50%-repeated-pitch worst case (issue #65).
        envelope: { attack: 0.008, decay: 0.1, sustain: 0.85, release: 0.12 },
      }).connect(gain);
      synths.push(synth);
      gains.push(gain);
    });
  }

  function disposeAudio() {
    synths.forEach((s) => s.dispose());
    gains.forEach((g) => g.dispose());
    if (master) { master.dispose(); master = null; }
    synths = []; gains = [];
  }

  // Mute the selected voice unless "also hear my part" is checked.
  // NOTE: this is the ONLY place backing-voice gain changes, and it depends
  // solely on voice selection — never on mic input/level (see Headphones mode
  // in scope.js for the OS-level ducking story).
export function applyMix() {
    const mono = parsed.parts.length === 1;
    parsed.parts.forEach((p, idx) => {
      if (!gains[idx]) return;
      const isSelected = p.voiceKey === selectedVoice;
      // 1-voice piece: the sole line follows melodyMuted (no "your part" mix).
      // Multi-voice: mute only your selected voice unless you opt to hear it.
      const mute = mono ? melodyMuted : (isSelected && !el.hearMine.checked);
      gains[idx].gain.rampTo(mute ? 0 : 0.25, 0.05);
    });
  }

  function midiToFreq(m) { return 440 * Math.pow(2, (m - 69) / 12); }

  function scheduleAll() {
    clearSchedule();
    const spb = 60 / Number(el.bpm.value); // seconds per quarter-note beat
    const from = clampMeasure(Number(el.loopFrom.value));
    const to = clampMeasure(Number(el.loopTo.value));
    const loop = el.loopOn.checked;

    // window in beats: use measures. We approximate measure length from the
    // control's own note onsets (first note beat of each measure).
    const range = measureBeatRange(from, to);
    const winStart = range.start;
    const winEnd = range.end;

    parsed.parts.forEach((part, idx) => {
      part.notes.forEach((n) => {
        if (n.startBeat < winStart - 1e-6 || n.startBeat >= winEnd - 1e-6) return;
        const t = (n.startBeat - winStart) * spb;
        const dur = Math.max(0.05, n.durBeat * spb * 0.95);
        const id = Tone.Transport.schedule((time) => {
          synths[idx].triggerAttackRelease(midiToFreq(n.midi), dur, time);
        }, t);
        scheduledIds.push(id);
      });
    });

    // cursor timeline = OSMD's own step table clipped to the window. Indices
    // stay ABSOLUTE (= next() calls since cursor.reset()) so stepCursorTo can
    // advance by exactly the right count even when the window starts mid-piece.
    cursorWindow = [];
    osmdSteps.forEach((s, i) => {
      if (s.beat < winStart - 1e-4 || s.beat >= winEnd - 1e-4) return;
      cursorWindow.push(i);
      const t = (s.beat - winStart) * spb;
      const id = Tone.Transport.schedule(() => stepCursorTo(i), t);
      scheduledIds.push(id);
    });

    const total = (winEnd - winStart) * spb;
    if (loop) {
      Tone.Transport.loop = true;
      Tone.Transport.loopStart = 0;
      Tone.Transport.loopEnd = total;
      // LAP-BOUNDARY DETECTION (issue #55): Tone.Transport re-fires every
      // event scheduled inside [loopStart,loopEnd) on each pass — that's
      // already how the pre-#55 spike's resetCursor() call here kept
      // resetting the cursor once per lap, and how the note/cursor-step
      // schedules above keep replaying each lap. So the exact same "just
      // before the wrap" instant is the one boundary signal a lap needs: no
      // separate polling/rAF watcher, just score-and-reset piggybacked onto
      // the schedule that already existed for the cursor reset.
      const id = Tone.Transport.schedule(() => onLapWrap(), total - 1e-3);
      scheduledIds.push(id);
    } else {
      Tone.Transport.loop = false;
      const id = Tone.Transport.schedule(() => stop(), total + 0.3);
      scheduledIds.push(id);
    }
  }

  // Fires ~1ms before the transport wraps back to loopStart (see the comment
  // above). Scores the lap that just finished (no-op if the mic produced no
  // samples this lap — see scoreCurrentLap), rolls the sample buffer over to
  // the next lap, and resets the follow cursor.
  //
  // KNOWN EDGE CASE: this callback runs on Tone's audio-clock schedule, which
  // can fire a few ms ahead of the pitch tracker's rAF-driven sample stream
  // (real mic latency). A straggler sample or two from the very tail of the
  // finishing lap can therefore land in the NEXT lap's buffer instead. In
  // practice this only ever brushes the last note of a lap, whose target
  // pitch is identical lap-to-lap (same passage repeating), so the practical
  // effect is negligible — a deliberate v1 tradeoff, not an oversight.
  function onLapWrap() {
    scoreLapAndRoll();   // score the finished lap + roll the sample buffer (scoring-ui.js)
    resetCursor();
  }

  function clearSchedule() {
    scheduledIds.forEach((id) => Tone.Transport.clear(id));
    scheduledIds = [];
  }

  /* ---------- Cursor -------------------------------------------------- */

  function resetCursor() {
    if (!osmd.cursor) return;
    // Belt-and-braces: some OSMD builds ignore constructor cursorsOptions.
    if (osmd.cursor.CursorOptions) {
      osmd.cursor.CursorOptions.color = GOLD;
      osmd.cursor.CursorOptions.alpha = 0.45;
      osmd.cursor.CursorOptions.follow = false;   // never let OSMD scroll the page
    }
    osmd.cursor.reset();
    osmd.cursor.show();
    if (osmd.cursor.update) osmd.cursor.update();
    cursorStep = 0;
    // when the loop window starts mid-piece, park the cursor on the window's
    // first step instead of the top of the piece
    if (cursorWindow.length && cursorWindow[0] > 0) {
      while (cursorStep < cursorWindow[0]) { osmd.cursor.next(); cursorStep++; }
    }
    updatePos(cursorWindow.length ? osmdSteps[cursorWindow[0]].measure : null);
    lastFollowScroll = 0;   // let the first per-step follow-scroll fire promptly
    scrollCursorIntoView();
  }
export let cursorStep = 0;
  function stepCursorTo(i) {
    if (!osmd.cursor) return;
    if (i < cursorStep) {
      // loop wrapped without an explicit reset — rewind and re-advance
      osmd.cursor.reset(); osmd.cursor.show(); cursorStep = 0;
    }
    while (cursorStep < i) { osmd.cursor.next(); cursorStep++; }
    updatePos(osmdSteps[i] ? osmdSteps[i].measure : null);
    // Throttle the follow-scroll. scrollCursorIntoView reads offsetTop/Height
    // (a forced synchronous reflow over a ~4500-node score SVG that osmd.cursor
    // .next just invalidated) and restarts a smooth-scroll animation. Doing that
    // on every step piles main-thread work into the audio scheduler's tick
    // (issue #65). The cursor glyph and posOut still advance every step; only
    // the score-scroll cadence is capped — the cursor never drifts more than
    // ~140ms (< one note) before the view catches up.
    const now = performance.now();
    if (now - lastFollowScroll >= FOLLOW_SCROLL_MS) { lastFollowScroll = now; scrollCursorIntoView(); }
  }

  function updatePos(measure) {
    if (!el.posOut) return;
    // Just the current measure — the windowed-render pill ("of N") is the sole
    // denominator, and it uses the PRINTED count (updatePos used the SOURCE
    // count, so the two disagreed at split measures).
    el.posOut.textContent = measure ? `m ${measure}` : 'm –';
    // Keep the active-section label in step with the cursor's measure (cheap
    // binary search; no-op for pieces without sections). measure===null (stop)
    // leaves the last active section shown rather than blanking it.
    if (currentSections.length && measure != null) {
      setActiveSection(sectionIndexForMeasure(measure));
    }
  }

  // Keep the follow cursor visible inside the scrollable score container.
  // Etiquette (owner's design):
  //   - only ever scrolls the score CONTAINER — never the page,
  //   - only while PLAYING (paused/stopped = page + score fully free),
  //   - suspends ~3 s after any user touch/scroll on the container,
  //   - vertically prioritizes the SELECTED voice's staff (the cursor element
  //     spans the whole system, so the active staff sits at a fractional
  //     height within it — S top … B bottom).
  // force=true bypasses the playing-state + user-hold guards: a PAUSED jump-to-
  // section needs to scroll the score to the parked cursor even though playback
  // isn't running (the normal path only auto-scrolls while playing).
  function scrollCursorIntoView(force) {
    if (!force) {
      if (playState !== 'playing') return;
      if (performance.now() < userHoldUntil) return;
    }
    const cEl = osmd && osmd.cursor && osmd.cursor.cursorElement;
    const wrap = el.osmd;
    if (!cEl || !wrap) return;

    const vTop = wrap.scrollTop;
    const vBottom = vTop + wrap.clientHeight;
    const sysTop = cEl.offsetTop;
    const sysBottom = sysTop + cEl.offsetHeight;

    if (cEl.offsetHeight <= wrap.clientHeight - 8) {
      // The whole system fits — keep ALL staves (T and B included) in view.
      if (sysTop < vTop || sysBottom > vBottom) {
        const slack = Math.max(6, (wrap.clientHeight - cEl.offsetHeight) * 0.35);
        wrap.scrollTo({ top: Math.max(0, sysTop - slack), behavior: 'smooth' });
      }
    } else {
      // System taller than the viewport — gold-voice priority: center the
      // SELECTED voice's staff (cursor spans the system, staff ≈ fractional).
      const nParts = parsed && parsed.parts.length ? parsed.parts.length : 1;
      const selIdx = parsed ? parsed.parts.findIndex((p) => p.voiceKey === selectedVoice) : -1;
      const frac = selIdx >= 0 ? (selIdx + 0.5) / nParts : 0.5;
      const targetY = sysTop + cEl.offsetHeight * frac;
      const margin = Math.min(30, wrap.clientHeight * 0.12);
      if (targetY < vTop + margin || targetY > vBottom - margin) {
        wrap.scrollTo({ top: Math.max(0, targetY - wrap.clientHeight * 0.5), behavior: 'smooth' });
      }
    }
    const left = cEl.offsetLeft;
    if (left < wrap.scrollLeft + 10 || left > wrap.scrollLeft + wrap.clientWidth - 30) {
      wrap.scrollTo({ left: Math.max(0, left - wrap.clientWidth * 0.3), behavior: 'smooth' });
    }
  }

export function noteUserTouch() { userHoldUntil = performance.now() + 3000; }

  // Park the follow cursor at the loop-window start while PAUSED/STOPPED, then
  // scroll it into view. Mirrors resetCursor's mid-piece parking but without any
  // playback scheduling (cursorWindow isn't built until startPlayback).
export function parkCursorAtWindowStart() {
    if (!osmd || !osmd.cursor) return;
    const cur = osmd.cursor;
    if (cur.CursorOptions) {
      cur.CursorOptions.color = GOLD;
      cur.CursorOptions.alpha = 0.45;
      cur.CursorOptions.follow = false;
    }
    cur.reset();
    cur.show();
    if (cur.update) cur.update();
    cursorStep = 0;
    const from = clampMeasure(Number(el.loopFrom.value));
    const to = clampMeasure(Number(el.loopTo.value));
    const { start: winStart } = measureBeatRange(from, to);
    // first rendered step at/after the window start (the step table is clipped
    // to the rendered window but beats stay absolute)
    let target = 0;
    for (let i = 0; i < osmdSteps.length; i++) {
      if (osmdSteps[i].beat >= winStart - 1e-4) { target = i; break; }
    }
    while (cursorStep < target) { cur.next(); cursorStep++; }
    updatePos(osmdSteps[target] ? osmdSteps[target].measure : from);
    scrollCursorIntoView(true);   // force: we're paused, bypass the playing guard
  }

  /* ---------- Transport ----------------------------------------------- */

  // Single source of truth for the "Playing…" status line, so a mid-play toggle
  // of the melody Playing/Muted seg or the "Also play my part" checkbox can
  // repaint it truthfully (they used to only re-mix, leaving the line lying).
export function statusForPlaying() {
    if (isMonophonic()) {
      return melodyMuted
        ? 'Melody muted — sing it yourself. Follow the gold cursor.'
        : 'Playing the melody — follow along or sing with it.';
    }
    const name = VOICE_DEFS.find((v) => v.key === selectedVoice)?.name;
    return el.hearMine.checked
      ? `Playing — ${name} audible (practising along).`
      : `Playing — ${name} muted (sing it). Follow the gold cursor.`;
  }

export async function playPause() {
    if (playState === 'playing') { pause(); return; }
    if (playState === 'paused') { await resume(); return; }
    await startPlayback();
  }

export async function startPlayback() {
    if (!(await unlockAudio())) return;   // suspended-context guard (issue #63)
    if (!synths.length) buildAudio();
    applyMix();
    // Windowed scores: make sure the loop range is actually rendered before we
    // schedule cursor steps (the cursor iterator is clipped to the render
    // window). No-op for small pieces / already-covered ranges.
    ensureRenderWindow(Number(el.loopFrom.value), Number(el.loopTo.value));
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    buildScopeLane();
    scheduleAll();
    // Scoring v1: start a fresh sample buffer + lap session (owned by scoring-ui.js).
    beginScoringSession();
    playState = 'playing';
    resetCursor();
    Tone.Transport.start('+0.1');
    updatePlayUI();
    setOverlay(false);
    setStatus(statusForPlaying());
    onPlaySucceeded();   // first-run onboarding (issue #64) — no-op after the first time
  }

  function pause() {
    Tone.Transport.pause();
    playState = 'paused';
    updatePlayUI();
    setOverlay(true);
    setStatus('Paused — scroll freely. ▶ resumes where you left off.');
  }

  async function resume() {
    if (!(await unlockAudio())) return;   // suspended-context guard (issue #63)
    playState = 'playing';
    Tone.Transport.start();
    updatePlayUI();
    setOverlay(false);
    setStatus(statusForPlaying());
    onPlaySucceeded();   // no-op after the first successful Play this browser
  }

export function stop() {
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    clearSchedule();
    if (osmd && osmd.cursor) osmd.cursor.hide();
    // Score whatever's left of the current lap (final/partial lap); no-op with
    // the mic off. Owned by scoring-ui.js.
    const scored = finalizeScoringOnStop();
    playState = 'stopped';
    flushDeferredRender();   // apply a render deferred during playback (loader.js)
    updatePos(null);
    updatePlayUI();
    setOverlay(true);
    // Keep a just-produced score summary on the surface across this Stop and any
    // repeated Stops (e.g. a manual Stop after an auto-stop) — only fall back to
    // "Stopped." when no summary is showing. Cleared by the next Play.
    if (!scored && !scoreSummaryShown) setStatus('Stopped.');
    onStopped();   // first-run onboarding (issue #64) — no-op before the first Play
  }

export function updatePlayUI() {
    el.play.textContent =
      playState === 'playing' ? '⏸ Pause' :
      playState === 'paused' ? '▶ Resume' : '▶ Play';
  }

  /* ---------- Transport overlay (fixed bottom sheet) -------------------- */

export function setOverlay(expanded) {
    el.transport.classList.toggle('collapsed', !expanded);
    el.expandHandle.setAttribute('aria-expanded', String(expanded));
  }

export function initOverlay() {
    el.expandHandle.addEventListener('click', () =>
      setOverlay(el.transport.classList.contains('collapsed')));
    el.voiceChip.addEventListener('click', () => setOverlay(true));
    // Reserve page bottom padding = live overlay height, so the overlay never
    // covers the singscope's now-line (or any content) at full page scroll.
    const sync = () => document.documentElement.style.setProperty(
      '--transport-h', el.transport.offsetHeight + 'px');
    new ResizeObserver(sync).observe(el.transport);
    sync();
  }

