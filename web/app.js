import init, { JsTuningGrid } from './pkg/chanterlab_core.js';
import { ScaleLadder    } from './ui/scale_ladder.js?v=chant-script-engine-phase2f';
import { AudioEngine    } from './audio/audio_engine.js?v=0.2.0-alpha.0';
import { VKeyboard      } from './ui/vkeyboard.js?v=0.2.0-alpha.0';
import { Singscope      } from './ui/singscope.js?v=chant-script-engine-phase2f';
import { NoteIndicator  } from './ui/note_indicator.js?v=0.2.0-alpha.0';
import { ExerciseMode   } from './ui/exercise_mode.js?v=0.2.0-alpha.0';
import { PthoraPalette, buildQuickPthoraControls } from './ui/pthora_palette.js?v=0.2.0-alpha.0';
import { ShadingPalette, buildQuickShadingControls } from './ui/shading_palette.js?v=0.2.0-alpha.0';
import {
  compileChantScriptExample,
  listChantScriptExamples,
} from './score/examples.js?v=chant-script-engine-phase5j';
import {
  compileGlyphText,
  compileSbmuflGlyphText,
  compileUnicodeByzantineText,
  listMinimalGlyphImportTokens,
} from './score/glyph_import.js?v=chant-script-engine-phase6d';
import { formatDiagnostic } from './score/diagnostics.js?v=chant-script-engine-phase6d';
import {
  findGlyphImportSampleFixture,
  listGlyphImportSampleFixtures,
} from './score/glyph_import_samples.js?v=chant-script-engine-phase6d';
import {
  referenceMoriaForDegree,
} from './score/chant_score.js?v=chant-script-engine-phase5j';
import {
  ScorePracticePrototype,
  scorePracticeExplicitlyDisabled,
  scorePracticeIsonControlState,
} from './score/score_practice.js?v=chant-script-engine-phase5j';
import {
  applyPthoraDrop,
  retuneCompiledScoreWithGrid,
} from './score/tuning_context.js?v=chant-script-engine-phase5j';

// ── App state ────────────────────────────────────────────────────────────────

const PRESETS = [
  { label: 'Diatonic',      genus: 'Diatonic',      degree: 'Ni'  },
  { label: 'Hard Chromatic',genus: 'HardChromatic',  degree: 'Pa'  },
  { label: 'Soft Chromatic',genus: 'SoftChromatic',  degree: 'Ni'  },
  { label: 'Western',       genus: 'Western',       degree: 'Ni'  },
  { label: 'Grave Diatonic',genus: 'GraveDiatonic',  degree: 'Ga'  },
  { label: 'Enharmonic Zo', genus: 'EnharmonicZo',   degree: 'Zo'  },
  { label: 'Enharmonic Ga', genus: 'EnharmonicGa',   degree: 'Ga'  },
];

const DEFAULT_REF_NI_HZ = 130.81;
const APP_VERSION = '0.2.0-alpha.0';
const HELP_RELEASE_ID = APP_VERSION;
const SCORE_PRACTICE_CROSSHAIR_RATIO = 0.28;
const SCORE_PRACTICE_DEFAULT_PLAYBACK_RATE = 0.35;
const SCORE_PRACTICE_MIN_PLAYBACK_RATE = 0.15;
const SCORE_PRACTICE_MAX_PLAYBACK_RATE = 1.25;
const SCORE_PRACTICE_LEAD_IN_MS = 3000;
const SCORE_PRACTICE_SCROLL_PX_PER_SECOND = 56;
const SCORE_GLYPH_IMPORT_TOKENS = listMinimalGlyphImportTokens();
const SCORE_IMPORT_DEGREES = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo'];
const SCORE_GLYPH_KEYBOARD_ROLES = [
  { role: 'quantity', label: 'Quantity' },
  { role: 'rest', label: 'Rest' },
  { role: 'temporal', label: 'Timing' },
  { role: 'duration', label: 'Beats' },
  { role: 'pthora', label: 'Pthora' },
  { role: 'qualitative', label: 'Chroa' },
  { role: 'tempo', label: 'Tempo' },
];
const DETECTION_LOW_MORIA = -72;
const DETECTION_HIGH_MORIA = 144;
const REFERENCE_RANGE_OPTIONS = [
  { value: '110', label: 'Bass - Ni A2' },
  { value: '130.81', label: 'Baritone - Ni C3' },
  { value: '155.56', label: 'Tenor - Ni Eb3' },
  { value: '220', label: 'Female low - Ni A3' },
  { value: '261.63', label: 'Female mid - Ni C4' },
  { value: '311.13', label: 'Female high - Ni Eb4' },
  { value: 'custom', label: 'Custom' },
];
const RECORDING_MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/aac',
];
const RECORDING_TARGET_PEAK = 0.9;
const RECORDING_MAX_GAIN = 8;

const app = {
  grid:            null,
  ladder:          null,
  singscope:       null,
  noteIndicator:   null,
  exercise:        null,
  scorePractice:   null,
  engine:          null,
  keyboard:        null,
  activePresetIdx: 0,
  gridChanged:     null,
  refNiHz:         DEFAULT_REF_NI_HZ,
  // Ison state
  isonEnabled:    false,
  isonDegree:     'Ni',
  isonOctave:     0,
  isonVolume:     0.5,
  scorePracticeIsonOverride: null,
  scorePracticeManualIsonState: null,
  // Mic / PSOLA correction state. Off by default — chanters should hear
  // their own voice first and opt in to correction as a training aid.
  correctionEnabled: false,
  correctionVolume:  0.5,
  voiceSnapTable:    [],
  voiceLastCellId:   null,
  voiceCurrentCellId: null,
  synthFollowEnabled: false,
  synthFollowVolume:  0.5,
  synthFollowCellId:  null,
  synthFollowMisses:  0,
  setReferenceNiHz:   null,
  selectedPalettePayload: null,
  selectedPaletteEl:      null,
  ensureAudio:       null,
  ensureVoice:       null,
  recorder:          null,
  recordingChunks:   [],
  recordingPitchEvents: [],
  recordingStartedAt: 0,
  recordingTimerId:  null,
  recordingAudioGraph: null,
  recordingCounter:  0,
  recordings:        [],
  activeRecordingPlayback: null,
};

// ── Boot ─────────────────────────────────────────────────────────────────────

async function main() {
  await init();

  app.grid   = new JsTuningGrid();
  app.grid.refNiHz = app.refNiHz;
  app.engine = new AudioEngine();

  const canvas  = document.getElementById('scale-ladder');
  app.ladder    = new ScaleLadder(canvas, app);
  app.keyboard  = new VKeyboard(app.engine, app.ladder);

  const singCanvas  = document.getElementById('singscope');
  app.singscope     = new Singscope(singCanvas);
  app.singscope.start();
  app.noteIndicator = new NoteIndicator(document.getElementById('note-indicator'));
  app.exercise      = new ExerciseMode(document.getElementById('exercise-panel'), app, { selectPreset });

  buildPresetButtons();
  wireControls();
  wirePalettes();
  wireAccidentalPopup();
  wirePresetSaveLoad();
  wireIsonControls();
  wireCorrectionControls();
  wireSynthFollowControls();
  wireRecordingControls();
  wireMobileTabs();
  syncAppVersionText();
  wireHelpDialog();
  wireAudioInit();

  gridChanged();
  wireScorePracticePrototype();
}

// ── Called whenever the grid state changes ────────────────────────────────────

function gridChanged() {
  const gridRefNiHz = app.grid?.refNiHz;
  if (Number.isFinite(gridRefNiHz) && gridRefNiHz > 0) {
    app.refNiHz = clampReferenceHz(gridRefNiHz);
  }
  app.grid.refNiHz = app.refNiHz;
  syncReferenceControls();
  app.ladder.refresh();
  if (app.singscope) app.singscope.setRowMap(app.ladder.rowMap);
  const cells = JSON.parse(app.grid.cellsJson());
  const gridState = readGridState();
  app.noteIndicator?.refresh(cells, gridState);
  app.noteIndicator?.clear();
  app.keyboard.rebuildKeyMap(cells);
  app.voiceSnapTable = cells
    .filter(c => c.enabled)
    .map(c => ({
      cell_id: c.moria,
      moria: c.moria + (c.accidental ?? 0),
      accidental: c.accidental ?? 0,
    }))
    .filter(c => Number.isFinite(c.cell_id) && Number.isFinite(c.moria))
    .sort((a, b) => a.moria - b.moria);
  app.voiceLastCellId = null;
  app.voiceCurrentCellId = null;
  app.engine.updateTuning(cells, app.refNiHz);
  updateIsonVoice(cells);
  stopSynthFollow();
  app.exercise?.syncReferenceNiHz(app.refNiHz);
  app.exercise?.refresh();
  app.scorePractice?.setRowMap(app.ladder.rowMap);
}

app.gridChanged = gridChanged;

function readGridState() {
  try {
    return JSON.parse(app.grid.toJson());
  } catch (e) {
    console.warn('Failed to read grid state for UI context', e);
    return null;
  }
}

// ── Audio init on first user gesture ─────────────────────────────────────────

function syncAppVersionText() {
  document.querySelectorAll('.app-version, .app-version-text').forEach(el => {
    el.textContent = el.classList.contains('app-version') ? `v${APP_VERSION}` : APP_VERSION;
  });
}

