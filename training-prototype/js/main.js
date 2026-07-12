/* main.js — entry module: control wiring, mic, startup, and the
 * window.__training / window.__library test hooks assembled from the module
 * exports. Loaded as <script type="module"> (deferred), after the vendored
 * classic scripts (OSMD, Tone, scoring.js, scope.js) have defined their globals.
 */
import { el, setStatus, PIECES, PRACTICE_HISTORY_KEY } from './state.js';
import { parsed, transposeSemitones, setTransposeSemitones } from './model.js';
import {
  osmd, osmdSteps, viewMode, windowed, sourceMeasureCount, renderFromIdx, renderToIdx,
  lastPrinted, loadPieceById, loadStartingPiece, resolvePieceId, setView,
  applyResponsiveOsmdOptions, isNarrow, requestRender, renderFullScore,
  ensureRenderWindow, maybeExtendOnScroll, indexFromPrinted, printedForIndex,
  renderCount, clearScoreColoring, scoreColoringInfo,
} from './loader.js';
import {
  gains, playState, userHoldUntil, cursorStep, applyMix, statusForPlaying,
  startPlayback, stop, playPause, updatePlayUI, setOverlay, initOverlay, noteUserTouch,
  audioContextState, instrumentMode, loadInstrumentMode, switchInstrumentMode,
  updateInstrumentUI, captureOfflineAB, audioContextInfo, rebuildAudioForMic,
  iosMediaUnlock, iosMediaUnlockPauseForMic, silentUnlockState, isIOS, masterOutputLevel,
  recreateAudioContext, audioSessionSupported, setAudioSessionType,
  markContextForRecovery, contextRecoveryState, transportInfo, setOnContextRecreated,
  setRecoveryLogger, setRecoveryTestOverride,
  getVolume, setVolume, loadVolume, updateVolumeUI, getDisplayLatency,
  setScopeSyncMs, getScopeSyncMs,
  setResponseLatencyMs, getResponseLatencyMs, getResponseLatencySec,
} from './transport.js';
import {
  practiceSamples, lastScoreResult, sessionLaps, scoringStrictness, buildScoreTargets,
  setStrictness, loadStrictness, updateStrictnessUI, dismissReport, toggleScoreColoring,
} from './scoring-ui.js';
import {
  currentSections, activeSectionIdx, xmlScannedSections, jumpToSection, initSections,
} from './sections.js';
import { activeVerse, setVerse, buildScopeLane, updateVoiceChip } from './voices.js';
import { initScopeVerdicts, syncScopeVerdicts, scopeVerdictsInfo } from './scope-verdicts.js';
import {
  libProto, libItems, libFlat, libOffsets, libOpen, libFacetDefs, libCollapsed,
  loadLibraryManifest, openLibrary, closeLibrary, toggleGroup, renderWindow, initLibrary,
} from './library.js';
import { initTour, maybeAutoStartTour, startTour, tourNext, tourPrev, endTour, tourState } from './tour.js';
import { initCalibrate, openCalibrate, closeCalibrate, measureOffsetSec } from './calibrate.js';
import {
  initRecording, startRecording, stopRecording, onMicChange, setBalance, recordingState,
} from './recording.js';
import { initKeys } from './keys.js';

