/* main.js — entry module: control wiring, mic, startup, and the
 * window.__training / window.__library test hooks assembled from the module
 * exports. Loaded as <script type="module"> (deferred), after the vendored
 * classic scripts (OSMD, Tone, scoring.js, scope.js) have defined their globals.
 */
import { el, setStatus, PIECES, PRACTICE_HISTORY_KEY } from './state.js';
import { parsed } from './model.js';
import {
  osmd, osmdSteps, viewMode, windowed, sourceMeasureCount, renderFromIdx, renderToIdx,
  lastPrinted, loadPieceById, loadStartingPiece, resolvePieceId, setView,
  applyResponsiveOsmdOptions, isNarrow, requestRender, renderFullScore,
  ensureRenderWindow, maybeExtendOnScroll, indexFromPrinted, printedForIndex,
} from './loader.js';
import {
  gains, playState, userHoldUntil, cursorStep, applyMix, statusForPlaying,
  startPlayback, stop, playPause, updatePlayUI, setOverlay, initOverlay, noteUserTouch,
  audioContextState, instrumentMode, loadInstrumentMode, switchInstrumentMode,
  updateInstrumentUI, captureOfflineAB,
} from './transport.js';
import {
  practiceSamples, lastScoreResult, sessionLaps, scoringStrictness, buildScoreTargets,
  setStrictness, loadStrictness, updateStrictnessUI, dismissReport,
} from './scoring-ui.js';
import {
  currentSections, activeSectionIdx, xmlScannedSections, jumpToSection, initSections,
} from './sections.js';
import { activeVerse, setVerse, buildScopeLane, updateVoiceChip } from './voices.js';
import {
  libProto, libItems, libFlat, libOffsets, libOpen, libFacetDefs, libCollapsed,
  loadLibraryManifest, openLibrary, closeLibrary, toggleGroup, renderWindow, initLibrary,
} from './library.js';
import { initOnboarding, markMicUsed } from './onboarding.js';
import {
  initRecording, startRecording, stopRecording, onMicChange, setBalance, recordingState,
} from './recording.js';

let resizeTimer = 0;
let loopRenderTimer = 0;   // debounce windowed re-render on loop-input edits

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
      if (playState === 'playing') { stop(); startPlayback(); }
      else if (playState === 'paused') stop();
    });
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
      return;
    }
    try {
      await Tone.start();                       // user gesture → audio context running
      // Headphones mode ON (default) = raw mic: echoCancellation OFF so the
      // phone can't duck the backing voices while you sing.
      await TrainingScope.setMicProcessing(!el.hpMode.checked);
      await TrainingScope.micStart(Tone.getContext().rawContext);
      el.micBtn.classList.add('on');
      el.micBtn.textContent = '🎤 On';
      onMicChange();   // fan the live mic into any active recording + relabel (issue #67)
      markMicUsed();   // first-run onboarding (issue #64): skip the mic nudge
      if (el.scopeHint) el.scopeHint.textContent = 'sing your gold line — cyan is you, gold glow = on the note (±50¢, any octave)';
      setStatus('Mic on — sing your part. Headphones avoid feedback from the other voices.');
    } catch (e) {
      setStatus('Mic unavailable: ' + e.message);
    }
  }

  async function onHeadphonesToggle() {
    const hp = el.hpMode.checked;
    el.micNote.textContent = hp
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

  async function main() {
    loadStrictness();
    loadInstrumentMode();   // restores the toggle position only — never fetches
                            // samples at boot (issue #66); see loadInstrumentMode.
    initControls();
    updateStrictnessUI();
    updateInstrumentUI();
    initLibrary();
    initSections();
    initRecording();    // in-app practice recording (issue #67) — wires the ⏺ toggle,
                        // the Voice/Music balance slider, and the master-rebuild re-tap
                        // hook; builds NO audio graph until the first Record.
    initOnboarding();   // first-run coach-marks (issue #64) — shows step (a) immediately
    // Kicked off now (parallel with everything below) but AWAITED just before
    // loadStartingPiece — issue #64's default-piece choice needs to know
    // whether the manifest actually loaded and lists the preferred piece. It's
    // a local, fast fetch (or an instant 404 on every CI/fresh-clone
    // checkout — the manifest is gitignored), so this adds negligible latency
    // to the critical path and none at all on the no-manifest path beyond the
    // 404 round-trip that already happened unconditionally before.
    const manifestReady = loadLibraryManifest();
    initOverlay();
    setView('split');
    updatePlayUI();
    setOverlay(true);
    // Mobile cold-load: collapse the transport so the score is visible on first
    // paint — the expanded controls otherwise cover the whole sheet on a phone.
    // setOverlay(false) is the transport's own collapse API (toggles .collapsed);
    // the always-visible mini-row (Play/Stop/position) stays reachable.
    if (window.matchMedia && window.matchMedia('(max-width:759px)').matches) setOverlay(false);
    if (window.TrainingScope && el.scope) {
      TrainingScope.attach(el.scope, el.scopeReadout, el.scopeHint);
      TrainingScope.setTimeSource(() => ({
        playing: playState === 'playing',
        // keep the lane frozen in place while paused (t survives the pause)
        t: playState === 'stopped' ? null : Tone.Transport.seconds,
      }));
      // Scoring tap (#49): collect the live voiced-pitch stream ONLY while
      // actively playing with the mic on. Nothing accrues otherwise, so the
      // scoring path is entirely free when the mic is off.
      TrainingScope.setPitchSink((s) => {
        if (playState !== 'playing') return;
        if (s.tSec == null || !isFinite(s.tSec)) return;
        practiceSamples.push({ tSec: s.tSec, midi: s.midi });
      });
    }
    await manifestReady;
    await loadStartingPiece();
  }

  // Tiny debug/verification hook (used by the headless checks; harmless in prod).
  window.__training = {
    gains: () => gains.map((g) => g.gain.value),
    playState: () => playState,
    // Post-Play assertion for tests (issue #63): Tone AudioContext state —
    // 'running' after a successful unlock, 'suspended' if the browser's
    // autoplay policy still blocked it (the "Tap again" case).
    audioContextState: () => audioContextState(),
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