function wireHelpDialog() {
  const dialog = document.getElementById('help-dialog');
  const openBtn = document.getElementById('help-open-btn');
  const closeBtn = document.getElementById('help-close-btn');
  const doneBtn = document.getElementById('help-done-btn');
  const showAgain = document.getElementById('help-show-again');
  if (!dialog || !openBtn || !closeBtn || !doneBtn || !showAgain) return;

  const storageKey = 'chanterlab_help_seen_release';
  const seenRelease = localStorage.getItem(storageKey);
  showAgain.checked = false;

  const open = () => {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  };
  const close = () => {
    if (!showAgain.checked) localStorage.setItem(storageKey, HELP_RELEASE_ID);
    else localStorage.removeItem(storageKey);
    dialog.close();
  };

  openBtn.addEventListener('click', open);
  closeBtn.addEventListener('click', close);
  doneBtn.addEventListener('click', close);
  dialog.addEventListener('click', event => {
    if (event.target === dialog) close();
  });
  dialog.addEventListener('cancel', () => {
    if (!showAgain.checked) localStorage.setItem(storageKey, HELP_RELEASE_ID);
  });

  const compactViewport = window.matchMedia(
    '(max-width: 720px), (max-width: 980px) and (max-height: 520px) and (orientation: landscape)'
  ).matches;
  if (seenRelease !== HELP_RELEASE_ID && !compactViewport) {
    requestAnimationFrame(open);
  }
}

function wireAudioInit() {
  const statusEl = document.getElementById('audio-status');

  async function ensureAudio() {
    if (app.engine.ready) return;
    try {
      await app.engine.init();
      statusEl.textContent = '▶ Audio on';
      statusEl.classList.replace('audio-off', 'audio-on');
      // Push the current tuning table now that the engine is ready.
      const cells = JSON.parse(app.grid.cellsJson());
      app.engine.updateTuning(cells, app.refNiHz);
      updateIsonVoice(cells);
      // Correction defaults to off; the synth's own default is 0.5, so we
      // override explicitly on first init.
      app.engine.setCorrectionVolume(
        app.correctionEnabled ? app.correctionVolume : 0
      );
      app.engine.setSynthFollow(null, 0);
    } catch (e) {
      console.error('Audio init failed', e);
    }
  }

  async function ensureVoice() {
    if (app.engine.voiceReady) return;
    try {
      await app.engine.initVoice(handlePitchEvent);
      statusEl.textContent = '▶ Audio + Mic';
    } catch (e) {
      // Mic permission denied or unavailable — non-fatal.
      console.warn('Voice init failed (mic unavailable?)', e);
    }
  }

  // Both click and first keydown trigger audio context creation.
  app.ensureAudio = ensureAudio;
  app.ensureVoice = ensureVoice;

  document.addEventListener('click', ensureAudio, { once: true });
  document.addEventListener('keydown', ensureAudio, { once: true });

  // A second user gesture (or the same one if audio was already up) starts mic.
  document.addEventListener('click', async () => { await ensureAudio(); ensureVoice(); });
  document.addEventListener('keydown', async () => { await ensureAudio(); ensureVoice(); });
}

function handlePitchEvent(msg) {
  if (msg.type === 'dsp_path') {
    const statusEl = document.getElementById('audio-status');
    if (msg.path === 'wasm') {
      statusEl.textContent = '▶ Audio + Mic (WASM DSP)';
      statusEl.title = 'Rust DSP running in the AudioWorklet';
    } else {
      // JS fallback means the Rust DSP didn't load. Put the actual reason in
      // the pill's title (long-press on iOS) and short-form in the visible
      // label so we can diagnose without desktop tooling.
      const reason = msg.error ? msg.error.slice(0, 80) : 'reason unknown';
      statusEl.textContent = '▶ Audio + Mic (JS DSP — slow)';
      statusEl.title = `WASM DSP unavailable: ${reason}`;
      if (msg.error) console.warn('Voice WASM failed:', msg.error);
    }
    return;
  }
  if (msg.type !== 'pitch') return;

  if (
    typeof msg.detected_hz === 'number' &&
    Number.isFinite(msg.detected_hz) &&
    msg.detected_hz > 0
  ) {
    msg.raw_moria = 72 * Math.log2(msg.detected_hz / app.refNiHz);
  } else {
    msg.raw_moria = null;
  }

  const inDetectionRange = msg.raw_moria !== null
    && msg.raw_moria >= DETECTION_LOW_MORIA
    && msg.raw_moria <= DETECTION_HIGH_MORIA;
  if (!inDetectionRange) {
    msg.gate_open = false;
    msg.cell_id = -1;
    msg.neighbor_id = -1;
    msg.neighbor_vel = 0;
  }

  const snap = (msg.gate_open && inDetectionRange)
    ? nearestEnabledMoriaCell(msg.raw_moria, app.voiceLastCellId)
    : null;
  if (snap) {
    msg.cell_id = snap.primary;
    msg.snap_moria = snap.primary_moria;
    msg.neighbor_id = snap.neighbor?.cell_id ?? -1;
    msg.neighbor_moria = snap.neighbor?.moria ?? null;
    msg.neighbor_vel = snap.neighbor?.vel ?? 0;
    app.voiceLastCellId = snap.primary;
  } else if (!msg.gate_open) {
    app.voiceLastCellId = null;
  }
  app.voiceCurrentCellId = msg.gate_open && isValidCellId(msg.cell_id)
    ? msg.cell_id
    : null;

  updateSynthFollowFromPitch(msg);
  app.exercise?.handlePitch(msg);
  app.scorePractice?.handlePitch(msg);

  if (!msg.gate_open || !isValidCellId(msg.cell_id)) {
    app.ladder.setDetectedCell(null, null, 0);
    app.noteIndicator?.clear();
  } else {
    app.ladder.setDetectedCell(
      msg.cell_id,
      isValidCellId(msg.neighbor_id) ? msg.neighbor_id : null,
      msg.neighbor_vel,
      Number.isFinite(msg.snap_moria) ? msg.snap_moria : null,
      Number.isFinite(msg.neighbor_moria) ? msg.neighbor_moria : null,
    );
    app.noteIndicator?.showPitch(msg);
  }
  if (app.singscope) app.singscope.pushPitch(msg);
  recordPitchForActiveTake(msg);
}

function wireScorePracticePrototype() {
  if (scorePracticeExplicitlyDisabled()) return;
  try {
    wireScorePracticePrototypeUnsafe();
  } catch (e) {
    console.error('Score practice failed to initialize', e);
  }
}

function wireScorePracticePrototypeUnsafe() {

  const mainView = document.getElementById('main-view');
  if (!mainView) return;

  const params = new URLSearchParams(window.location.search);
  const exampleId = params.get('scorePracticeExample') || 'diatonic-ladder';
  const playbackRate = readScorePracticePlaybackRate(params);
  const scrollPxPerSecond = readScorePracticeScrollSpeed(params);
  const importOptions = readScorePracticeImportOptions(params);
  let compiled;
  try {
    compiled = compileChantScriptExample(exampleId);
  } catch (e) {
    console.warn('Score practice example failed to compile', e);
    return;
  }

  const canvas = document.createElement('canvas');
  canvas.id = 'score-practice-canvas';
  canvas.className = 'score-practice-layer';
  canvas.setAttribute('aria-hidden', 'true');

  const status = document.createElement('div');
  status.id = 'score-practice-status';
  status.className = 'score-practice-status';
  status.setAttribute('aria-live', 'polite');

  const controls = buildScorePracticeControls(exampleId, playbackRate, {
    importEnabled: scorePracticeImportEnabled(params),
    importOptions,
  });

  mainView.appendChild(canvas);
  mainView.appendChild(status);
  mainView.appendChild(controls.el);
  mainView.classList.add('score-practice-enabled');
  document.body.classList.add('score-practice-active');
  app.singscope?.setTraceTiming({
    anchorRatio: SCORE_PRACTICE_CROSSHAIR_RATIO,
    pxPerSecond: scrollPxPerSecond,
  });

  app.scorePractice = new ScorePracticePrototype(canvas, {
    enabled: true,
    statusEl: status,
    pxPerSecond: scrollPxPerSecond,
    lookaheadMs: 8000,
    crosshairX: SCORE_PRACTICE_CROSSHAIR_RATIO,
    playbackRate,
    leadInMs: SCORE_PRACTICE_LEAD_IN_MS,
    loop: true,
    onTuningChange: tuning => applyScorePracticeTuning(compiled, tuning),
    onIsonChange: applyScorePracticeIson,
  });

  const loadCompiledScore = rawCompiled => {
    applyCompiledScoreInitialTuning(rawCompiled);
    compiled = retuneCompiledScore(rawCompiled);
    app.scorePractice.setCompiledScore(compiled);
    app.scorePractice.setRowMap(app.ladder.rowMap);
    app.scorePractice.restart();
    controls.playPause.textContent = 'Pause';
  };

  const loadExample = nextExampleId => {
    let rawCompiled;
    try {
      rawCompiled = compileChantScriptExample(nextExampleId);
    } catch (e) {
      console.warn('Score practice example failed to compile', e);
      return;
    }
    loadCompiledScore(rawCompiled);
  };

  controls.select.addEventListener('change', () => loadExample(controls.select.value));
  controls.importToggle?.addEventListener('click', () => {
    setScorePracticeImportCollapsed(controls, !controls.el.classList.contains('import-collapsed'));
  });
  controls.importSample?.addEventListener('change', () => {
    const sample = findGlyphImportSampleFixture(controls.importSample.value);
    if (!sample) return;
    applyScorePracticeImportSample(controls, sample);
  });
  controls.importKeyboard?.addEventListener('click', event => {
    const button = event.target.closest('[data-glyph-name]');
    if (!button) return;
    insertScorePracticeImportToken(
      controls.importText,
      scorePracticeGlyphTokenText(button.dataset.glyphName, controls.importSource.value)
    );
    controls.importStatus.textContent = 'edited';
    renderScorePracticeImportDiagnostics(controls.importDiagnostics, []);
  });
  controls.importApply?.addEventListener('click', () => {
    const text = controls.importText.value.trim();
    if (!text) {
      controls.importStatus.textContent = 'empty';
      renderScorePracticeImportDiagnostics(controls.importDiagnostics, []);
      return;
    }
    let rawCompiled;
    try {
      rawCompiled = compileScorePracticeGlyphText(text, controls.importSource.value, {
        startDegree: controls.importStart?.value,
        bpm: Number(controls.importBpm?.value),
      });
    } catch (e) {
      console.warn('Score practice glyph import failed', e);
      controls.importStatus.textContent = 'failed';
      renderScorePracticeImportDiagnostics(controls.importDiagnostics, [{
        severity: 'error',
        code: 'glyph-import-exception',
        message: e?.message ?? String(e),
      }]);
      return;
    }
    const errors = (rawCompiled.diagnostics ?? []).filter(diagnostic => diagnostic.severity === 'error');
    renderScorePracticeImportDiagnostics(controls.importDiagnostics, rawCompiled.diagnostics ?? []);
    if (errors.length) {
      console.warn('Score practice glyph import diagnostics', rawCompiled.diagnostics);
      controls.importStatus.textContent = `${errors.length} error${errors.length === 1 ? '' : 's'}`;
      return;
    }
    loadCompiledScore(rawCompiled);
    const warnings = (rawCompiled.diagnostics ?? []).filter(diagnostic => diagnostic.severity === 'warning').length;
    controls.importStatus.textContent = `loaded ${rawCompiled.notes?.length ?? 0} notes${warnings ? `, ${warnings} warn` : ''}`;
    setScorePracticeImportCollapsed(controls, true);
  });
  controls.restart.addEventListener('click', () => {
    app.scorePractice.restart();
    controls.playPause.textContent = 'Pause';
  });
  controls.playPause.addEventListener('click', () => {
    if (app.scorePractice.isRunning()) {
      app.scorePractice.stop();
      controls.playPause.textContent = 'Play';
    } else {
      app.scorePractice.start();
      controls.playPause.textContent = 'Pause';
    }
  });
  controls.speed.addEventListener('input', () => {
    const nextRate = clampScorePracticePlaybackRate(Number(controls.speed.value));
    controls.speedReadout.textContent = formatPlaybackRate(nextRate);
    app.singscope?.setTraceTiming({
      anchorRatio: SCORE_PRACTICE_CROSSHAIR_RATIO,
      pxPerSecond: scrollPxPerSecond,
    });
    app.scorePractice.setTiming({
      playbackRate: nextRate,
      pxPerSecond: scrollPxPerSecond,
    });
  });

  loadExample(exampleId);
}