let resizeTimer = 0;
let loopRenderTimer = 0;   // debounce windowed re-render on loop-input edits

  // Practice transpose: set the absolute value and propagate everywhere a
  // change matters — same live-change contract as the tempo slider (rebuild
  // the lane, re-sync verdict tints, restart mid-play so the schedule picks
  // up the new pitches). Shared by the ± buttons and the __training hook.
  const fmtTranspose = (n) => (n > 0 ? `+${n}` : String(n));
  function applyTranspose(value) {
    const v = setTransposeSemitones(value);
    if (el.transposeOut) el.transposeOut.textContent = fmtTranspose(v);
    buildScopeLane();
    syncScopeVerdicts();
    if (playState === 'playing') { stop(); startPlayback(); }
    else if (playState === 'paused') stop();
    setStatus(v === 0 ? 'Transpose off — original key.'
      : `Transposed ${fmtTranspose(v)} semitone${Math.abs(v) === 1 ? '' : 's'} — the score shows the original key.`);
    return v;
  }

  /* ---------- Wire-up ------------------------------------------------- */

  function initControls() {
    PIECES.forEach((p) => {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = p.label; el.piece.appendChild(o);
    });
    // Hidden built-in selector (kept for headless tests). The library overlay
    // is the primary picker; both route through loadPieceById.
    el.piece.addEventListener('change', () => loadPieceById(el.piece.value, { fromSelect: true }));
    el.bpm.addEventListener('input', () => {
      el.bpmOut.textContent = el.bpm.value;
      buildScopeLane();
      syncScopeVerdicts();   // same window, rebuilt lane — restore verdict tints (issue #60)
      if (playState === 'playing') { stop(); startPlayback(); }
      else if (playState === 'paused') stop();
    });
    if (el.transposeDown) el.transposeDown.addEventListener('click', () => applyTranspose(transposeSemitones - 1));
    if (el.transposeUp) el.transposeUp.addEventListener('click', () => applyTranspose(transposeSemitones + 1));
    el.play.addEventListener('click', playPause);
    el.stop.addEventListener('click', stop);
    if (el.retryStart) el.retryStart.addEventListener('click', loadStartingPiece);
    el.hearMine.addEventListener('change', () => {
      applyMix();
      updateVoiceChip();   // keep the 🔇 chip glyph in sync
      // Mid-play, the status line otherwise lies about whether your part is audible.
      if (playState === 'playing') setStatus(statusForPlaying());
    });
    el.loopOn.addEventListener('change', () => {
      if (playState !== 'stopped') { stop(); startPlayback(); }
    });
    // Loop edits: refresh the scope immediately; render the new range (windowed
    // scores) on a short debounce so editing the two fields one at a time
    // doesn't render an intermediate wide/inverted range. startPlayback also
    // ensures the window, so this is only to preview the range before Play.
    const onLoopChange = () => {
      buildScopeLane();
      // Lane rebuilt: re-sync verdict tints (issue #60). Unchanged range gets
      // its tints back; a different range fails the count guard → plain gold.
      syncScopeVerdicts();
      // Preview-render the loop range only while stopped (a re-render hides the
      // follow cursor); startPlayback re-ensures the window before it schedules.
      if (!windowed || playState !== 'stopped') return;
      clearTimeout(loopRenderTimer);
      loopRenderTimer = setTimeout(
        () => ensureRenderWindow(Number(el.loopFrom.value), Number(el.loopTo.value)), 300);
    };
    el.loopFrom.addEventListener('change', onLoopChange);
    el.loopTo.addEventListener('change', onLoopChange);
    el.micBtn.addEventListener('click', toggleMic);
    el.hpMode.addEventListener('change', onHeadphonesToggle);
    // Master accompaniment volume (issue #74 F5) — see transport.js's setVolume.
    if (el.volume) el.volume.addEventListener('input', () => setVolume(Number(el.volume.value) / 100));
    // Timing calibration sliders (live + persisted). Playback sync (L_out) nudges
    // the gold lane; Voice response (L_in) back-dates the trace + scoring.
    if (el.scopeSync) el.scopeSync.addEventListener('input', () => {
      setScopeSyncMs(Number(el.scopeSync.value)); updateTimingUI();
    });
    if (el.responseLag) el.responseLag.addEventListener('input', () => {
      const ms = setResponseLatencyMs(Number(el.responseLag.value));
      if (window.TrainingScope && TrainingScope.setInputLatency) TrainingScope.setInputLatency(ms / 1000);
      updateTimingUI();
    });
    if (el.calibrateBtn) el.calibrateBtn.addEventListener('click', openCalibrate);
    [...el.viewPicker.children].forEach((b) =>
      b.addEventListener('click', () => setView(b.dataset.view)));
    if (el.strictnessPicker) {
      [...el.strictnessPicker.children].forEach((b) =>
        b.addEventListener('click', () => setStrictness(b.dataset.strictness)));
    }
    if (el.instrumentPicker) {
      [...el.instrumentPicker.children].forEach((b) =>
        b.addEventListener('click', () => switchInstrumentMode(b.dataset.instrument)));
    }
    if (el.scoreReportClose) {
      el.scoreReportClose.addEventListener('click', dismissReport);
    }
    // Verse switch clears any per-note score coloring (issue #79). The verse
    // buttons are (re)built inside voices.js, so listen on the stable #versePicker
    // container via delegation — no-op when no overlay is active, and the chip
    // re-syncs off the 'chanterlab:scorecoloring' event clearScoreColoring fires.
    if (el.versePicker) el.versePicker.addEventListener('click', () => clearScoreColoring());

    // auto-scroll etiquette: user touch on the score container suspends
    // cursor-follow for ~3 s (each event refreshes the window)
    ['touchstart', 'touchmove', 'pointerdown', 'wheel'].forEach((ev) =>
      el.osmd.addEventListener(ev, noteUserTouch, { passive: true }));

    // Windowed scores: scrolling to the bottom of the rendered portion lazily
    // renders more.
    el.osmd.addEventListener('scroll', maybeExtendOnScroll, { passive: true });
    if (el.renderFull) el.renderFull.addEventListener('click', renderFullScore);

    // Re-apply responsive OSMD sizing + re-layout on resize. Debounced to fire
    // once per settle; autoResize is OFF so this is the ONLY render path on
    // resize (colors already live on the model → one render, boundary or not).
    let wasNarrow = null;
    window.addEventListener('resize', () => {
      if (libOpen) renderWindow(true);
      if (!osmd) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        const n = isNarrow();
        if (n !== wasNarrow) { wasNarrow = n; applyResponsiveOsmdOptions(); }
        requestRender();
      }, 180);
    });
  }

  /* ---------- Mic ------------------------------------------------------ */

  async function toggleMic() {
    if (TrainingScope.isMicOn()) {
      TrainingScope.micStop();
      el.micBtn.classList.remove('on');
      el.micBtn.textContent = '🎤 Mic';
      onMicChange();   // drop the mic leg from any live recording + relabel (issue #67)
      setStatus('Mic off.');
      // F1 (issue #74 follow-up): the mic track is now stopped, so it's safe to
      // claim the plain playback session — this is what kills the STICKY
      // PlayAndRecord/call-mode session (📞 icon, dual volume domains) that
      // otherwise survives mic-off for as long as audio keeps playing. Feature-
      // detected no-op pre-16.4 / off iOS (see docs/design/IOS-AUDIO-SESSION-
      // ANALYSIS.md F1). Must come AFTER micStop — never 'playback' with a live
      // mic track.
      logAudioEvent('audiosession-set', setAudioSessionType('playback', 'mic-off'));
      // F4: legacy-iOS fallback only (audioSessionSupported() already made this
      // a no-op above 16.4) — re-engage the media-channel unlock now, in this
      // very gesture, rather than waiting for a separate Play tap.
      iosMediaUnlock();
      // iOS route-flip mitigation (issue #74): dropping the mic reverts the
      // AVAudioSession toward playback-only, which can re-change the route/rate.
      // Log it and — if we're stopped — rebuild so the next Play is born on the
      // reverted session. No-op off iOS / while playing / with no piece loaded.
      logAudioEvent('mic-off', { rate: ctxSampleRate() });
      const r = rebuildAudioForMic('mic-off');
      if (r && r.rebuilt) logAudioEvent('graph-rebuilt', r);
      // F2: the hardware may have settled at a different rate than our
      // (possibly stale) context now that capture has stopped — auto-recreate
      // while safely stopped; no mic to re-acquire on this path.
      const hwProbeOff = (isIOS() || audioDebugEnabled()) ? probeHardwareRate() : null;
      const ctxRateOff = ctxSampleRate();
      const mismatchOff = !!(hwProbeOff && ctxRateOff && hwProbeOff !== ctxRateOff);
      if (mismatchOff) logAudioEvent('sample-rate-mismatch', { rate: ctxRateOff, hwProbe: hwProbeOff, reason: 'mic-off' });
      await autoRecreateForMismatch({ reason: 'mic-off', mismatch: mismatchOff, reacquireMic: false });
      return;
    }
    try {
      // F1 (issue #74 follow-up): claim the play-and-record session BEFORE
      // getUserMedia — the override short-circuits WebKit's whole category
      // state machine, so the session never transitions mid-stream. No-op
      // pre-16.4 / off iOS.
      logAudioEvent('audiosession-set', setAudioSessionType('play-and-record', 'mic-on'));
      // F4: legacy-iOS fallback only — the silent-unlock element is now a
      // liability while a mic track is live (its playing keeps isPlayingAudio
      // stuck, trapping the session in call mode after mic-off), so PAUSE it
      // rather than engaging it. No-op on ≥16.4 (never constructed) / off iOS.
      iosMediaUnlockPauseForMic();
      const rateBefore = ctxSampleRate();       // rate the graph was born at
      await Tone.start();                       // user gesture → audio context running
      // Headphones mode ON (default) = raw mic: echoCancellation OFF so the
      // phone can't duck the backing voices while you sing.
      await TrainingScope.setMicProcessing(!el.hpMode.checked);
      await TrainingScope.micStart(Tone.getContext().rawContext);
      el.micBtn.classList.add('on');
      el.micBtn.textContent = '🎤 On';
      onMicChange();   // fan the live mic into any active recording + relabel (issue #67)
      if (el.scopeHint) el.scopeHint.textContent = 'sing your gold line — cyan is you, gold glow = on the note (±50¢, any octave)';
      // iOS + mic + speaker runs Apple's voice-processing unit, which crackles
      // under WebKit and is unfixable from the web (field-tested: rates clean,
      // buffers don't help, screen-recording routes around it). Headphone mode
      // is clean AND the better practice setup — say so once, honestly.
      setStatus(isIOS() && !el.hpMode.checked
        ? 'Mic on. iPhone speaker + mic can crackle — headphones are cleaner (and better for practice).'
        : 'Mic on — sing your part. Headphones avoid feedback from the other voices.');

      // Sample-rate mismatch detection (issue #74). getUserMedia flips iOS to
      // play-and-record, which can move the hardware sample rate. The
      // AudioContext's own rate is fixed at creation, so either a changed
      // ctx.sampleRate OR a ctx-vs-mic-track mismatch means the live graph is now
      // resampling and will crackle. A fresh throwaway AudioContext is born at
      // the CURRENT hardware rate, so it reveals the mismatch even when Safari's
      // getSettings() omits sampleRate. F2 (issue #74 follow-up): probed
      // unconditionally on iOS now (one throwaway context per mic toggle is well
      // inside iOS's per-page budget) instead of only under the debug flag, so
      // the auto-recreate below actually has hwProbe to work with in the field.
      const rateAfter = ctxSampleRate();
      const micSettings = (TrainingScope.getMicSettings && TrainingScope.getMicSettings()) || null;
      const micRate = micSettings && micSettings.sampleRate != null ? micSettings.sampleRate : null;
      const hwProbe = (isIOS() || audioDebugEnabled()) ? probeHardwareRate() : null;
      const mismatch =
        (rateBefore && rateAfter && rateBefore !== rateAfter) ||
        (micRate && rateAfter && micRate !== rateAfter) ||
        (hwProbe && rateAfter && hwProbe !== rateAfter);
      logAudioEvent('mic-on', {
        rateBefore, rateAfter, micRate,
        echoCancellation: micSettings && micSettings.echoCancellation,
        hwProbe, mismatch: !!mismatch,
      });
      if (mismatch) logAudioEvent('sample-rate-mismatch', { rateBefore, rateAfter, micRate, hwProbe });
      logAudioEvent('silent-unlock', silentUnlockState());
      // Born-under-play-and-record (issue #74, mitigation 3): rebuild the
      // playback graph now that the session is in play-and-record — and to
      // re-sync it if a mismatch was just detected. Silent + idempotent (same op
      // as an instrument switch); a NO-OP while playing (can't cut live sound)
      // or before a piece loads. Inaudible on desktop, where nothing flipped.
      const rb = rebuildAudioForMic(mismatch ? 'mic-on:mismatch' : 'mic-on');
      if (rb && rb.rebuilt) logAudioEvent('graph-rebuilt', rb);
      // F2: promote the mismatch detection above from log-only to ACTION —
      // recreate the AudioContext itself (not just the graph) and re-acquire
      // the mic on the fresh context. rebuildAudioForMic (above) only rebuilds
      // the Tone graph on the SAME (stale-rate) context, which is why the
      // crackle survived it (WebKit #154538 needs a genuinely new context).
      await autoRecreateForMismatch({ reason: 'mic-on', mismatch, reacquireMic: true });
    } catch (e) {
      setStatus('Mic unavailable: ' + e.message);
    }
  }

  async function onHeadphonesToggle() {
    const hp = el.hpMode.checked;
    // Calm Surface (#73/§9-8): the standing #micNote paragraph was deleted; its
    // guidance now lives in the checkbox title + the status messages below. Kept
    // as a no-op guard so a future re-introduction still updates it.
    if (el.micNote) el.micNote.textContent = hp
      ? '🎧 raw mic: backing voices stay at constant volume while you sing.'
      : '🔊 speaker mode: echo cancellation on — the phone may duck the backing voices while you sing.';
    try {
      await TrainingScope.setMicProcessing(!hp);   // re-acquires the mic if it is live
      onMicChange();   // re-tap the (possibly re-acquired) mic into any recording (issue #67)
      if (TrainingScope.isMicOn()) {
        setStatus(hp
          ? 'Headphones mode: raw mic — backing voices stay at constant volume.'
          : 'Speaker mode: echo cancellation on — ducking may occur while you sing.');
      }
    } catch (e) {
      setStatus('Mic switch failed: ' + e.message);
    }
  }

  /* ---------- iOS audio diagnostics (issue #74) ------------------------ *
   * A field tool for the "crackle / silent-unless-mic during playback" reports
   * that reproduce only on a real iPhone. Everything here is INERT unless the
   * overlay is explicitly opened (?audiodebug=1 or a triple-tap on the status
   * line) EXCEPT two always-on, desktop-harmless resiliency hooks:
   *   - a 'statechange' listener that resumes the RAW context when iOS parks it
   *     in the non-standard 'interrupted' state (Tone's resume() only handles
   *     'suspended'; 'interrupted' never occurs off iOS — Tonejs/Tone.js#767);
   *   - a mediaDevices 'devicechange' listener that, while the mic is live and
   *     playback is stopped, rebuilds the graph so the next Play is born on the
   *     new route (a no-op off iOS, where routes don't flip under getUserMedia).
   * The event log is an in-memory ring buffer written unconditionally (so a
   * triple-tap mid-session already has history) but only RENDERED when open.
   * Zero console output, zero network, zero DOM churn unless opened — the
   * headless smoke test never touches the mic or the overlay, so CI is
   * byte-unchanged. The crown-jewel readout is the GRAPH-vs-SPEAKER
   * discriminator (masterOutputLevel): non-zero graph output during a reported
   * silence => route/session-level (use "Recreate ctx"); ~zero => graph-level.
   */
  const AD_MAX_EVENTS = 90;
  let adEvents = [];
  let adEnabled = false;
  let adEls = null;
  let adPoll = 0;
  let adListenerCtx = null;
  let adClockLast = null, adWallLast = null, adStalls = 0, adRatio = 1;
  let adGraphPeakMax = 0;   // max master-output peak seen while the overlay is open

  function rawCtx() {
    try { return (typeof Tone !== 'undefined' && Tone.getContext) ? Tone.getContext().rawContext : null; }
    catch (e) { return null; }
  }
  function ctxSampleRate() { const c = rawCtx(); return c ? c.sampleRate : null; }
  function audioDebugEnabled() { return adEnabled; }
  function nowStamp() {
    const d = new Date();
    return d.toLocaleTimeString('en-GB', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0');
  }
  function logAudioEvent(type, data) {
    adEvents.push({ stamp: nowStamp(), type, data: data == null ? null : data });
    if (adEvents.length > AD_MAX_EVENTS) adEvents.shift();
    if (adEnabled) renderAudioDebug();
  }

  // A fresh AudioContext is born at the CURRENT preferred hardware rate, so
  // comparing it to Tone's live (possibly stale) context rate reveals an iOS
  // route mismatch even when Safari's getSettings() omits the mic sampleRate.
  // Created + closed immediately to spare iOS's per-page context budget. Issue
  // #74 F2: now also called unconditionally on iOS from every mic toggle (on
  // AND off) — a throwaway context per toggle is well inside that budget — so
  // the auto-recreate path below has real hardware-rate data even when the
  // debug overlay was never opened. Off iOS it stays gated behind the debug
  // flag / the "HW rate" button, unchanged.
  function probeHardwareRate() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    let probe = null, rate = null;
    try { probe = new AC(); rate = probe.sampleRate; } catch (e) { rate = null; }
    finally { if (probe && probe.close) { try { probe.close(); } catch (e) { /* ignore */ } } }
    return rate;
  }

  // F2 (issue #74 follow-up): promote sample-rate-mismatch detection from
  // log-only to ACTION. rebuildAudioForMic only rebuilds the Tone graph on
  // the SAME (stale-rate) AudioContext, which is why the crackle survived it
  // (WebKit #154538 — the fix needs a genuinely new context, born at the
  // current hardware rate). Guarded to the STOPPED transport only ("never
  // yank a running transport" — recreateAudioContext() would cut live sound)
  // and to at most one recreate in flight at a time (autoRecreateBusy),
  // so a rapid double mic-toggle can't pile up overlapping recreates/loops.
  let autoRecreateBusy = false;
  async function autoRecreateForMismatch({ reason, mismatch, reacquireMic }) {
    if (!mismatch) return null;
    if (playState !== 'stopped') { logAudioEvent('recreate-deferred', { reason }); return null; }
    if (autoRecreateBusy) { logAudioEvent('auto-recreate-skip', { reason, why: 'already in flight' }); return null; }
    autoRecreateBusy = true;
    try {
      // The OLD mic (if any) lives on the OLD context — drop it before
      // recreating (mirrors onRecreateCtx, the manual fallback below), then
      // re-acquire on the NEW context only if this toggle wanted the mic on.
      const hadMic = TrainingScope.isMicOn();
      if (hadMic) {
        try { TrainingScope.micStop(); } catch (e) { /* ignore */ }
        el.micBtn.classList.remove('on'); el.micBtn.textContent = '🎤 Mic';
        onMicChange();
      }
      logAudioEvent('auto-recreate:start', { reason, hadMic });
      const r = await recreateAudioContext();
      logAudioEvent('auto-recreate', { ...(r || {}), reason });
      if (r && r.ok && reacquireMic) {
        try {
          logAudioEvent('audiosession-set', setAudioSessionType('play-and-record', 'auto-recreate:mic-reacquire'));
          await TrainingScope.setMicProcessing(!el.hpMode.checked);
          await TrainingScope.micStart(Tone.getContext().rawContext);
          el.micBtn.classList.add('on'); el.micBtn.textContent = '🎤 On';
          onMicChange();
          logAudioEvent('auto-recreate:mic-reacquired', {});
        } catch (e) {
          logAudioEvent('auto-recreate:mic-reacquire-failed', { error: (e && e.message) || String(e) });
          setStatus('Audio engine recreated, but the mic could not reconnect: ' + ((e && e.message) || e));
        }
      }
      return r;
    } finally {
      autoRecreateBusy = false;
    }
  }

  function audioSnapshot() {
    const info = audioContextInfo() || {};
    let mic = null;
    try { mic = (window.TrainingScope && TrainingScope.getMicSettings) ? TrainingScope.getMicSettings() : null; }
    catch (e) { mic = null; }
    const lvl = masterOutputLevel();
    const su = silentUnlockState();
    let detector = null;
    try { detector = (window.TrainingScope && TrainingScope.detectorInfo) ? TrainingScope.detectorInfo() : null; }
    catch (e) { detector = null; }
    let audioSessionType = null;
    if (audioSessionSupported()) { try { audioSessionType = navigator.audioSession.type; } catch (e) { /* ignore */ } }
    return {
      ios: isIOS(),
      playState,
      micOn: !!(window.TrainingScope && TrainingScope.isMicOn && TrainingScope.isMicOn()),
      hpMode: !!(el.hpMode && el.hpMode.checked),
      sampleRate: info.sampleRate ?? null,
      state: info.state ?? null,
      baseLatency: info.baseLatency ?? null,
      outputLatency: info.outputLatency ?? null,
      lookAhead: info.lookAhead ?? null,
      // Scope display-sync compensation (seconds) — what the singscope
      // subtracts from Transport.seconds so the lane tracks AUDIBLE audio.
      displayLatency: getDisplayLatency(),
      scopeSyncMs: getScopeSyncMs(),        // manual nudge portion of the above
      detector: (window.TrainingScope && TrainingScope.getDetector) ? TrainingScope.getDetector() : null,
      micRate: mic && mic.sampleRate != null ? mic.sampleRate : null,
      echoCancellation: mic && mic.echoCancellation != null ? mic.echoCancellation : null,
      noiseSuppression: mic && mic.noiseSuppression != null ? mic.noiseSuppression : null,
      graphRms: lvl.rms,
      graphPeak: lvl.peak,
      graphPeakMax: adGraphPeakMax,
      // F1/F4 (issue #74 follow-up): which session-management strategy is
      // actually active, and the live navigator.audioSession.type when F1 is
      // in effect (null = unsupported engine, e.g. every non-Safari browser).
      audioSessionSupported: audioSessionSupported(),
      audioSessionType,
      silentStrategy: su.strategy,
      silentUnlock: su.engaged,
      silentPlaying: su.playing,
      clockRatio: +adRatio.toFixed(2),
      stalls: adStalls,
      volume: getVolume(),
      detector,
      // Tone Transport scheduler snapshot + recovery flags (choir-training
      // background/interruption hang): a wedged worker reads state='started'
      // with seconds frozen while ctx.state='running'.
      transport: transportInfo(),
      recovery: contextRecoveryState(),
    };
  }

  function fmtVal(v) {
    if (v == null) return '—';
    if (typeof v === 'number' && !Number.isInteger(v)) return v.toFixed(v < 1 ? 4 : 2);
    return String(v);
  }
  function formatStats(s) {
    const rateMismatch = (s.sampleRate != null && s.micRate != null && s.sampleRate !== s.micRate);
    // Graph-vs-speaker discriminator verdict (only meaningful while playing).
    let verdict = '(play to test)';
    if (s.playState === 'playing') {
      verdict = (s.graphPeakMax > 0.0005)
        ? 'graph PRODUCING → if silent, it is ROUTE/SESSION level (try Recreate ctx)'
        : 'graph ~SILENT → scheduling/graph level (not route)';
    }
    // F1: when the Audio Session API is in play, its override wins over
    // everything else (design doc §0) — report the CONFIRMED type rather than
    // an inference. Otherwise fall back to the pre-F1 inference from mic/
    // silent-unlock state.
    const session = s.audioSessionType ? `override: ${s.audioSessionType}`
      : (s.micOn ? 'play-and-record (mic, inferred)'
        : (s.silentUnlock ? 'media/playback (silent-unlock, inferred)' : 'ambient/default (inferred)'));
    // F4: the "(not playing!)" alarm only means anything for the legacy
    // silent-element strategy — on audioSession-api (≥16.4) the element is
    // never engaged at all, by design, so a paused/absent element there is
    // NOT a fault.
    const silentWarn = (s.ios && s.silentStrategy === 'silent-element' && !s.silentPlaying) ? ' (not playing!)' : '';
    // Pitch detector A/B line (issue #80): which front-end is live + its cadence.
    const d = s.detector;
    const detLine = d
      ? `detector = ${d.mode}${d.mode === 'wasm' ? (d.wasmReady ? ' (worklet live)' : ' (loading…)') : ''}   ` +
        `cadence = ${d.cadenceHz != null ? d.cadenceHz.toFixed(1) : '—'} Hz   ` +
        `latency≈ ${d.latencyMs != null ? d.latencyMs.toFixed(1) : '—'} ms   ` +
        `frames = ${d.framesSeen} (voiced ${d.voicedFrames})` +
        (d.lastError ? `   ⚠ ${d.lastError}` : '')
      : 'detector = —';
    return [
      `iOS=${s.ios}   play=${s.playState}   mic=${s.micOn ? 'ON' : 'off'}   hpMode=${s.hpMode ? 'on(raw)' : 'off(processed)'}`,
      detLine,
      `ctx.sampleRate = ${fmtVal(s.sampleRate)} Hz    state = ${fmtVal(s.state)}`,
      `mic.sampleRate = ${fmtVal(s.micRate)} Hz${rateMismatch ? '  ⚠ RATE MISMATCH' : ''}    echoCancel = ${fmtVal(s.echoCancellation)}`,
      `baseLatency = ${fmtVal(s.baseLatency)}    outputLatency = ${fmtVal(s.outputLatency)}    lookAhead = ${fmtVal(s.lookAhead)}`,
      `scope sync comp = ${s.displayLatency != null ? Math.round(s.displayLatency * 1000) : '—'} ms  (auto ${s.displayLatency != null ? Math.round(s.displayLatency * 1000) - (s.scopeSyncMs || 0) : '—'} + manual ${s.scopeSyncMs || 0}; +ms = lane later — set via ?scopelag=MS)`,
      `session (inferred) = ${session}    unlock strategy = ${s.silentStrategy}${silentWarn}`,
      `GRAPH OUTPUT  rms=${fmtVal(s.graphRms)}  peak=${fmtVal(s.graphPeak)}  peakMax=${fmtVal(s.graphPeakMax)}`,
      `→ ${verdict}`,
      `clock health = ${fmtVal(s.clockRatio)}x wall   ·   stalls = ${s.stalls}   ·   volume = ${Math.round(s.volume * 100)}%`,
      `TRANSPORT ${s.transport ? `${s.transport.state} @ ${fmtVal(s.transport.seconds)}s  clock=${fmtVal(s.transport.clockSource)}` : '—'}` +
        `${s.recovery ? `   ·   recovery pending=${s.recovery.pending} recreated=${s.recovery.lastRecreated} watchdog=${s.recovery.watchdogRecovered}` : ''}`,
    ].join('\n');
  }
  function fmtEvent(e) {
    let d = '';
    if (e.data) {
      d = ' ' + Object.keys(e.data).map((k) => {
        const v = e.data[k];
        return `${k}=${v == null ? '—' : (typeof v === 'object' ? JSON.stringify(v) : v)}`;
      }).join(' ');
    }
    return `${e.stamp}  ${e.type}${d}`;
  }

  function renderAudioDebug() {
    if (!adEnabled || !adEls) return;
    adEls.stats.textContent = formatStats(audioSnapshot());
    adEls.log.textContent = adEvents.map(fmtEvent).join('\n');
  }

  // Underrun proxy: while running, the audio clock should advance ~1:1 with wall
  // time; a large shortfall over a poll interval is a stall/interruption signal.
  function sampleClockHealth() {
    const ctx = rawCtx();
    if (!ctx) return;
    const wall = performance.now() / 1000;
    const ac = ctx.currentTime;
    if (adClockLast != null) {
      const dWall = wall - adWallLast;
      const dAudio = ac - adClockLast;
      if (dWall > 0.05) {
        adRatio = dAudio / dWall;
        if (ctx.state === 'running' && adRatio < 0.5) {
          adStalls++;
          logAudioEvent('clock-stall', { ratio: +adRatio.toFixed(2) });
        }
      }
    }
    adClockLast = ac; adWallLast = wall;
    // Track peak master output so a transient chant note registers even between
    // poll ticks (reset whenever a fresh Play starts — see the poll's playState).
    if (playState === 'playing') {
      const lvl = masterOutputLevel();
      if (lvl.peak != null && lvl.peak > adGraphPeakMax) adGraphPeakMax = lvl.peak;
    }
  }

  function enableAudioDebug() {
    if (adEnabled) return;
    const box = document.getElementById('audioDebug');
    if (!box) return;
    adEls = { box, stats: document.getElementById('adStats'), log: document.getElementById('adLog') };
    box.hidden = false;
    adEnabled = true;
    adClockLast = null; adWallLast = null; adGraphPeakMax = 0;
    logAudioEvent('diagnostics-opened', { ua: (navigator.userAgent || '').slice(0, 64) });
    attachContextListeners();   // (re)bind in case the context was created after boot
    renderAudioDebug();
    clearInterval(adPoll);
    adPoll = setInterval(() => { sampleClockHealth(); renderAudioDebug(); }, 400);
  }
  function disableAudioDebug() {
    adEnabled = false;
    clearInterval(adPoll); adPoll = 0;
    const box = document.getElementById('audioDebug');
    if (box) box.hidden = true;
  }
  function toggleAudioDebug() { adEnabled ? disableAudioDebug() : enableAudioDebug(); }

  function buildAudioReport() {
    return [
      'ChanterLab iOS audio diagnostics (issue #74)',
      'when: ' + new Date().toISOString(),
      'ua: ' + (navigator.userAgent || ''),
      'dpr: ' + (window.devicePixelRatio || 1),
      '',
      formatStats(audioSnapshot()),
      '',
      'events (oldest first):',
      ...adEvents.map(fmtEvent),
    ].join('\n');
  }
  function flashCopy(msg) {
    const b = document.getElementById('adCopy');
    if (!b) return;
    const old = b.textContent; b.textContent = msg;
    setTimeout(() => { b.textContent = old; }, 1200);
  }
  async function copyAudioReport() {
    const text = buildAudioReport();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); }
      else { throw new Error('no clipboard API'); }
      flashCopy('copied ✓');
    } catch (e) {
      // iOS/older-Safari fallback: a temporary textarea + execCommand('copy').
      try {
        const ta = document.createElement('textarea');
        ta.value = text; ta.setAttribute('readonly', '');
        ta.style.position = 'absolute'; ta.style.left = '-9999px';
        document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, text.length);
        document.execCommand('copy');
        document.body.removeChild(ta);
        flashCopy('copied ✓');
      } catch (e2) { flashCopy('copy failed'); }
    }
  }

  async function onRecreateCtx(latencyHint) {
    // The mic (if on) lives on the OLD context; drop it first so the owner
    // re-enables it cleanly on the fresh context.
    const hadMic = !!(window.TrainingScope && TrainingScope.isMicOn && TrainingScope.isMicOn());
    if (hadMic) {
      try { TrainingScope.micStop(); } catch (e) { /* ignore */ }
      el.micBtn.classList.remove('on');
      el.micBtn.textContent = '🎤 Mic';
      onMicChange();
    }
    logAudioEvent('recreate-ctx:start', { hadMic, latencyHint: latencyHint || 'default' });
    const r = await recreateAudioContext(latencyHint);
    adListenerCtx = null; attachContextListeners();   // rebind to the NEW context
    logAudioEvent('recreate-ctx:done', r);
    setStatus(r && r.ok
      ? `Audio context recreated (${r.before}→${r.after} Hz, buffer: ${r.latencyHint}). Press Play; re-enable the mic if you need it.`
      : `Recreate failed: ${(r && r.reason) || 'unknown'}`);
  }

  // Registered with transport.setOnContextRecreated: invoked (awaited) right
  // after the Play gesture recreates the AudioContext to recover from an iOS
  // interruption (choir-training bug). Rebinds the diagnostics statechange
  // listener to the fresh context and, if the mic was live on the now-defunct
  // old context, re-taps it on the new one — the same mic dance as onRecreateCtx
  // / autoRecreateForMismatch, minus the recreate itself (already done).
  async function reattachMicAfterRecreate(recreateResult) {
    adListenerCtx = null; attachContextListeners();   // rebind to the NEW context
    logAudioEvent('recover:ctx', recreateResult || {});
    const hadMic = !!(window.TrainingScope && TrainingScope.isMicOn && TrainingScope.isMicOn());
    if (!hadMic) return;
    try {
      try { TrainingScope.micStop(); } catch (e) { /* ignore — was on the dead context */ }
      logAudioEvent('audiosession-set', setAudioSessionType('play-and-record', 'recover:mic'));
      await TrainingScope.setMicProcessing(!el.hpMode.checked);
      await TrainingScope.micStart(Tone.getContext().rawContext);
      el.micBtn.classList.add('on'); el.micBtn.textContent = '🎤 On';
      onMicChange();
      logAudioEvent('recover:mic-reacquired', {});
    } catch (e) {
      logAudioEvent('recover:mic-reacquire-failed', { error: (e && e.message) || String(e) });
      setStatus('Audio recovered, but the mic could not reconnect: ' + ((e && e.message) || e));
    }
  }

  // iOS background/interruption recovery (choir-training bug): returning to the
  // foreground after backgrounding — or a bfcache restore — can leave the
  // AudioContext interrupted or its clock stalled even while state reads
  // 'running'. Mark it so the NEXT Play recreates the context in-gesture (see
  // transport.unlockAudio). markContextForRecovery is iOS-gated, so both
  // listeners are a complete no-op on desktop Chrome/Firefox.
  function attachInterruptionRecovery() {
    const mark = (reason) => {
      if (markContextForRecovery(reason)) {
        logAudioEvent('recover:mark', { reason, state: (audioContextInfo() || {}).state });
      }
    };
    try {
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') mark('visibilitychange');
      });
    } catch (e) { /* ignore */ }
    // pageshow.persisted = a bfcache restore (page + JS heap were frozen; audio
    // is definitely dead). Ordinary background/return is covered by
    // visibilitychange above; the plain initial pageshow is skipped so a fresh
    // load's first Play doesn't needlessly recreate.
    try {
      window.addEventListener('pageshow', (e) => { if (e && e.persisted) mark('pageshow-bfcache'); });
    } catch (e) { /* ignore */ }
  }

  function attachContextListeners() {
    const ctx = rawCtx();
    if (!ctx || ctx === adListenerCtx || !ctx.addEventListener) return;
    adListenerCtx = ctx;
    try {
      ctx.addEventListener('statechange', () => {
        logAudioEvent('statechange', { state: ctx.state });
        // Ignore statechanges from a context we've already recreated AWAY from:
        // recreateAudioContext() deliberately suspends the OLD context, and that
        // suspend must NOT re-flag recovery or fight the intentional teardown.
        // (rawCtx() is the LIVE Tone context; after a recreate this old listener
        // still fires but ctx !== rawCtx().)
        if (ctx !== rawCtx()) return;
        // iOS parks the context in the non-standard 'interrupted' state (and
        // sometimes 'suspended') on a route change / mic-session flip / phone
        // call / backgrounding. Tone's Context.resume() only handles 'suspended',
        // so resume the RAW context directly. Harmless when running; unreachable
        // off iOS. ALSO mark the context for a full recreate on the next Play
        // (choir-training background/interruption bug): a bare resume() can
        // leave the clock stalled — markContextForRecovery is iOS-gated, so this
        // is a no-op on desktop.
        if (ctx.state === 'interrupted') {
          markContextForRecovery('statechange:interrupted');
          try { ctx.resume && ctx.resume().catch(() => {}); } catch (e) { /* ignore */ }
        } else if (ctx.state === 'suspended') {
          markContextForRecovery('statechange:suspended');
          if (playState === 'playing') { try { ctx.resume && ctx.resume().catch(() => {}); } catch (e) { /* ignore */ } }
        }
      });
    } catch (e) { /* statechange unsupported — ignore */ }
  }
  function attachDeviceChange() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.addEventListener) return;
    try {
      navigator.mediaDevices.addEventListener('devicechange', () => {
        const micOn = !!(window.TrainingScope && TrainingScope.isMicOn && TrainingScope.isMicOn());
        logAudioEvent('devicechange', { micOn });
        if (micOn) { const r = rebuildAudioForMic('devicechange'); if (r && r.rebuilt) logAudioEvent('graph-rebuilt', r); }
      });
    } catch (e) { /* ignore */ }
  }
  let adTapTimes = [];
  function wireStatusTripleTap() {
    if (!el.status) return;
    el.status.addEventListener('click', () => {
      const now = performance.now();
      adTapTimes.push(now);
      adTapTimes = adTapTimes.filter((t) => now - t < 700);
      if (adTapTimes.length >= 3) { adTapTimes = []; toggleAudioDebug(); }
    });
  }
  function initAudioDebug() {
    attachContextListeners();
    attachDeviceChange();
    // iOS interruption / background recovery (choir-training bug): wire the
    // recover-on-next-Play machinery. The logger + mic-reattach callbacks let
    // transport.js surface recovery events in this overlay's ring and re-tap the
    // mic on a recreated context; the visibility/pageshow listeners flag the
    // context after a background return. All iOS-gated / no-op on desktop.
    setRecoveryLogger(logAudioEvent);
    setOnContextRecreated(reattachMicAfterRecreate);
    attachInterruptionRecovery();
    wireStatusTripleTap();
    const copy = document.getElementById('adCopy');
    const close = document.getElementById('adClose');
    const probe = document.getElementById('adProbe');
    const recreate = document.getElementById('adRecreate');
    if (copy) copy.addEventListener('click', copyAudioReport);
    if (close) close.addEventListener('click', disableAudioDebug);
    // The click event object must not become the latencyHint argument.
    if (recreate) recreate.addEventListener('click', () => onRecreateCtx());
    // Buffer-size experiment levers (owner field finding: iOS screen recording
    // silences the mic+speaker crackle — it forces larger system buffers, so
    // recreating with a fatter latencyHint should be the same medicine).
    const bufI = document.getElementById('adBufInteractive');
    const bufB = document.getElementById('adBufBalanced');
    const bufP = document.getElementById('adBufPlayback');
    if (bufI) bufI.addEventListener('click', () => onRecreateCtx('interactive'));
    if (bufB) bufB.addEventListener('click', () => onRecreateCtx('balanced'));
    if (bufP) bufP.addEventListener('click', () => onRecreateCtx('playback'));
    if (probe) probe.addEventListener('click', () => {
      const hw = probeHardwareRate();
      const info = audioContextInfo() || {};
      logAudioEvent('hw-probe', { hwRate: hw, ctxRate: info.sampleRate, mismatch: !!(hw && info.sampleRate && hw !== info.sampleRate) });
    });
    if (new URLSearchParams(location.search).get('audiodebug') === '1') enableAudioDebug();
  }

  // Reflect the two persisted timing latencies onto their sliders + readouts.
  function updateTimingUI() {
    const outMs = getScopeSyncMs();
    if (el.scopeSync) el.scopeSync.value = String(outMs);
    if (el.scopeSyncOut) el.scopeSyncOut.textContent = (outMs > 0 ? '+' : '') + outMs + ' ms';
    const inMs = getResponseLatencyMs();
    if (el.responseLag) el.responseLag.value = String(inMs);
    if (el.responseOut) el.responseOut.textContent = inMs + ' ms';
  }

  // The scoring pitch-sink (issue #49) as a named installer so the calibration
  // wizard (js/calibrate.js) can borrow the single sink and reinstate this one.
  function installScoringSink() {
    if (!(window.TrainingScope && TrainingScope.setPitchSink)) return;
    TrainingScope.setPitchSink((s) => {
      if (playState !== 'playing') return;
      if (s.tSec == null || !isFinite(s.tSec)) return;
      practiceSamples.push({ tSec: s.tSec, midi: s.midi });
    });
  }

  async function main() {
    loadStrictness();
    loadInstrumentMode();   // restores the toggle position only — never fetches
                            // samples at boot (issue #66); see loadInstrumentMode.
    loadVolume();           // master accompaniment volume (issue #74 F5) — restores
                            // the persisted level only; buildAudio applies it.
    initControls();
    updateStrictnessUI();
    updateInstrumentUI();
    updateVolumeUI();
    // F1 (issue #74 follow-up): pin the AVAudioSession category via the Audio
    // Session API where supported (Safari ≥16.4) so mic-off playback always
    // lands in plain media/playback — see docs/design/IOS-AUDIO-SESSION-
    // ANALYSIS.md §3 F1. Feature-detected no-op everywhere else (desktop
    // Chrome/Firefox, older Safari) — logged to the ring regardless so a
    // triple-tap later still shows the boot-time attempt.
    if (isIOS()) logAudioEvent('audiosession-set', setAudioSessionType('playback', 'boot'));
    initLibrary();
    initSections();
    initScopeVerdicts();  // scope-lane verdict tints (issue #60 phase 2) — rides
                          // the 'chanterlab:scorecoloring' event; no DOM of its own.
    initRecording();    // in-app practice recording (issue #67) — wires the ⏺ toggle,
                        // the Voice/Music balance slider, and the master-rebuild re-tap
                        // hook; builds NO audio graph until the first Record.
    initTour();         // interactive guided tour — wires the header ? menu + the
                        // overlay controls; auto-start is decided after first paint.
    initCalibrate({     // timing wizard (js/calibrate.js): borrows the pitch sink,
                        // so hand it these to restore scoring + turn on the mic.
      restoreScoringSink: installScoringSink,
      requestMic: async () => { if (!(window.TrainingScope && TrainingScope.isMicOn())) await toggleMic(); },
      refreshTimingUI: updateTimingUI,
    });
    // Kicked off now (parallel with everything below) but AWAITED just before
    // loadStartingPiece — issue #64's default-piece choice needs to know
    // whether the manifest actually loaded and lists the preferred piece. It's
    // a local, fast fetch (or an instant 404 on every CI/fresh-clone
    // checkout — the manifest is gitignored), so this adds negligible latency
    // to the critical path and none at all on the no-manifest path beyond the
    // 404 round-trip that already happened unconditionally before.
    const manifestReady = loadLibraryManifest();
    initOverlay();
    initAudioDebug();   // iOS audio diagnostics (issue #74) — inert unless opened
                        // via ?audiodebug=1 or a triple-tap on the status line.
    initKeys();         // desktop keyboard shortcuts (Calm Surface #73/§5) — active at
                        // all widths, harmless on mobile (no hardware keyboard).
    setView('split');
    updatePlayUI();
    setOverlay(true);
    // Mobile cold-load: collapse the transport so the score is visible on first
    // paint — the expanded controls otherwise cover the whole sheet on a phone.
    // setOverlay(false) is the transport's own collapse API (toggles .collapsed);
    // the always-visible mini-row (Play/Stop/position) stays reachable.
    if (window.matchMedia && window.matchMedia('(max-width:759px)').matches) setOverlay(false);
    if (window.TrainingScope && el.scope) {
      // Detector selection (issue #80). The Rust/WASM worklet is now the
      // DEFAULT; opt back to the JS autocorrelation path with ?detector=js or a
      // persisted localStorage['chanterlab.detector']='js'. Setting the mode
      // here with the mic off only records the preference — no wasm fetch until
      // mic-on (scope.micStart), where a load failure (e.g. the gitignored
      // pkg-worklet artifact absent on a fresh deploy) falls back to JS
      // automatically. So a fresh checkout / CI (mic never on) never fetches it.
      if (TrainingScope.setDetector) {
        let detFlag = new URLSearchParams(location.search).get('detector');
        if (!detFlag) { try { detFlag = localStorage.getItem('chanterlab.detector'); } catch (e) { detFlag = null; } }
        TrainingScope.setDetector(detFlag === 'js' ? 'js' : 'wasm');
      }
      // Scope-sync manual calibration: ?scopelag=MS sets the persisted per-device
      // nudge on top of the auto latency estimate (positive = lane later, the
      // fix for residual earliness). Set once; it sticks across reloads.
      const lagFlag = new URLSearchParams(location.search).get('scopelag');
      if (lagFlag != null && lagFlag !== '' && isFinite(parseFloat(lagFlag))) {
        setScopeSyncMs(parseFloat(lagFlag));
      }
      // Voice-response latency (L_in): ?responselag=MS overrides the persisted
      // value, then push it into the scope so the trace + scoring stamp are
      // back-dated. Mirrors ?scopelag for the input side.
      const respFlag = new URLSearchParams(location.search).get('responselag');
      if (respFlag != null && respFlag !== '' && isFinite(parseFloat(respFlag))) {
        setResponseLatencyMs(parseFloat(respFlag));
      }
      if (TrainingScope.setInputLatency) TrainingScope.setInputLatency(getResponseLatencySec());
      updateTimingUI();
      TrainingScope.attach(el.scope, el.scopeReadout, el.scopeHint);
      TrainingScope.setTimeSource(() => ({
        playing: playState === 'playing',
        // keep the lane frozen in place while paused (t survives the pause).
        // Output-latency compensation (owner report: scope leads the audible
        // audio): Transport.seconds is schedule-domain; what's AUDIBLE now was
        // scheduled getDisplayLatency() ago, so shift the display time back by
        // it. This is the ONE crossing from audio-schedule domain to display
        // domain — the target lane, the active-target glow, and the scoring
        // tSec stamp all read this t, so all three stay mutually consistent
        // (and scoring samples land nearer the note the singer actually heard).
        // getDisplayLatency() is always finite (0 fallback) — t is never NaN.
        // Slightly negative t right after Play is correct: nothing is audible
        // yet, so the lane sits just right of the now line until sound lands.
        t: playState === 'stopped' ? null : Tone.Transport.seconds - getDisplayLatency(),
      }));
      // Scoring tap (#49): collect the live voiced-pitch stream ONLY while
      // actively playing with the mic on. Nothing accrues otherwise, so the
      // scoring path is entirely free when the mic is off. Named + reinstalled
      // via installScoringSink so the calibration wizard can borrow the sink and
      // hand it back (js/calibrate.js).
      installScoringSink();
    }
    await manifestReady;
    await loadStartingPiece();
    // First-run walkthrough — only now the score has painted, so the tour's
    // spotlight lands on real, laid-out controls. Suppressed for returning
    // visitors and WebDriver/headless browsers (see maybeAutoStartTour), so
    // this never drives the CI smoke test into an open overlay.
    maybeAutoStartTour();
  }

  // Tiny debug/verification hook (used by the headless checks; harmless in prod).
  window.__training = {
    gains: () => gains.map((g) => g.gain.value),
    playState: () => playState,
    // Post-Play assertion for tests (issue #63): Tone AudioContext state —
    // 'running' after a successful unlock, 'suspended' if the browser's
    // autoplay policy still blocked it (the "Tap again" case).
    audioContextState: () => audioContextState(),
    // --- iOS interruption / background recovery (choir-training bug) ---
    // audioRecovery(): recovery-flag snapshot — { ios, pending, reason,
    // lastRecreated, watchdogRecovered, testForced }.
    audioRecovery: () => contextRecoveryState(),
    // transportInfo(): live scheduler snapshot — { state, seconds, clockSource,
    // ctxState }. The dead-worker hang shows as state='started' + frozen seconds
    // while ctxState='running'.
    transportInfo: () => transportInfo(),
    // markAudioRecovery(reason): force the "recover on next Play" flag (the same
    // thing the visibilitychange listener does). iOS-gated unless
    // forceAudioRecoveryPath is on; returns whether the mark took.
    markAudioRecovery: (reason) => markContextForRecovery(reason || 'test'),
    // forceAudioRecoveryPath(on): TEST-ONLY — take the iOS resume-or-recreate
    // path on desktop Chromium so a headless probe can drive the full
    // recreate→rebuild→reschedule→start chain (a real 'interrupted' state is
    // iOS-only). Returns the resulting override state.
    forceAudioRecoveryPath: (on) => setRecoveryTestOverride(on),
    // --- iOS audio diagnostics (issue #74) ---
    // audioDebug(): full snapshot + the in-memory event log (for headless
    // verification that events are logged with a fake mic). audioDebugShow/Hide
    // drive the overlay the same way ?audiodebug=1 / triple-tap do.
    audioDebug: () => ({ enabled: adEnabled, snapshot: audioSnapshot(), events: adEvents.slice() }),
    audioDebugShow: () => { enableAudioDebug(); return adEnabled; },
    audioDebugHide: () => { disableAudioDebug(); return adEnabled; },
    // Scope display-sync compensation (seconds; always finite, >= 0) — the
    // amount setTimeSource subtracts from Transport.seconds. Exposed so the
    // smoke test / on-device console can assert the offset math cheaply.
    displayLatency: () => getDisplayLatency(),
    // Manual per-device scope-sync nudge (ms). setScopeLatency(120) pushes the
    // target lane 120ms later; persists. Same as ?scopelag=120. For dialing in
    // the last few tens of ms of alignment by eye on-device.
    setScopeLatency: (ms) => setScopeSyncMs(ms),
    scopeLatency: () => getScopeSyncMs(),
    // Voice-response latency L_in (ms) — back-dates the sung trace + scoring
    // stamp so a note sung on the audible beat scores on that note. setter
    // live-applies to the scope + persists; same as ?responselag=MS.
    inputLatency: () => getResponseLatencyMs(),
    setInputLatency: (ms) => {
      const v = setResponseLatencyMs(ms);
      if (window.TrainingScope && TrainingScope.setInputLatency) TrainingScope.setInputLatency(v / 1000);
      updateTimingUI();
      return v;
    },
    // --- pitch-detector A/B (issue #80) ---
    // detector(): which front-end is live ('js'|'wasm') plus its live cadence,
    // latency proxy, and frame counters — the console-visible A/B hook.
    detector: () => (window.TrainingScope && TrainingScope.detectorInfo) ? TrainingScope.detectorInfo() : null,
    setDetector: (m) => (window.TrainingScope && TrainingScope.setDetector) ? TrainingScope.setDetector(m) : null,
    // --- master accompaniment volume (issue #74 F5) ---
    // volume(): current level (0..1.25). setVolume(v): live-applies + persists,
    // returns the (clamped) resulting level — mirrors setInstrument's pattern.
    volume: () => getVolume(),
    setVolume: (v) => setVolume(v),
    holdRemaining: () => Math.max(0, userHoldUntil - performance.now()),
    viewMode: () => viewMode,
    cursorStep: () => cursorStep,
    osmdSteps: () => osmdSteps.map((s) => ({ beat: s.beat, measure: s.measure })),
    parsedNoteCounts: () => (parsed ? parsed.parts.map((p) => p.notes.length) : []),
    parsed: () => parsed,
    zoom: () => (osmd ? osmd.zoom : null),

    // --- verse toggle (multi-verse lyrics) ---
    verse: () => activeVerse,
    setVerse: (v) => { setVerse(v); return activeVerse; },
    maxVerse: () => (parsed ? (parsed.maxVerse || 1) : 1),

    // --- per-note scoring (Scoring v1, issue #55) ---
    // lastScore(): the latest scored lap (result + {lap,best}) with a laps[]
    // array of every lap this session alongside it (null before any run).
    lastScore: () => lastScoreResult,
    // scoreLaps(): every scored lap this play session, oldest first.
    scoreLaps: () => sessionLaps.slice(),
    // scoreCore(): the pure scorer, for tests (delegates to ChanterScoring).
    scoreCore: (targets, samples, opts) =>
      (window.ChanterScoring ? window.ChanterScoring.scoreNotes(targets, samples, opts) : null),
    // introspection: the current loop's targets + the CURRENT lap's collected
    // sample stream (reset at every lap boundary — see onLapWrap).
    scoreTargets: () => buildScoreTargets(),
    practiceSamples: () => practiceSamples.slice(),
    scoreHistory: () => {
      try { return JSON.parse(localStorage.getItem(PRACTICE_HISTORY_KEY) || '[]'); }
      catch (e) { return []; }
    },
    // strictness preset: 'relaxed' (default) or 'strict' — persisted.
    strictness: () => scoringStrictness,
    setStrictness: (s) => { setStrictness(s); return scoringStrictness; },

    // --- per-note score coloring (issue #79) ---
    // scoreColoring(): current overlay state — { on, applied, matched, painted,
    // targets, from, to, colors } (colors = the NoteheadColor of each scored-
    // voice note in the covered range, so a test can count the verdict tints).
    scoreColoring: () => scoreColoringInfo(),
    // toggleScoreColoring(): drive the report's "Show on score" chip
    // programmatically; returns the resulting scoreColoring() snapshot.
    toggleScoreColoring: () => { toggleScoreColoring(); return scoreColoringInfo(); },
    // scopeVerdicts(): the scope-lane half of the overlay (issue #60 phase 2) —
    // { on, applied, painted, targets, tints } where tints[] is each lane
    // note's current color (null = plain gold).
    scopeVerdicts: () => scopeVerdictsInfo(),
    // renderCount(): monotonically-increasing renderNow() count — lets a test
    // assert exactly one render happened across a toggle.
    renderCount: () => renderCount,

    // --- instrument sound: Synth / Voices (issue #66) ---
    // instrument(): the CURRENTLY EFFECTIVE setting ('synth' default, 'voices'
    // once samples are switched to/loaded and usable — see transport.js's
    // effectiveMode fallback-on-failure behavior).
    instrument: () => instrumentMode,
    // setInstrument(): drives the same async switch the Sound toggle does
    // (persists + lazy-loads + rebuilds live audio); awaits it so a test can
    // reliably check instrument() right after.
    setInstrument: async (mode) => { await switchInstrumentMode(mode); return instrumentMode; },
    // captureOfflineAB(): dev/verification-only — renders the CURRENT loop
    // range through both instrument paths via Tone.Offline (headless-safe,
    // no audio device needed) and returns base64 16-bit PCM for each side.
    // The app itself never calls this.
    captureOfflineAB: (fromMeasure, toMeasure, bpm) => captureOfflineAB(fromMeasure, toMeasure, bpm),
    // --- practice transpose (semitones) ---
    // transpose(): the current shift; setTranspose(n): drives the SAME path
    // as the ± buttons (clamp, lane rebuild, mid-play restart) so a headless
    // test exercises the real propagation, not just the state variable.
    // scoreTargets(): the loop window's scoring targets as the scorer will
    // see them — lets a test assert the midi shift lands in scoring.
    transpose: () => transposeSemitones,
    setTranspose: (n) => applyTranspose(n),
    scoreTargets: () => buildScoreTargets(),
    // Test-only pitch injection: headless checks (and any dev box without a
    // real mic) have no way to drive TrainingScope's actual pitch detector,
    // so this pushes straight into the CURRENT lap's sample buffer exactly as
    // the real pitch sink does (see main()'s setPitchSink), letting a test
    // exercise the real lap-scoring/report code against synthetic samples.
    // No-op while not playing; never called by the app itself.
    injectSample: (tSec, midi) => {
      if (playState !== 'playing') return false;
      practiceSamples.push({ tSec, midi });
      return true;
    },

    // --- windowed-render + seek machinery (for a future "jump to section" UI) ---
    // Current render window as printed measure numbers + whether the piece is
    // windowed at all.
    windowInfo: () => ({
      windowed,
      sourceMeasureCount,
      lastPrinted,
      fromIdx: renderFromIdx,
      toIdx: renderToIdx,
      fromPrinted: (osmd && osmd.Sheet) ? printedForIndex(renderFromIdx) : null,
      toPrinted: (osmd && osmd.Sheet) ? printedForIndex(renderToIdx) : null,
    }),
    // Low-level: render whatever window is needed to cover [fromPrinted,toPrinted].
    ensureWindow: (fromPrinted, toPrinted) => ensureRenderWindow(fromPrinted, toPrinted),
    // High-level "jump to section": render the range, set the loop inputs to it,
    // refresh the scope, and scroll the score to the target. Everything a
    // jump-to-section button needs.
    seekTo: (fromPrinted, toPrinted) => {
      const to = toPrinted != null ? toPrinted : fromPrinted;
      ensureRenderWindow(fromPrinted, to);
      el.loopFrom.value = Math.max(1, Math.round(fromPrinted) || 1);
      el.loopTo.value = Math.max(Number(el.loopFrom.value), Math.round(to) || Number(el.loopFrom.value));
      buildScopeLane();
      return true;
    },
    renderFull: () => renderFullScore(),
    // printed -> source index and back (the map a jump UI would consult)
    printedToIndex: (p) => indexFromPrinted(p),
    indexToPrinted: (idx) => printedForIndex(idx),

    // --- jump-to-section (headless checks) ---
    sections: () => currentSections.map((s) => ({ title: s.title, measure: s.measure })),
    jumpToSection: (i) => jumpToSection(i),
    activeSection: () => activeSectionIdx,
    xmlSections: () => xmlScannedSections.map((s) => ({ title: s.title, measure: s.measure })),

    // --- in-app practice recording (issue #67) ---
    // recording(): full recorder state snapshot (support, live flag, mic flag,
    // elapsedMs, negotiated mimeType + candidate-support matrix, balance + the
    // two leg gains, and the last clip's object URL / size / type / filename).
    recording: () => recordingState(),
    // start/stop the mixed-audio recorder (same path the ⏺ toggle drives).
    startRecording: () => startRecording(),
    stopRecording: () => stopRecording(),
    // set the Voice/Music RECORDING balance (0 = music only … 1 = voice only),
    // persisted; returns the fresh recording() snapshot for a test to assert on.
    setRecordBalance: (v) => { setBalance(v); return recordingState(); },
  };

  // Interactive guided-tour hook (headless checks + on-device console). start()
  // opens the walkthrough for the CURRENT viewport's device; next/prev/end drive
  // it; the getters expose which step of how many, the detected device, and the
  // active step-id list (mobile has one extra step — the ⌄ "open controls").
  window.__tour = {
    start: () => { startTour(); return tourState.isActive(); },
    next: () => { tourNext(); return tourState.index(); },
    prev: () => { tourPrev(); return tourState.index(); },
    end: () => { endTour(false); return tourState.isActive(); },
    isActive: () => tourState.isActive(),
    index: () => tourState.index(),
    count: () => tourState.count(),
    device: () => tourState.device(),
    steps: () => tourState.stepIds(),
  };

  // Timing-calibration hook. open/close drive the wizard modal; measureOffset is
  // the pure lag-sweep (samples, targets) → { deltaSec, matched } so a headless
  // test can verify it recovers a known synthetic offset without a real mic.
  window.__calibrate = {
    open: () => { openCalibrate(); return !el.calibrateOverlay.hidden; },
    close: () => { closeCalibrate(); return !!el.calibrateOverlay.hidden; },
    isOpen: () => !!(el.calibrateOverlay && !el.calibrateOverlay.hidden),
    measureOffset: (samples, targets, tol) => measureOffsetSec(samples, targets, tol),
  };

  // Programmatic library hook (headless tests). select() resolves either the
  // prefixed piece id ('ingest_<x>') or the bare manifest id ('<x>').
  window.__library = {
    open: () => openLibrary(),
    close: () => closeLibrary(),
    select: async (id) => {
      const rid = resolvePieceId(id);
      if (!rid) return null;
      await loadPieceById(rid);
      closeLibrary();
      return playState;
    },
    count: () => libProto.length + libItems.length,
    shown: () => libFlat.filter((f) => f.type === 'row').length,
    domRows: () => el.libViewport.childElementCount,
    isOpen: () => libOpen,
    // sectioned-UI introspection for the headless checks
    sections: () => libFlat.filter((f) => f.type === 'group')
      .map((f) => ({ group: f.group, count: f.count, collapsible: f.collapsible, expanded: f.expanded })),
    subs: () => libFlat.filter((f) => f.type === 'sub').map((f) => f.label),
    toggle: (group) => { toggleGroup(group); return libFlat.filter((f) => f.type === 'group' && f.group === group).map((f) => f.expanded)[0]; },
    collapsed: () => [...libCollapsed],
    toneFacets: () => libFacetDefs.tone.map((t) => t.value),
    scrollToGroup: (group) => {
      const i = libFlat.findIndex((f) => f.type === 'group' && f.group === group);
      if (i < 0) return false;
      el.libList.scrollTop = libOffsets[i];
      renderWindow(true);
      return true;
    },
  };

main();