function retuneCompiledScore(compiled) {
  return retuneCompiledScoreWithGrid(compiled, {
    createGrid: () => new JsTuningGrid(),
    refNiHz: app.refNiHz,
  });
}

function applyCompiledScoreInitialTuning(compiled) {
  try {
    rebuildGridForCompiledScore(compiled);
  } catch (e) {
    console.warn('Score practice tuning context failed to apply', e);
  }
}

function applyScorePracticeTuning(compiled, tuning) {
  if (!compiled) return;
  try {
    rebuildGridForCompiledScore(compiled, tuning);
  } catch (e) {
    console.warn('Score practice tuning event failed to apply', e);
  }
}

function rebuildGridForCompiledScore(compiled, tuning = {}) {
  const startDegree = compiled?.score?.initialMartyria?.degree ?? 'Ni';
  const initialScale = compiled?.score?.initialScale;
  const initialDrop = {
    type: 'pthora',
    genus: initialScale?.genus ?? 'Diatonic',
    degree: startDegree,
    dropMoria: referenceMoriaForDegree(startDegree),
    dropDegree: startDegree,
    ...(Number.isInteger(initialScale?.phase) ? { phase: initialScale.phase } : {}),
  };

  app.grid = new JsTuningGrid();
  app.grid.refNiHz = app.refNiHz;
  applyPthoraDrop(app.grid, initialDrop);

  for (const event of tuning?.pthoraEvents ?? []) {
    if (event?.sourceEventIndex === -1) continue;
    applyPthoraDrop(app.grid, event);
  }

  const accidental = tuning?.accidental;
  if (Number.isFinite(accidental?.cellMoria) && Number.isFinite(accidental?.accidentalMoria)) {
    app.grid.setAccidental(accidental.cellMoria, accidental.accidentalMoria);
  }

  app.activePresetIdx = -1;
  document.querySelectorAll('.preset-btn').forEach(btn => btn.classList.remove('active'));
  gridChanged();
}

function readScorePracticePlaybackRate(params) {
  const raw = Number(params.get('scorePracticeSpeed') ?? params.get('score-practice-speed'));
  return Number.isFinite(raw) && raw > 0
    ? clampScorePracticePlaybackRate(raw)
    : SCORE_PRACTICE_DEFAULT_PLAYBACK_RATE;
}

function readScorePracticeScrollSpeed(params) {
  const raw = Number(params.get('scorePracticeScroll') ?? params.get('score-practice-scroll'));
  return Number.isFinite(raw) && raw > 0
    ? Math.max(28, Math.min(140, raw))
    : SCORE_PRACTICE_SCROLL_PX_PER_SECOND;
}

function scorePracticeImportEnabled(params) {
  const raw = params.get('scoreImport') ?? params.get('score-import');
  return raw !== null && ['1', 'true', 'yes', 'on'].includes(raw.toLowerCase());
}

function readScorePracticeImportOptions(params) {
  const samples = listGlyphImportSampleFixtures();
  const requestedSampleId = params.get('scoreImportSample') ?? params.get('score-import-sample');
  const sample = findGlyphImportSampleFixture(requestedSampleId) ?? samples[0];
  const startDegree = params.get('scoreImportStart') ?? params.get('score-import-start') ?? sample?.startDegree ?? 'Ni';
  const bpm = Number(params.get('scoreImportBpm') ?? params.get('score-import-bpm') ?? sample?.bpm ?? 120);
  const source = params.get('scoreImportSource') ?? params.get('score-import-source') ?? sample?.source ?? 'glyph';
  return {
    sampleId: sample?.id,
    source,
    startDegree,
    bpm: Number.isFinite(bpm) && bpm > 0 ? bpm : 120,
  };
}

function compileScorePracticeGlyphText(text, source, options = {}) {
  const compileOptions = {
    title: 'Imported Glyph Score',
    startDegree: options.startDegree ?? 'Ni',
    bpm: Number.isFinite(options.bpm) && options.bpm > 0 ? options.bpm : 120,
  };
  if (source === 'sbmufl') return compileSbmuflGlyphText(text, compileOptions);
  if (source === 'unicode') return compileUnicodeByzantineText(text, compileOptions);
  return compileGlyphText(text, compileOptions);
}

function clampScorePracticePlaybackRate(rate) {
  return Number.isFinite(rate)
    ? Math.max(SCORE_PRACTICE_MIN_PLAYBACK_RATE, Math.min(SCORE_PRACTICE_MAX_PLAYBACK_RATE, rate))
    : SCORE_PRACTICE_DEFAULT_PLAYBACK_RATE;
}

function formatPlaybackRate(rate) {
  return `${Math.round(rate * 100)}%`;
}

function buildScorePracticeControls(selectedExampleId, playbackRate, options = {}) {
  const el = document.createElement('div');
  el.id = 'score-practice-controls';
  el.className = 'score-practice-controls';
  if (options.importEnabled) el.classList.add('has-import');

  const title = document.createElement('span');
  title.className = 'score-practice-controls-title';
  title.textContent = 'Score practice';

  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Choose score practice fixture');
  for (const example of listChantScriptExamples()) {
    const option = document.createElement('option');
    option.value = example.id;
    option.textContent = example.title;
    option.selected = example.id === selectedExampleId;
    select.appendChild(option);
  }

  const restart = document.createElement('button');
  restart.type = 'button';
  restart.className = 'score-practice-restart';
  restart.textContent = 'Restart';

  const playPause = document.createElement('button');
  playPause.type = 'button';
  playPause.className = 'score-practice-play';
  playPause.textContent = 'Pause';

  const speedWrap = document.createElement('label');
  speedWrap.className = 'score-practice-speed';
  const speedText = document.createElement('span');
  speedText.textContent = 'Speed';
  const speed = document.createElement('input');
  speed.type = 'range';
  speed.min = String(SCORE_PRACTICE_MIN_PLAYBACK_RATE);
  speed.max = String(SCORE_PRACTICE_MAX_PLAYBACK_RATE);
  speed.step = '0.05';
  speed.value = String(clampScorePracticePlaybackRate(playbackRate));
  const speedReadout = document.createElement('span');
  speedReadout.className = 'score-practice-speed-readout';
  speedReadout.textContent = formatPlaybackRate(Number(speed.value));
  speedWrap.append(speedText, speed, speedReadout);

  el.append(title, select, speedWrap, restart, playPause);

  const controls = { el, select, restart, playPause, speed, speedReadout };
  if (options.importEnabled) {
    el.classList.add('import-collapsed');
    const importOptions = options.importOptions ?? {};
    const samples = listGlyphImportSampleFixtures();
    const selectedSample = findGlyphImportSampleFixture(importOptions.sampleId) ?? samples[0];

    const importToggle = document.createElement('button');
    importToggle.type = 'button';
    importToggle.className = 'score-practice-import-toggle';
    importToggle.textContent = 'Import';
    importToggle.setAttribute('aria-expanded', 'false');

    const importPanel = document.createElement('div');
    importPanel.className = 'score-practice-import';

    const importSource = document.createElement('select');
    importSource.className = 'score-practice-import-source';
    importSource.setAttribute('aria-label', 'Glyph import source');
    for (const [value, label] of [
      ['glyph', 'Glyph names'],
      ['sbmufl', 'SBMuFL/Neanes'],
      ['unicode', 'Unicode'],
    ]) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      importSource.appendChild(option);
    }
    importSource.value = importOptions.source ?? selectedSample?.source ?? 'glyph';

    const importSample = document.createElement('select');
    importSample.className = 'score-practice-import-sample';
    importSample.setAttribute('aria-label', 'Glyph import sample');
    for (const sample of samples) {
      const option = document.createElement('option');
      option.value = sample.id;
      option.textContent = sample.title;
      option.selected = sample.id === selectedSample?.id;
      importSample.appendChild(option);
    }

    const importStart = document.createElement('select');
    importStart.className = 'score-practice-import-start';
    importStart.setAttribute('aria-label', 'Glyph import start degree');
    importStart.title = 'Start degree';
    for (const degree of SCORE_IMPORT_DEGREES) {
      const option = document.createElement('option');
      option.value = degree;
      option.textContent = degree;
      importStart.appendChild(option);
    }
    importStart.value = SCORE_IMPORT_DEGREES.includes(importOptions.startDegree)
      ? importOptions.startDegree
      : selectedSample?.startDegree ?? 'Ni';

    const importBpm = document.createElement('input');
    importBpm.className = 'score-practice-import-bpm';
    importBpm.type = 'number';
    importBpm.min = '30';
    importBpm.max = '240';
    importBpm.step = '1';
    importBpm.inputMode = 'numeric';
    importBpm.setAttribute('aria-label', 'Glyph import BPM');
    importBpm.title = 'BPM';
    importBpm.value = String(importOptions.bpm ?? selectedSample?.bpm ?? 120);

    const importText = document.createElement('textarea');
    importText.setAttribute('aria-label', 'Glyph import text');
    importText.rows = 2;
    importText.spellcheck = false;
    importText.value = selectedSample?.text ?? 'ison oligon oligon apostrofos gorgonAbove leimma2';

    const importKeyboard = buildScorePracticeGlyphKeyboard();

    const importApply = document.createElement('button');
    importApply.type = 'button';
    importApply.textContent = 'Load';

    const importStatus = document.createElement('span');
    importStatus.className = 'score-practice-import-status';
    importStatus.textContent = 'import';

    const importDiagnostics = document.createElement('pre');
    importDiagnostics.className = 'score-practice-import-diagnostics';
    importDiagnostics.hidden = true;

    importPanel.append(
      importSource,
      importSample,
      importStart,
      importBpm,
      importText,
      importKeyboard,
      importApply,
      importStatus,
      importDiagnostics
    );
    el.appendChild(importToggle);
    el.appendChild(importPanel);
    Object.assign(controls, {
      importToggle,
      importSource,
      importSample,
      importStart,
      importBpm,
      importText,
      importKeyboard,
      importApply,
      importStatus,
      importDiagnostics,
    });
  }

  return controls;
}

function buildScorePracticeGlyphKeyboard() {
  const keyboard = document.createElement('div');
  keyboard.className = 'score-practice-glyph-keyboard';
  keyboard.setAttribute('aria-label', 'Glyph token keyboard');

  for (const group of SCORE_GLYPH_KEYBOARD_ROLES) {
    const tokens = SCORE_GLYPH_IMPORT_TOKENS.filter(token => token.role === group.role);
    if (!tokens.length) continue;

    const groupEl = document.createElement('div');
    groupEl.className = 'score-practice-glyph-keyboard-group';

    const label = document.createElement('span');
    label.className = 'score-practice-glyph-keyboard-label';
    label.textContent = group.label;
    groupEl.appendChild(label);

    for (const token of tokens) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'score-practice-glyph-key';
      button.dataset.glyphName = token.glyphName;
      button.textContent = scoreGlyphTokenLabel(token);
      button.title = token.glyphName;
      groupEl.appendChild(button);
    }

    keyboard.appendChild(groupEl);
  }

  return keyboard;
}

function applyScorePracticeImportSample(controls, sample) {
  controls.importSource.value = sample.source ?? 'glyph';
  controls.importStart.value = sample.startDegree ?? 'Ni';
  controls.importBpm.value = String(sample.bpm ?? 120);
  controls.importText.value = sample.text ?? '';
  controls.importStatus.textContent = 'sample';
  renderScorePracticeImportDiagnostics(controls.importDiagnostics, []);
}

function setScorePracticeImportCollapsed(controls, collapsed) {
  if (!controls?.el || !controls?.importToggle) return;
  controls.el.classList.toggle('import-collapsed', collapsed);
  controls.importToggle.textContent = collapsed ? 'Import' : 'Hide';
  controls.importToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

function insertScorePracticeImportToken(textarea, tokenText) {
  if (!textarea || !tokenText) return;
  const value = textarea.value;
  const start = Number.isInteger(textarea.selectionStart) ? textarea.selectionStart : value.length;
  const end = Number.isInteger(textarea.selectionEnd) ? textarea.selectionEnd : start;
  const before = value.slice(0, start);
  const after = value.slice(end);
  const prefix = before && !/\s$/.test(before) ? ' ' : '';
  const suffix = after && !/^\s/.test(after) ? ' ' : '';
  const insert = `${prefix}${tokenText}${suffix}`;
  textarea.value = `${before}${insert}${after}`;
  const cursor = start + prefix.length + tokenText.length;
  textarea.focus();
  textarea.setSelectionRange(cursor, cursor);
}

function scorePracticeGlyphTokenText(glyphName, source) {
  const token = SCORE_GLYPH_IMPORT_TOKENS.find(item => item.glyphName === glyphName);
  if (!token) return glyphName;
  if (source === 'sbmufl') return characterForCodepoint(token.codepoint) ?? token.glyphName;
  if (source === 'unicode') return characterForCodepoint(token.alternateCodepoint) ?? token.glyphName;
  return token.glyphName;
}

function characterForCodepoint(codepoint) {
  if (typeof codepoint !== 'string') return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint.trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}

function scoreGlyphTokenLabel(token) {
  const labels = {
    ison: 'Ison',
    oligon: 'Oligon',
    apostrofos: 'Apost.',
    yporroi: 'Yporroi',
    elafron: 'Elafron',
    chamili: 'Chamili',
    leimma1: 'Rest 1',
    leimma2: 'Rest 2',
    leimma3: 'Rest 3',
    leimma4: 'Rest 4',
    gorgonAbove: 'Gorgon',
    digorgon: 'Digorgon',
    trigorgon: 'Trigorgon',
    argon: 'Argon',
    apli: 'Apli',
    klasma: 'Klasma',
    dipli: 'Dipli',
    tripli: 'Tripli',
    agogiMetria: 'Metria',
    agogiGorgi: 'Gorgi',
    fthoraHardChromaticPaAbove: 'Hard Pa',
    fthoraHardChromaticDiAbove: 'Hard Di',
    fthoraSoftChromaticDiAbove: 'Soft Di',
    fthoraSoftChromaticKeAbove: 'Soft Ke',
    chroaZygosAbove: 'Zygos',
    chroaKlitonAbove: 'Kliton',
    chroaSpathiAbove: 'Spathi',
  };
  return labels[token.glyphName] ?? token.glyphName.replace(/([A-Z])/g, ' $1');
}

function renderScorePracticeImportDiagnostics(el, diagnostics) {
  if (!el) return;
  const visible = (diagnostics ?? []).filter(Boolean);
  if (!visible.length) {
    el.hidden = true;
    el.textContent = '';
    return;
  }

  el.hidden = false;
  el.textContent = visible.slice(0, 8).map(formatScorePracticeImportDiagnostic).join('\n');
}

function formatScorePracticeImportDiagnostic(diagnostic) {
  const tokenLabel = scorePracticeDiagnosticTokenLabel(diagnostic);
  return tokenLabel
    ? `${formatDiagnostic(diagnostic)} (${tokenLabel})`
    : formatDiagnostic(diagnostic);
}

function scorePracticeDiagnosticTokenLabel(diagnostic) {
  const source = diagnostic?.source?.source;
  const tokens = Array.isArray(source?.tokens) ? source.tokens : [];
  const rawTokens = tokens.map(token => token.raw).filter(Boolean);
  if (rawTokens.length) return `tokens: ${rawTokens.join(' ')}`;
  const raw = diagnostic?.source?.raw;
  return raw ? `token: ${raw}` : '';
}

function isValidCellId(cellId) {
  return typeof cellId === 'number' && Number.isFinite(cellId) && cellId !== -1;
}

function stopSynthFollow() {
  if (app.synthFollowCellId !== null) {
    app.engine.setSynthFollow(null, 0);
    app.synthFollowCellId = null;
  }
  app.synthFollowMisses = 0;
}

function updateSynthFollowFromPitch(msg) {
  if (!app.synthFollowEnabled || app.synthFollowVolume <= 0) {
    stopSynthFollow();
    return;
  }

  if (!msg.gate_open || !isValidCellId(msg.cell_id)) {
    if (app.synthFollowCellId !== null && app.synthFollowMisses < 8) {
      app.synthFollowMisses++;
      return;
    }
    stopSynthFollow();
    return;
  }

  app.synthFollowMisses = 0;
  if (app.synthFollowCellId !== msg.cell_id) {
    app.engine.setSynthFollow(msg.cell_id, app.synthFollowVolume);
    app.synthFollowCellId = msg.cell_id;
  }
}

function nearestEnabledMoriaCell(rawMoria, lastCellId) {
  const table = app.voiceSnapTable;
  const n = table.length;
  if (n === 0) return null;

  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (table[mid].moria <= rawMoria) lo = mid + 1;
    else hi = mid;
  }
  const pos = lo;

  let primaryIdx;
  if (pos === 0) {
    primaryIdx = 0;
  } else if (pos === n) {
    primaryIdx = n - 1;
  } else {
    const below = table[pos - 1];
    const above = table[pos];
    let dBelow = rawMoria - below.moria;
    let dAbove = above.moria - rawMoria;
    if (lastCellId != null) {
      if (below.cell_id === lastCellId) dBelow /= 2;
      if (above.cell_id === lastCellId) dAbove /= 2;
    }
    primaryIdx = dBelow < dAbove ? pos - 1 : pos;
  }

  const primary = table[primaryIdx];
  let neighbor = null;
  if (n > 1) {
    const below = primaryIdx > 0 ? table[primaryIdx - 1] : null;
    const above = primaryIdx < n - 1 ? table[primaryIdx + 1] : null;
    if (below && above) {
      const a2 = Math.max(0, rawMoria - below.moria);
      const a3 = Math.max(0, above.moria - rawMoria);
      const total = a2 + a3;
      neighbor = a2 <= a3
        ? { cell_id: below.cell_id, moria: below.moria, vel: total > 0 ? a3 / total : 0.5 }
        : { cell_id: above.cell_id, moria: above.moria, vel: total > 0 ? a2 / total : 0.5 };
    } else {
      const neighborCell = below ?? above;
      neighbor = { cell_id: neighborCell.cell_id, moria: neighborCell.moria, vel: 0.5 };
    }
  }

  return { primary: primary.cell_id, primary_moria: primary.moria, neighbor };
}

// ── Preset buttons ────────────────────────────────────────────────────────────

function buildPresetButtons() {
  const container = document.getElementById('preset-buttons');
  PRESETS.forEach((p, i) => {
    const btn = document.createElement('button');
    btn.className = 'preset-btn' + (i === 0 ? ' active' : '');
    btn.textContent = p.label;
    btn.dataset.idx = i;
    btn.addEventListener('click', () => selectPreset(i));
    container.appendChild(btn);
  });
}

function selectPreset(idx) {
  const p = PRESETS[idx];
  app.grid = new JsTuningGrid();
  app.grid.refNiHz = app.refNiHz;
  app.grid.applyPthora(0, p.genus, p.degree);
  app.activePresetIdx = idx;

  document.querySelectorAll('.preset-btn').forEach((b, i) => {
    b.classList.toggle('active', i === idx);
  });
  gridChanged();
}

// ── Wiring ────────────────────────────────────────────────────────────────────

const CONCERT_NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];

function hzToExactMidi(hz) {
  return 69 + 12 * Math.log2(hz / 440);
}

function midiToHz(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

function nextMidiFromHz(hz, direction) {
  const exactMidi = hzToExactMidi(hz);
  const nearestMidi = Math.round(exactMidi);
  const displaySnapsToMidi = Math.abs(exactMidi - nearestMidi) < 0.005;
  if (displaySnapsToMidi) return nearestMidi + direction;
  return direction > 0 ? Math.floor(exactMidi) + 1 : Math.ceil(exactMidi) - 1;
}

function formatConcertPitch(hz) {
  if (!Number.isFinite(hz) || hz <= 0) return '';

  const exactMidi = hzToExactMidi(hz);
  let midi = Math.ceil(exactMidi - 0.5);
  let cents = Math.round((exactMidi - midi) * 100);

  if (cents <= -50) {
    midi -= 1;
    cents += 100;
  } else if (cents > 50) {
    midi += 1;
    cents -= 100;
  }

  const noteName = CONCERT_NOTE_NAMES[((midi % 12) + 12) % 12];
  const octave = Math.floor(midi / 12) - 1;
  const sign = cents >= 0 ? '+' : '';
  return `${noteName}${octave} ${sign}${cents}c`;
}

function setReferenceNiHz(hz) {
  const clampedHz = clampReferenceHz(hz);
  app.refNiHz = clampedHz;
  app.grid.refNiHz = clampedHz;
  gridChanged();
}

app.setReferenceNiHz = setReferenceNiHz;

function clampReferenceHz(hz) {
  const slider = document.getElementById('ni-hz-slider');
  const min = parseFloat(slider ? slider.min : '90');
  const max = parseFloat(slider ? slider.max : '700');
  return Math.min(max, Math.max(min, hz));
}

function updateReferenceNiDisplay(hz) {
  const niDisplay = document.getElementById('ni-hz-display');
  const noteDisplay = document.getElementById('ni-note-display');
  niDisplay.textContent = hz.toFixed(2);
  noteDisplay.textContent = formatConcertPitch(hz);
}

function syncReferenceRangeSelect(hz) {
  const rangeSelect = document.getElementById('reference-range-select');
  if (!rangeSelect) return;
  const matched = REFERENCE_RANGE_OPTIONS.find(option => {
    if (option.value === 'custom') return false;
    return Math.abs(parseFloat(option.value) - hz) < 0.01;
  });
  rangeSelect.value = matched?.value ?? 'custom';
}

function syncReferenceControls() {
  const slider = document.getElementById('ni-hz-slider');
  if (slider) slider.value = app.refNiHz.toFixed(2);
  updateReferenceNiDisplay(app.refNiHz);
  syncReferenceRangeSelect(app.refNiHz);
}

function wireControls() {
  const slider    = document.getElementById('ni-hz-slider');
  const rangeSelect = document.getElementById('reference-range-select');

  syncReferenceControls();
  slider.addEventListener('input', () => {
    setReferenceNiHz(parseFloat(slider.value));
  });
  rangeSelect?.addEventListener('change', () => {
    if (rangeSelect.value === 'custom') return;
    setReferenceNiHz(parseFloat(rangeSelect.value));
  });

  document.getElementById('ni-snap-up-btn').addEventListener('click', () => {
    setReferenceNiHz(midiToHz(nextMidiFromHz(app.refNiHz, 1)));
  });
  document.getElementById('ni-snap-down-btn').addEventListener('click', () => {
    setReferenceNiHz(midiToHz(nextMidiFromHz(app.refNiHz, -1)));
  });

  const resetScale = () => {
    app.grid = new JsTuningGrid();
    app.grid.refNiHz = app.refNiHz;
    app.activePresetIdx = 0;
    document.querySelectorAll('.preset-btn').forEach((b, i) => {
      b.classList.toggle('active', i === 0);
    });
    gridChanged();
  };
  document.getElementById('reset-btn')?.addEventListener('click', resetScale);
  document.getElementById('scale-reset-btn')?.addEventListener('click', resetScale);
}

// ── Palettes ──────────────────────────────────────────────────────────────────

function wirePalettes() {
  new PthoraPalette(document.getElementById('pthora-palette'));
  new ShadingPalette(document.getElementById('shading-palette'));
  buildQuickPthoraControls({
    genusSelect: document.getElementById('quick-pthora-genus'),
    degreeContainer: document.getElementById('quick-pthora-degrees'),
    onPick: payload => applyOrSelectQuickPayload(payload),
  });
  buildQuickShadingControls({
    container: document.getElementById('quick-shading-buttons'),
    onPick: payload => applyOrSelectQuickPayload(payload),
  });
  document.addEventListener('chanterlab:palette-click', e => {
    const payload = e.detail?.payload;
    const applied = applySymbolPayloadToCurrentSungCell(payload);
    if (!applied) {
      setSelectedPalettePayload(payload, e.target.closest('.pthora-icon, .shading-icon'));
    } else {
      clearSelectedPalettePayload();
    }
  });
}

function applyOrSelectQuickPayload(payload) {
  const applied = applySymbolPayloadToCurrentSungCell(payload);
  if (!applied) setSelectedPalettePayload(payload);
  else clearSelectedPalettePayload();
}

function setSelectedPalettePayload(payload, sourceEl = null) {
  if (!payload) return;
  clearSelectedPalettePayload();
  app.selectedPalettePayload = payload;
  app.selectedPaletteEl = sourceEl;
  sourceEl?.classList.add('selected');
  app.noteIndicator?.setMessage('Tap a ladder note to apply the selected symbol.');
}

function clearSelectedPalettePayload() {
  app.selectedPaletteEl?.classList.remove('selected');
  app.selectedPalettePayload = null;
  app.selectedPaletteEl = null;
}

function applySymbolPayloadToCurrentSungCell(payload) {
  if (!isValidCellId(app.voiceCurrentCellId)) return false;
  const cell = findCellByMoria(app.voiceCurrentCellId);
  if (!cell || cell.degree === null || !cell.enabled) return false;
  return applySymbolPayloadToCell(payload, cell);
}

function findCellByMoria(moria) {
  const cells = JSON.parse(app.grid.cellsJson());
  return cells.find(c => c.moria === moria) ?? null;
}

function applySymbolPayloadToCell(payload, cell) {
  if (!payload || !cell || cell.degree === null) return false;

  let drop = null;
  if (payload.type === 'pthora') {
    const hasPhase = Number.isInteger(payload.phase);
    drop = {
      type: 'pthora',
      genus: payload.genus,
      degree: hasPhase ? cell.degree : (payload.degree ?? cell.degree),
      dropMoria: cell.moria,
      dropDegree: cell.degree,
    };
    if (hasPhase) drop.phase = payload.phase;
  } else if (payload.type === 'shading') {
    drop = {
      type: 'shading',
      shading: payload.shading,
      dropMoria: cell.moria,
      dropDegree: cell.degree,
    };
  }
  if (!drop) return false;

  const ok = app.grid.applySymbolDrop(JSON.stringify(drop));
  if (ok) app.gridChanged();
  return ok;
}

app.applySymbolPayloadToCell = applySymbolPayloadToCell;
app.clearSelectedPalettePayload = clearSelectedPalettePayload;

function wireMobileTabs() {
  const tabs = Array.from(document.querySelectorAll('.mobile-tab'));
  if (!tabs.length) return;
  const views = new Set(tabs.map(btn => btn.dataset.mobileView).filter(Boolean));

  const setView = view => {
    if (!views.has(view)) view = 'sing';
    document.body.dataset.mobileView = view;
    tabs.forEach(btn => btn.classList.toggle('active', btn.dataset.mobileView === view));
    requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
  };

  tabs.forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.mobileView || 'sing';
      if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
      setView(view);
    });
  });
  window.addEventListener('hashchange', () => setView(location.hash.slice(1)));
  setView(location.hash.slice(1) || 'sing');
}

// ── Accidental popup ──────────────────────────────────────────────────────────

let _accPopupCell = null;

function wireAccidentalPopup() {
  const popup = document.getElementById('accidental-popup');

  [-8, -6, -4, -2, +2, +4, +6, +8].forEach(offset => {
    const btn = document.createElement('button');
    btn.className = 'acc-btn';
    btn.textContent = (offset > 0 ? '+' : '') + offset;
    btn.addEventListener('click', () => {
      if (_accPopupCell) {
        app.grid.setAccidental(_accPopupCell.moria, offset);
        gridChanged();
      }
      hideAccidentalPopup();
    });
    document.getElementById('acc-preset-btns').appendChild(btn);
  });

  document.getElementById('acc-custom-apply').addEventListener('click', () => {
    const val = parseInt(document.getElementById('acc-custom-input').value, 10);
    if (!isNaN(val) && val % 2 === 0 && _accPopupCell) {
      app.grid.setAccidental(_accPopupCell.moria, val);
      gridChanged();
    }
    hideAccidentalPopup();
  });

  document.getElementById('acc-clear-btn').addEventListener('click', () => {
    if (_accPopupCell) {
      app.grid.clearOverride(_accPopupCell.moria);
      gridChanged();
    }
    hideAccidentalPopup();
  });

  document.addEventListener('click', e => {
    if (!popup.contains(e.target)) hideAccidentalPopup();
  });
}

function hideAccidentalPopup() {
  document.getElementById('accidental-popup').classList.remove('visible');
  _accPopupCell = null;
}

app.showAccidentalPopup = function(cell, x, y) {
  _accPopupCell = cell;
  const popup = document.getElementById('accidental-popup');
  popup.style.left = x + 'px';
  popup.style.top  = y + 'px';
  popup.classList.add('visible');
};

// ── Ison drone ────────────────────────────────────────────────────────────────

function wireIsonControls() {
  const toggleBtn   = document.getElementById('ison-toggle-btn');
  const degreeSelect = document.getElementById('ison-degree-select');
  const octaveSelect = document.getElementById('ison-octave-select');
  const volSlider    = document.getElementById('ison-volume-slider');

  toggleBtn.addEventListener('click', () => {
    app.isonEnabled = !app.isonEnabled;
    toggleBtn.textContent = app.isonEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.isonEnabled);
    updateIsonVoice(JSON.parse(app.grid.cellsJson()));
  });

  degreeSelect.addEventListener('change', () => {
    app.isonDegree = degreeSelect.value;
    updateIsonVoice(JSON.parse(app.grid.cellsJson()));
  });

  octaveSelect.addEventListener('change', () => {
    app.isonOctave = parseInt(octaveSelect.value, 10);
    updateIsonVoice(JSON.parse(app.grid.cellsJson()));
  });

  volSlider.addEventListener('input', () => {
    app.isonVolume = parseFloat(volSlider.value);
    if (app.isonEnabled) {
      updateIsonVoice(JSON.parse(app.grid.cellsJson()));
    }
  });

  syncIsonControls();
}

function syncIsonControls() {
  const toggleBtn = document.getElementById('ison-toggle-btn');
  const degreeSelect = document.getElementById('ison-degree-select');
  const octaveSelect = document.getElementById('ison-octave-select');
  const volSlider = document.getElementById('ison-volume-slider');
  if (toggleBtn) {
    toggleBtn.textContent = app.isonEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.isonEnabled);
  }
  if (degreeSelect) degreeSelect.value = app.isonDegree;
  if (octaveSelect) {
    const octaveValue = String(app.isonOctave);
    octaveSelect.value = octaveValue;
    for (const option of octaveSelect.options) {
      option.selected = option.value === octaveValue;
    }
  }
  if (volSlider) volSlider.value = String(app.isonVolume);
}

app.setIsonDrone = function({ degree = app.isonDegree, octave = app.isonOctave, enabled = true } = {}) {
  releaseScorePracticeIson();
  app.isonDegree = degree;
  app.isonOctave = octave;
  app.isonEnabled = enabled;
  syncIsonControls();
  updateIsonVoice(JSON.parse(app.grid.cellsJson()));
};

function applyScorePracticeIson(ison) {
  if (!ison) {
    releaseScorePracticeIson();
    return;
  }

  if (!app.scorePracticeManualIsonState) {
    app.scorePracticeManualIsonState = {
      enabled: app.isonEnabled,
      degree: app.isonDegree,
      octave: app.isonOctave,
    };
  }

  const resolved = scorePracticeIsonControlState(ison);
  if (!resolved) {
    releaseScorePracticeIson();
    return;
  }

  app.scorePracticeIsonOverride = {
    degree: resolved.degree,
    cellId: resolved.cellId,
    octave: resolved.octave,
  };
  app.isonEnabled = true;
  app.isonDegree = resolved.degree;
  app.isonOctave = Number.isFinite(resolved.octave)
    ? resolved.octave
    : app.isonOctave;
  syncIsonControls();
  updateIsonVoice(JSON.parse(app.grid.cellsJson()));
}

function releaseScorePracticeIson() {
  if (!app.scorePracticeManualIsonState && !app.scorePracticeIsonOverride) return;
  const manual = app.scorePracticeManualIsonState;
  app.scorePracticeIsonOverride = null;
  app.scorePracticeManualIsonState = null;
  if (manual) {
    app.isonEnabled = manual.enabled;
    app.isonDegree = manual.degree;
    app.isonOctave = manual.octave;
  }
  syncIsonControls();
  updateIsonVoice(JSON.parse(app.grid.cellsJson()));
}

function updateIsonVoice(cells) {
  if (app.scorePracticeIsonOverride) {
    const override = app.scorePracticeIsonOverride;
    const overrideCell = cells.find(cell => (
      cell.degree === override.degree
      && Number.isFinite(override.octave)
      && Math.floor(cell.moria / 72) === override.octave
      && cell.enabled
    ));
    if (overrideCell) {
      app.engine.setIson(overrideCell.moria, app.isonVolume);
      return;
    }
    const cellId = override.cellId;
    if (Number.isFinite(cellId)) {
      app.engine.setIson(cellId, app.isonVolume);
      return;
    }
  }
  if (!app.isonEnabled) {
    app.engine.setIson(null, 0);
    return;
  }
  // Find the enabled cell for the chosen degree + octave.
  const cell = cells.find(
    c => c.degree === app.isonDegree &&
         Math.floor(c.moria / 72) === app.isonOctave &&
         c.enabled
  );
  if (cell) {
    app.engine.setIson(cell.moria, app.isonVolume);
  } else {
    app.engine.setIson(null, 0);
  }
}

// ── Mic / PSOLA correction ───────────────────────────────────────────────────

function wireCorrectionControls() {
  const toggleBtn = document.getElementById('correction-toggle-btn');
  const volSlider = document.getElementById('correction-volume-slider');

  const pushVolume = () => {
    app.engine.setCorrectionVolume(
      app.correctionEnabled ? app.correctionVolume : 0
    );
  };

  toggleBtn.addEventListener('click', () => {
    app.correctionEnabled = !app.correctionEnabled;
    toggleBtn.textContent = app.correctionEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.correctionEnabled);
    pushVolume();
  });

  volSlider.addEventListener('input', () => {
    app.correctionVolume = parseFloat(volSlider.value);
    if (app.correctionEnabled) pushVolume();
  });
}

// ── Synth follow ─────────────────────────────────────────────────────────────

function wireSynthFollowControls() {
  const toggleBtn = document.getElementById('synth-follow-toggle-btn');
  const volSlider = document.getElementById('synth-follow-volume-slider');

  toggleBtn.addEventListener('click', () => {
    app.synthFollowEnabled = !app.synthFollowEnabled;
    toggleBtn.textContent = app.synthFollowEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.synthFollowEnabled);
    if (!app.synthFollowEnabled) stopSynthFollow();
  });

  volSlider.addEventListener('input', () => {
    app.synthFollowVolume = parseFloat(volSlider.value);
    if (!app.synthFollowEnabled) return;
    if (app.synthFollowCellId !== null && app.synthFollowVolume > 0) {
      app.engine.setSynthFollow(app.synthFollowCellId, app.synthFollowVolume);
    } else {
      stopSynthFollow();
    }
  });
}

// ── Recording / playback ─────────────────────────────────────────────────────

function wireRecordingControls() {
  document.getElementById('record-toggle-btn')?.addEventListener('click', () => {
    if (app.recorder?.state === 'recording') stopRecording();
    else startRecording();
  });

  document.getElementById('record-stop-playback-btn')?.addEventListener('click', () => {
    stopRecordingPlayback();
  });

  renderRecordings();
  updateRecordingControls();
}

async function startRecording() {
  if (app.recorder?.state === 'recording') return;
  stopRecordingPlayback();

  if (!window.MediaRecorder) {
    setRecordingStatus('Recording is not supported in this browser.');
    return;
  }

  await app.ensureVoice?.();
  const micStream = app.engine?.micStream;
  if (!micStream) {
    setRecordingStatus('Mic is not ready. Allow microphone access, then try again.');
    return;
  }

  let recorder;
  let audioGraph = null;
  try {
    audioGraph = createStereoRecordingStream(micStream);
    recorder = createMediaRecorder(audioGraph.stream);
  } catch (e) {
    console.error('Failed to create MediaRecorder', e);
    audioGraph?.cleanup?.();
    setRecordingStatus('Could not start the recorder for this mic stream.');
    return;
  }

  app.recordingChunks = [];
  app.recordingPitchEvents = [];
  app.recordingStartedAt = performance.now();
  app.recordingAudioGraph = audioGraph;
  app.recorder = recorder;

  recorder.addEventListener('dataavailable', event => {
    if (event.data?.size > 0) app.recordingChunks.push(event.data);
  });
  recorder.addEventListener('error', event => {
    console.error('Recording error', event.error || event);
    setRecordingStatus('Recording stopped because of an audio capture error.');
  });
  recorder.addEventListener('stop', () => {
    finalizeRecording().catch(e => {
      console.error('Failed to finalize recording', e);
      setRecordingStatus('Could not save the recording.');
      updateRecordingControls();
    });
  });

  try {
    recorder.start(250);
  } catch (e) {
    console.error('Failed to start MediaRecorder', e);
    audioGraph?.cleanup?.();
    app.recordingAudioGraph = null;
    app.recorder = null;
    setRecordingStatus('Could not start recording.');
    updateRecordingControls();
    return;
  }

  app.recordingTimerId = setInterval(updateRecordingControls, 250);
  setRecordingStatus('Recording 0:00');
  updateRecordingControls();
}

function stopRecording() {
  if (!app.recorder || app.recorder.state !== 'recording') return;
  setRecordingStatus('Saving recording...');
  app.recorder.requestData?.();
  app.recorder.stop();
  updateRecordingControls();
}

async function finalizeRecording() {
  if (app.recordingTimerId !== null) {
    clearInterval(app.recordingTimerId);
    app.recordingTimerId = null;
  }

  const recorder = app.recorder;
  const chunks = app.recordingChunks;
  const durationMs = Math.max(0, performance.now() - app.recordingStartedAt);
  const pitchEvents = app.recordingPitchEvents.slice();
  app.recordingAudioGraph?.cleanup?.();
  app.recorder = null;
  app.recordingAudioGraph = null;
  app.recordingChunks = [];
  app.recordingPitchEvents = [];

  if (!chunks.length) {
    setRecordingStatus('No audio was captured.');
    updateRecordingControls();
    return;
  }

  const mimeType = recorder?.mimeType || chunks[0]?.type || 'audio/webm';
  const sourceBlob = new Blob(chunks, { type: mimeType });
  setRecordingStatus('Normalizing recording...');
  const normalized = await normalizeRecordingBlob(sourceBlob, mimeType);
  const id = `rec-${Date.now()}-${app.recordingCounter++}`;
  const recording = {
    id,
    name: makeRecordingName(),
    blob: normalized.blob,
    url: URL.createObjectURL(normalized.blob),
    mimeType: normalized.mimeType,
    extension: normalized.extension,
    normalized: normalized.normalized,
    gain: normalized.gain,
    durationMs,
    pitchEvents,
    createdAt: new Date(),
  };

  app.recordings.unshift(recording);
  setRecordingStatus(`Saved ${formatDuration(durationMs)} recording.`);
  renderRecordings();
  updateRecordingControls();
}

function createMediaRecorder(stream) {
  for (const mimeType of RECORDING_MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported?.(mimeType)) {
      return new MediaRecorder(stream, { mimeType });
    }
  }
  return new MediaRecorder(stream);
}

async function normalizeRecordingBlob(blob, fallbackMimeType) {
  const ctx = app.engine?.audioContext;
  if (!ctx) {
    return {
      blob,
      mimeType: fallbackMimeType,
      extension: extensionForMimeType(fallbackMimeType),
      normalized: false,
      gain: 1,
    };
  }

  try {
    const decoded = await decodeAudioDataCompat(ctx, await blob.arrayBuffer());
    const mono = downmixToMono(decoded);
    const peak = peakAbs(mono);
    if (peak < 0.00001) {
      return {
        blob,
        mimeType: fallbackMimeType,
        extension: extensionForMimeType(fallbackMimeType),
        normalized: false,
        gain: 1,
      };
    }

    const gain = Math.min(RECORDING_MAX_GAIN, RECORDING_TARGET_PEAK / peak);
    const wav = encodeStereoWav(mono, decoded.sampleRate, gain);
    return {
      blob: wav,
      mimeType: 'audio/wav',
      extension: 'wav',
      normalized: true,
      gain,
    };
  } catch (e) {
    console.warn('Recording normalization failed; keeping original encoded audio.', e);
    return {
      blob,
      mimeType: fallbackMimeType,
      extension: extensionForMimeType(fallbackMimeType),
      normalized: false,
      gain: 1,
    };
  }
}

function decodeAudioDataCompat(ctx, arrayBuffer) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = value => {
      if (!settled) {
        settled = true;
        resolve(value);
      }
    };
    const fail = error => {
      if (!settled) {
        settled = true;
        reject(error);
      }
    };

    try {
      const maybePromise = ctx.decodeAudioData(arrayBuffer.slice(0), done, fail);
      if (maybePromise?.then) maybePromise.then(done, fail);
    } catch (e) {
      fail(e);
    }
  });
}

function downmixToMono(buffer) {
  const mono = new Float32Array(buffer.length);
  const channelCount = Math.max(1, buffer.numberOfChannels);
  for (let ch = 0; ch < channelCount; ch++) {
    const data = buffer.getChannelData(ch);
    for (let i = 0; i < mono.length; i++) {
      mono[i] += data[i] / channelCount;
    }
  }
  return mono;
}

function peakAbs(samples) {
  let peak = 0;
  for (const sample of samples) {
    peak = Math.max(peak, Math.abs(sample));
  }
  return peak;
}

function encodeStereoWav(mono, sampleRate, gain) {
  const bytesPerSample = 2;
  const channels = 2;
  const dataBytes = mono.length * channels * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(buffer);

  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * bytesPerSample, true);
  view.setUint16(32, channels * bytesPerSample, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataBytes, true);

  let offset = 44;
  for (const sample of mono) {
    const scaled = Math.max(-1, Math.min(1, sample * gain));
    const pcm = scaled < 0 ? Math.round(scaled * 0x8000) : Math.round(scaled * 0x7fff);
    view.setInt16(offset, pcm, true);
    view.setInt16(offset + 2, pcm, true);
    offset += 4;
  }

  return new Blob([buffer], { type: 'audio/wav' });
}

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i++) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

function createStereoRecordingStream(micStream) {
  const ctx = app.engine?.audioContext;
  if (!ctx) return { stream: micStream, cleanup: () => {} };

  let source = null;
  let merger = null;
  try {
    source = ctx.createMediaStreamSource(micStream);
    merger = ctx.createChannelMerger(2);
    const dest = ctx.createMediaStreamDestination();

    source.connect(merger, 0, 0);
    source.connect(merger, 0, 1);
    merger.connect(dest);

    return {
      stream: dest.stream,
      cleanup: () => {
        try { source.disconnect(); } catch {}
        try { merger.disconnect(); } catch {}
      },
    };
  } catch (e) {
    console.warn('Stereo recording routing unavailable; recording the raw mic stream.', e);
    try { source?.disconnect(); } catch {}
    try { merger?.disconnect(); } catch {}
    return { stream: micStream, cleanup: () => {} };
  }
}

function recordPitchForActiveTake(msg) {
  if (app.recorder?.state !== 'recording') return;
  app.recordingPitchEvents.push({
    t: Math.max(0, performance.now() - app.recordingStartedAt),
    msg: {
      type: 'pitch',
      detected_hz: Number.isFinite(msg.detected_hz) ? msg.detected_hz : null,
      raw_moria: Number.isFinite(msg.raw_moria) ? msg.raw_moria : null,
      cell_id: isValidCellId(msg.cell_id) ? msg.cell_id : -1,
      neighbor_id: isValidCellId(msg.neighbor_id) ? msg.neighbor_id : -1,
      neighbor_vel: Number.isFinite(msg.neighbor_vel) ? msg.neighbor_vel : 0,
      confidence: Number.isFinite(msg.confidence) ? msg.confidence : 0,
      gate_open: Boolean(msg.gate_open),
    },
  });
}

function renderRecordings() {
  const list = document.getElementById('recordings-list');
  if (!list) return;
  list.innerHTML = '';

  if (!app.recordings.length) {
    const empty = document.createElement('div');
    empty.className = 'recordings-empty';
    empty.textContent = 'No recordings yet.';
    list.appendChild(empty);
    return;
  }

  for (const recording of app.recordings) {
    const row = document.createElement('div');
    row.className = 'recording-item';

    const meta = document.createElement('div');
    meta.className = 'recording-meta';
    const name = document.createElement('span');
    name.className = 'recording-name';
    name.textContent = recording.name;
    const details = document.createElement('span');
    details.className = 'recording-details';
    details.textContent = [
      formatDuration(recording.durationMs),
      recording.normalized ? 'normalized' : recording.extension,
      `${recording.pitchEvents.length} pitch points`,
    ].join(' · ');
    meta.appendChild(name);
    meta.appendChild(details);

    const actions = document.createElement('div');
    actions.className = 'recording-item-actions';

    const playBtn = document.createElement('button');
    playBtn.type = 'button';
    playBtn.textContent = app.activeRecordingPlayback?.id === recording.id ? 'Stop' : 'Play';
    playBtn.addEventListener('click', () => {
      if (app.activeRecordingPlayback?.id === recording.id) stopRecordingPlayback();
      else playRecording(recording);
    });

    const download = document.createElement('a');
    download.className = 'recording-download';
    download.href = recording.url;
    download.download = `${recording.name}.${recording.extension}`;
    download.textContent = 'Download';

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'recording-delete';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', () => deleteRecording(recording.id));

    actions.appendChild(playBtn);
    actions.appendChild(download);
    actions.appendChild(deleteBtn);
    row.appendChild(meta);
    row.appendChild(actions);
    list.appendChild(row);
  }
}

async function playRecording(recording) {
  if (app.recorder?.state === 'recording') {
    setRecordingStatus('Stop recording before playback.');
    return;
  }
  stopRecordingPlayback();
  app.singscope?.clear();
  showSingView();
  await app.ensureAudio?.();
  await ensureRecordingNormalized(recording);

  const audio = new Audio(recording.url);
  const stereoGraph = createStereoPlaybackGraph(audio);
  let idx = 0;
  let rafId = null;

  const pushDuePitch = () => {
    const t = audio.currentTime * 1000;
    while (idx < recording.pitchEvents.length && recording.pitchEvents[idx].t <= t) {
      app.singscope?.pushPitch(recording.pitchEvents[idx].msg);
      idx++;
    }
  };

  const tick = () => {
    pushDuePitch();
    if (!audio.paused && !audio.ended) {
      rafId = requestAnimationFrame(tick);
      if (app.activeRecordingPlayback) app.activeRecordingPlayback.rafId = rafId;
    }
  };

  const cleanup = () => {
    if (rafId !== null) cancelAnimationFrame(rafId);
    stereoGraph?.cleanup?.();
    if (app.activeRecordingPlayback?.audio === audio) {
      app.activeRecordingPlayback = null;
      setRecordingStatus('Playback finished.');
      renderRecordings();
      updateRecordingControls();
    }
  };

  audio.addEventListener('play', () => {
    setRecordingStatus(`Playing ${recording.name}.`);
    rafId = requestAnimationFrame(tick);
  });
  audio.addEventListener('ended', () => {
    pushDuePitch();
    cleanup();
  });
  audio.addEventListener('pause', () => {
    if (!audio.ended && app.activeRecordingPlayback?.audio === audio) cleanup();
  });

  app.activeRecordingPlayback = { id: recording.id, audio, rafId: null, stereoGraph };
  renderRecordings();
  updateRecordingControls();
  audio.play().catch(e => {
    console.error('Recording playback failed', e);
    setRecordingStatus('Could not play this recording.');
    cleanup();
  });
}

async function ensureRecordingNormalized(recording) {
  if (recording.normalized) return;
  setRecordingStatus('Normalizing recording...');
  const normalized = await normalizeRecordingBlob(recording.blob, recording.mimeType);
  if (!normalized.normalized) return;

  URL.revokeObjectURL(recording.url);
  recording.blob = normalized.blob;
  recording.url = URL.createObjectURL(normalized.blob);
  recording.mimeType = normalized.mimeType;
  recording.extension = normalized.extension;
  recording.normalized = true;
  recording.gain = normalized.gain;
  renderRecordings();
}

function createStereoPlaybackGraph(audio) {
  const ctx = app.engine?.audioContext;
  if (!ctx) return null;

  try {
    const source = ctx.createMediaElementSource(audio);
    const merger = ctx.createChannelMerger(2);
    source.connect(merger, 0, 0);
    source.connect(merger, 0, 1);
    merger.connect(ctx.destination);
    return {
      cleanup: () => {
        try { source.disconnect(); } catch {}
        try { merger.disconnect(); } catch {}
      },
    };
  } catch (e) {
    console.warn('Stereo recording playback routing unavailable; using direct element output.', e);
    return null;
  }
}

function stopRecordingPlayback() {
  const playback = app.activeRecordingPlayback;
  if (!playback) return;
  if (playback.rafId !== null) cancelAnimationFrame(playback.rafId);
  playback.stereoGraph?.cleanup?.();
  playback.audio.pause();
  playback.audio.currentTime = 0;
  app.activeRecordingPlayback = null;
  setRecordingStatus('Playback stopped.');
  renderRecordings();
  updateRecordingControls();
}

function deleteRecording(id) {
  const idx = app.recordings.findIndex(recording => recording.id === id);
  if (idx === -1) return;
  if (app.activeRecordingPlayback?.id === id) stopRecordingPlayback();
  const [recording] = app.recordings.splice(idx, 1);
  URL.revokeObjectURL(recording.url);
  setRecordingStatus(app.recordings.length ? 'Recording deleted.' : 'No recordings yet.');
  renderRecordings();
  updateRecordingControls();
}

function updateRecordingControls() {
  const recordBtn = document.getElementById('record-toggle-btn');
  const stopPlaybackBtn = document.getElementById('record-stop-playback-btn');
  const isRecording = app.recorder?.state === 'recording';
  if (recordBtn) {
    recordBtn.textContent = isRecording ? 'Stop Recording' : 'Record';
    recordBtn.classList.toggle('recording', isRecording);
  }
  if (stopPlaybackBtn) {
    stopPlaybackBtn.disabled = !app.activeRecordingPlayback;
  }
  if (isRecording) {
    setRecordingStatus(`Recording ${formatDuration(performance.now() - app.recordingStartedAt)}`);
  }
}

function setRecordingStatus(text) {
  const status = document.getElementById('recording-status');
  if (status) status.textContent = text;
}

function makeRecordingName() {
  const stamp = new Date().toISOString()
    .replace(/\.\d+Z$/, '')
    .replace(/[:-]/g, '')
    .replace('T', '-');
  return `chant-${stamp}`;
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function extensionForMimeType(mimeType) {
  if (mimeType.includes('mp4')) return 'm4a';
  if (mimeType.includes('aac')) return 'aac';
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
}

function showSingView() {
  if (document.getElementById('mobile-tabs')?.offsetParent === null) return;
  if (location.hash === '#sing') return;
  history.replaceState(null, '', '#sing');
  window.dispatchEvent(new Event('hashchange'));
}

// ── Preset save/load ──────────────────────────────────────────────────────────

const STORAGE_KEY = 'chanterlab_presets';
const LEGACY_STORAGE_KEY = 'byzorgan_presets';

function loadStoredPresets() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return JSON.parse(stored);

    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (!legacy) return {};

    const presets = JSON.parse(legacy);
    saveStoredPresets(presets);
    return presets;
  } catch {
    return {};
  }
}

function saveStoredPresets(presets) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}

function renderSavedPresets() {
  const list = document.getElementById('saved-presets-list');
  list.innerHTML = '';
  const presets = loadStoredPresets();
  Object.keys(presets).sort().forEach(name => {
    const row = document.createElement('div');
    row.className = 'saved-preset-item';

    const nameEl = document.createElement('span');
    nameEl.className = 'saved-preset-name';
    nameEl.textContent = name;

    const loadBtn = document.createElement('button');
    loadBtn.className = 'load-preset-btn';
    loadBtn.title = 'Load';
    loadBtn.textContent = '↑';
    loadBtn.addEventListener('click', () => {
      try {
        app.grid = JsTuningGrid.fromJson(presets[name]);
        app.refNiHz = app.grid.refNiHz;
        gridChanged();
      } catch (e) {
        console.error('Failed to load preset', e);
      }
    });

    const delBtn = document.createElement('button');
    delBtn.className = 'del-preset-btn';
    delBtn.title = 'Delete';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', () => {
      const stored = loadStoredPresets();
      delete stored[name];
      saveStoredPresets(stored);
      renderSavedPresets();
    });

    row.appendChild(loadBtn);
    row.appendChild(nameEl);
    row.appendChild(delBtn);
    list.appendChild(row);
  });
}

function wirePresetSaveLoad() {
  document.getElementById('save-btn').addEventListener('click', () => {
    const name = document.getElementById('preset-name-input').value.trim();
    if (!name) return;
    try {
      const stored = loadStoredPresets();
      stored[name] = app.grid.toJson();
      saveStoredPresets(stored);
      renderSavedPresets();
    } catch (e) {
      console.error('Failed to serialize grid', e);
    }
  });

  renderSavedPresets();
}

// ── Start ─────────────────────────────────────────────────────────────────────

main().catch(console.error);
