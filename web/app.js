import init, { JsTuningGrid } from './pkg/chanterlab_core.js';
import { ScaleLadder    } from './ui/scale_ladder.js?v=chant-script-engine-phase2f';
import { AudioEngine    } from './audio/audio_engine.js?v=reference-player-1';
import { VKeyboard      } from './ui/vkeyboard.js?v=0.2.0-alpha.0';
import { Singscope      } from './ui/singscope.js?v=reference-player-1';
import { NoteIndicator  } from './ui/note_indicator.js?v=0.2.0-alpha.0';
import { ExerciseMode   } from './ui/exercise_mode.js?v=0.2.0-alpha.0';
import { Metronome      } from './ui/metronome.js?v=0.2.0-alpha.0';
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
  listGlyphImportTokens,
  listMinimalGlyphImportTokens,
} from './score/glyph_import.js?v=chant-script-engine-phase6w';
import { formatDiagnostic } from './score/diagnostics.js?v=chant-script-engine-phase6d';
import {
  editGlyphImportText,
} from './score/glyph_editor.js?v=chant-script-engine-phase6h';
import {
  findGlyphImportSampleFixture,
  listGlyphImportSampleFixtures,
} from './score/glyph_import_samples.js?v=chant-script-engine-phase6h';
import {
  glyphPreviewFromText,
  glyphPreviewSourceKind,
} from './score/glyph_render.js?v=chant-script-engine-phase6h';
import {
  listGlyphClusterCatalog,
} from './score/glyph_cluster_catalog.js?v=chant-script-engine-phase6v';
import {
  createGlyphClusterElement,
  formatGlyphClusterSemantic,
} from './score/glyph_cluster_render.js?v=chant-script-engine-phase6v';
import {
  applyGlyphScoreCluster,
  clearGlyphScoreEditorState,
  createGlyphScoreEditorState,
  glyphScoreClusterInfo,
  glyphScoreGroupLabel,
  removeGlyphScoreGroup,
  serializeGlyphScoreEditorState,
} from './score/glyph_score_editor.js?v=chant-script-engine-phase6w';
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
  // { label: 'Grave Diatonic',genus: 'GraveDiatonic',  degree: 'Ga'  },
  // { label: 'Enharmonic Zo', genus: 'EnharmonicZo',   degree: 'Zo'  },
  // { label: 'Enharmonic Ga', genus: 'EnharmonicGa',   degree: 'Ga'  },
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
const SCORE_GLYPH_ALL_IMPORT_TOKENS = listGlyphImportTokens();
const SCORE_GLYPH_IMPORT_TOKEN_BY_NAME = new Map(SCORE_GLYPH_ALL_IMPORT_TOKENS.map(token => [token.glyphName, token]));
const SCORE_GLYPH_CLUSTER_CATALOG = listGlyphClusterCatalog();
const SCORE_GLYPH_CLUSTER_BY_ID = new Map(SCORE_GLYPH_CLUSTER_CATALOG.map(cluster => [cluster.id, cluster]));
const SCORE_GLYPH_CLUSTER_CATEGORIES = [
  'Basic Quantities',
  'Attachment Examples',
  'Rests',
  'Duration Signs',
  'Timing Signs',
  'Pthora And Chroa',
  'Oligon Compounds',
  'Petasti Compounds',
  'Kentimata Compounds',
  'Martyria Checkpoints',
].filter(category => SCORE_GLYPH_CLUSTER_CATALOG.some(cluster => cluster.category === category));
const SCORE_IMPORT_DEGREES = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo'];
const SCORE_GLYPH_KEYBOARD_ROLES = [
  { role: 'quantity', label: 'Quantity' },
  { role: 'rest', label: 'Rest' },
  { role: 'temporal', label: 'Timing' },
  { role: 'duration', label: 'Beats' },
  { role: 'pthora', label: 'Pthora' },
  { role: 'qualitative', label: 'Chroa' },
  { role: 'tempo', label: 'Tempo' },
  { role: 'martyria-note', label: 'Martyria Note' },
  { role: 'martyria-sign', label: 'Martyria Sign' },
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
const MEDIA_PROXY_QUERY_PARAM = 'mediaProxy';
const METUBE_QUERY_PARAM = 'metube';
const DEFAULT_METUBE_BASE_URL = 'https://metube.lab.alwaysdobetterllc.com';
const METUBE_POLL_INTERVAL_MS = 2000;
const METUBE_TIMEOUT_MS = 10 * 60 * 1000;
const REFERENCE_SEEK_STEP_MS = 10000;
const REFERENCE_TRACE_PREFILL_MS = 12000;
const REFERENCE_PITCH_MIN_MORIA = -72;
const REFERENCE_PITCH_MAX_MORIA = 72;

const app = {
  grid:            null,
  ladder:          null,
  singscope:       null,
  noteIndicator:   null,
  exercise:        null,
  scorePractice:   null,
  scorePracticeModeVisible: false,
  scorePracticeGridSnapshot: null,
  setScorePracticeMode: null,
  onScorePracticeModeChange: null,
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
  // Synth timbre — one of "Sine", "Organ", "Reed", "Flute", "String".
  synthVoicing:   'Organ',
  // Metronome state
  metronome:        null,
  metronomeBpm:     80,
  metronomeBeats:   4,
  metronomeVolume:  0.5,
  scorePracticeIsonOverride: null,
  scorePracticeManualIsonState: null,
  // Mic / PSOLA correction state. Off by default — chanters should hear
  // their own voice first and opt in to correction as a training aid.
  correctionEnabled: false,
  correctionVolume:  0.5,
  // Mic input makeup gain (linear). iOS Safari delivers very low getUserMedia
  // levels so this defaults higher than 1×; users can dial to taste.
  voiceInputGain:    6,
  // PSOLA pitch-corrected playback (independent of dry voice monitor).
  psolaEnabled:      false,
  psolaVolume:       0.5,
  // Reverb send for the voice/PSOLA mix bus.
  monitorReverbWet:  0.2,
  voiceSnapTable:    [],
  voiceLastCellId:   null,
  voiceCurrentCellId: null,
  synthFollowEnabled: false,
  synthFollowVolume:  0.5,
  synthFollowCellId:  null,
  synthFollowMisses:  0,
  zoomFollow:         false,
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
  referencePlaybackRate: 1,
  referencePitchShiftMoria: 0,
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
  wireVoicingControls();
  wireMetronomeControls();
  wireCorrectionControls();
  wireSynthFollowControls();
  wirePsolaControls();
  wireReverbControl();
  wireMicGainControl();
  wireRecordingControls();
  wireZoomFollowControl();
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
    if (app.engine.ready) {
      if (app.engine.audioContext?.state === 'suspended') {
        await app.engine.audioContext.resume();
      }
      return;
    }
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

  const normalized = normalizePitchMessage(msg, app.voiceLastCellId);
  msg = normalized.msg;
  app.voiceLastCellId = normalized.lastCellId;
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

  // Zoom follow target from detected pitch.
  if (app.zoomFollow) {
    if (msg.gate_open && Number.isFinite(msg.snap_moria)) {
      app.ladder.setFollowTarget(msg.snap_moria);
    } else if (!msg.gate_open) {
      app.ladder.setFollowTarget(null);
    }
  }
}

function normalizePitchMessage(input, lastCellId = null, options = {}) {
  const msg = { ...input };
  const pitchShiftMoria = Number.isFinite(options.pitchShiftMoria)
    ? options.pitchShiftMoria
    : 0;
  let rawMoria = null;
  if (
    typeof msg.detected_hz === 'number' &&
    Number.isFinite(msg.detected_hz) &&
    msg.detected_hz > 0
  ) {
    rawMoria = 72 * Math.log2(msg.detected_hz / app.refNiHz);
  } else if (Number.isFinite(msg.raw_moria)) {
    rawMoria = msg.raw_moria;
  }

  if (rawMoria !== null) {
    msg.raw_moria = rawMoria + pitchShiftMoria;
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
    ? nearestEnabledMoriaCell(msg.raw_moria, lastCellId)
    : null;
  if (snap) {
    msg.cell_id = snap.primary;
    msg.snap_moria = snap.primary_moria;
    msg.neighbor_id = snap.neighbor?.cell_id ?? -1;
    msg.neighbor_moria = snap.neighbor?.moria ?? null;
    msg.neighbor_vel = snap.neighbor?.vel ?? 0;
    lastCellId = snap.primary;
  } else if (!msg.gate_open) {
    lastCellId = null;
  }

  return { msg, lastCellId };
}

function setScorePracticeModeVisible(visible) {
  const nextVisible = !!visible;
  app.scorePracticeModeVisible = nextVisible;
  document.body.classList.toggle('score-practice-active', nextVisible);
  const button = document.getElementById('score-practice-mode-btn');
  if (button) {
    button.classList.toggle('active', nextVisible);
    button.setAttribute('aria-pressed', nextVisible ? 'true' : 'false');
    button.textContent = nextVisible ? 'Practice On' : 'Practice';
  }
  app.onScorePracticeModeChange?.(nextVisible);
  requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
}

function wireScorePracticePrototype() {
  const modeButton = document.getElementById('score-practice-mode-btn');
  if (scorePracticeExplicitlyDisabled()) {
    if (modeButton) modeButton.hidden = true;
    return;
  }
  modeButton?.addEventListener('click', () => {
    setScorePracticeModeVisible(!app.scorePracticeModeVisible);
  });
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
  if (scorePracticeExplicitlyRequested(params)) setScorePracticeModeVisible(true);
  let rawLoadedCompiled = null;
  let activeRawCompiled = null;
  let compiled = null;
  try {
    rawLoadedCompiled = compileChantScriptExample(exampleId);
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
    importOpen: scorePracticeImportOpen(params),
    importOptions,
  });

  mainView.appendChild(canvas);
  mainView.appendChild(status);
  mainView.appendChild(controls.el);
  mainView.classList.add('score-practice-enabled');
  document.body.classList.toggle('score-practice-active', app.scorePracticeModeVisible);

  app.scorePractice = new ScorePracticePrototype(canvas, {
    enabled: app.scorePracticeModeVisible,
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

  const updatePlayPauseLabel = () => {
    controls.playPause.textContent = app.scorePractice?.isRunning() ? 'Pause' : 'Play';
  };

  const syncScorePracticeSingscopeTiming = visible => {
    app.singscope?.setTraceTiming({
      anchorRatio: visible ? SCORE_PRACTICE_CROSSHAIR_RATIO : 1,
      pxPerSecond: visible ? scrollPxPerSecond : null,
    });
  };

  const restoreRegularSingTuning = () => {
    if (!app.scorePracticeGridSnapshot) return;
    try {
      app.grid = JsTuningGrid.fromJson(app.scorePracticeGridSnapshot);
      app.scorePracticeGridSnapshot = null;
      gridChanged();
    } catch (e) {
      console.warn('Unable to restore pre-practice tuning grid', e);
      app.scorePracticeGridSnapshot = null;
    }
  };

  const activateLoadedScore = () => {
    if (!rawLoadedCompiled) return;
    if (!app.scorePracticeGridSnapshot) {
      try {
        app.scorePracticeGridSnapshot = app.grid.toJson();
      } catch (e) {
        console.warn('Unable to snapshot pre-practice tuning grid', e);
      }
    }
    applyCompiledScoreInitialTuning(rawLoadedCompiled);
    compiled = retuneCompiledScore(rawLoadedCompiled);
    activeRawCompiled = rawLoadedCompiled;
    app.scorePractice.setCompiledScore(compiled);
    app.scorePractice.setRowMap(app.ladder.rowMap);
    app.scorePractice.seek(app.scorePractice.nowMs);
    updatePlayPauseLabel();
  };

  app.onScorePracticeModeChange = visible => {
    if (!app.scorePractice) return;
    syncScorePracticeSingscopeTiming(visible);
    if (visible) {
      app.scorePractice.setEnabled(true);
      activateLoadedScore();
    } else {
      app.scorePractice.setEnabled(false);
      releaseScorePracticeIson();
      restoreRegularSingTuning();
      updatePlayPauseLabel();
    }
  };

  const loadCompiledScore = rawCompiled => {
    rawLoadedCompiled = rawCompiled;
    activeRawCompiled = null;
    compiled = rawCompiled;
    app.scorePractice.stop();
    app.scorePractice.setCompiledScore(rawCompiled);
    app.scorePractice.setRowMap(app.ladder.rowMap);
    if (app.scorePracticeModeVisible) activateLoadedScore();
    updatePlayPauseLabel();
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
    renderScorePracticeGlyphPreview(controls);
  });
  controls.importSource?.addEventListener('change', () => renderScorePracticeGlyphPreview(controls));
  controls.importText?.addEventListener('input', () => renderScorePracticeGlyphPreview(controls));
  controls.importPreview?.addEventListener('click', event => {
    const cluster = event.target.closest('[data-source-start][data-source-end]');
    if (!cluster) return;
    const start = Number(cluster.dataset.sourceStart);
    const end = Number(cluster.dataset.sourceEnd);
    if (!Number.isInteger(start) || !Number.isInteger(end)) return;
    controls.importText.focus();
    controls.importText.setSelectionRange(start, end);
  });
  controls.importKeyboard?.addEventListener('click', event => {
    const button = event.target.closest('[data-glyph-name]');
    if (!button) return;
    insertScorePracticeImportToken(
      controls.importText,
      button.dataset.glyphName,
      controls.importSource.value
    );
    controls.importStatus.textContent = 'edited';
    renderScorePracticeImportDiagnostics(controls.importDiagnostics, []);
    renderScorePracticeGlyphPreview(controls);
  });
  controls.importEditorOpen?.addEventListener('click', () => {
    openGlyphScoreEditor(controls);
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
    if (app.scorePracticeModeVisible) activateLoadedScore();
    app.scorePractice.restart();
    updatePlayPauseLabel();
  });
  controls.playPause.addEventListener('click', () => {
    if (app.scorePractice.isRunning()) {
      app.scorePractice.stop();
      updatePlayPauseLabel();
    } else {
      if (app.scorePracticeModeVisible && activeRawCompiled !== rawLoadedCompiled) activateLoadedScore();
      app.scorePractice.start();
      updatePlayPauseLabel();
    }
  });
  controls.speed.addEventListener('input', () => {
    const nextRate = clampScorePracticePlaybackRate(Number(controls.speed.value));
    controls.speedReadout.textContent = formatPlaybackRate(nextRate);
    syncScorePracticeSingscopeTiming(app.scorePracticeModeVisible);
    app.scorePractice.setTiming({
      playbackRate: nextRate,
      pxPerSecond: scrollPxPerSecond,
    });
  });

  loadExample(exampleId);
  renderScorePracticeGlyphPreview(controls);
  updatePlayPauseLabel();
  app.onScorePracticeModeChange(app.scorePracticeModeVisible);
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

function scorePracticeExplicitlyRequested(params) {
  const queryValue = params.get('scorePractice') ?? params.get('score-practice');
  return queryValue !== null && ['1', 'true', 'yes', 'on'].includes(queryValue.toLowerCase());
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

function scorePracticeImportOpen(params) {
  const raw = params.get('scoreImportOpen') ?? params.get('score-import-open');
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
  playPause.textContent = 'Play';

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
    const importCollapsed = !options.importOpen;
    el.classList.toggle('import-collapsed', importCollapsed);
    const importOptions = options.importOptions ?? {};
    const samples = listGlyphImportSampleFixtures();
    const selectedSample = findGlyphImportSampleFixture(importOptions.sampleId) ?? samples[0];

    const importToggle = document.createElement('button');
    importToggle.type = 'button';
    importToggle.className = 'score-practice-import-toggle';
    importToggle.textContent = importCollapsed ? 'Import' : 'Hide';
    importToggle.setAttribute('aria-expanded', importCollapsed ? 'false' : 'true');

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

    const importPreview = document.createElement('div');
    importPreview.className = 'score-practice-glyph-preview';
    importPreview.setAttribute('aria-label', 'Glyph preview');

    const importKeyboard = buildScorePracticeGlyphKeyboard();

    const importEditorOpen = document.createElement('button');
    importEditorOpen.type = 'button';
    importEditorOpen.className = 'score-practice-glyph-editor-open';
    importEditorOpen.textContent = 'Compose';

    const importApply = document.createElement('button');
    importApply.type = 'button';
    importApply.className = 'score-practice-import-apply';
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
      importPreview,
      importText,
      importKeyboard,
      importEditorOpen,
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
      importPreview,
      importText,
      importKeyboard,
      importEditorOpen,
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

function renderScorePracticeGlyphPreview(controls) {
  if (!controls?.importPreview || !controls?.importText) return;
  const previewEl = controls.importPreview;
  previewEl.innerHTML = '';

  const sourceText = controls.importText.value;
  const preview = glyphPreviewFromText(sourceText, {
    source: glyphPreviewSourceKind(controls.importSource?.value ?? 'glyph'),
  });

  const strip = document.createElement('div');
  strip.className = 'score-practice-glyph-preview-strip';
  if (!preview.clusters.length) {
    const empty = document.createElement('span');
    empty.className = 'score-practice-glyph-preview-empty';
    empty.textContent = 'No glyphs';
    strip.appendChild(empty);
  }

  for (const cluster of preview.clusters) {
    const aboveItems = [...cluster.slots.above, ...cluster.slots.right];
    const clusterEl = document.createElement('button');
    clusterEl.type = 'button';
    clusterEl.className = [
      'score-practice-glyph-cluster',
      cluster.kind,
      aboveItems.length ? 'has-above' : '',
      cluster.slots.below.length ? 'has-below' : '',
    ].filter(Boolean).join(' ');
    clusterEl.title = cluster.label;
    const span = codePointSpanToStringSpan(sourceText, cluster.sourceSpan);
    if (span) {
      clusterEl.dataset.sourceStart = String(span.start);
      clusterEl.dataset.sourceEnd = String(span.end);
    }

    appendGlyphPreviewSlot(clusterEl, 'above', aboveItems);
    appendGlyphPreviewSlot(clusterEl, 'main', cluster.slots.main);
    appendGlyphPreviewSlot(clusterEl, 'below', cluster.slots.below);

    const label = document.createElement('span');
    label.className = 'score-practice-glyph-cluster-label';
    label.textContent = compactGlyphPreviewLabel(cluster.label);
    clusterEl.appendChild(label);
    strip.appendChild(clusterEl);
  }

  const summary = document.createElement('div');
  summary.className = 'score-practice-glyph-preview-summary';
  const errors = preview.diagnostics.filter(diagnostic => diagnostic.severity === 'error').length;
  const warnings = preview.diagnostics.filter(diagnostic => diagnostic.severity === 'warning').length;
  summary.textContent = [
    `${preview.clusters.length} group${preview.clusters.length === 1 ? '' : 's'}`,
    errors ? `${errors} error${errors === 1 ? '' : 's'}` : '',
    warnings ? `${warnings} warning${warnings === 1 ? '' : 's'}` : '',
  ].filter(Boolean).join(' · ');

  previewEl.append(strip, summary);
  previewEl.classList.toggle('has-errors', errors > 0);
}

function appendGlyphPreviewSlot(clusterEl, slotName, items) {
  const row = document.createElement('span');
  row.className = `score-practice-glyph-slot ${slotName}`;
  for (const item of items ?? []) {
    row.appendChild(glyphPreviewItemElement(item));
  }
  clusterEl.appendChild(row);
}

function glyphPreviewItemElement(item) {
  const el = document.createElement('span');
  el.className = `score-practice-glyph-preview-item ${item.kind ?? 'unknown'}`;
  el.textContent = item.text || '?';
  el.title = item.label ?? item.glyphName ?? item.raw ?? '';
  return el;
}

function compactGlyphPreviewLabel(label) {
  return String(label ?? '')
    .replaceAll('fthora', '')
    .replaceAll('Chromatic', 'Chr')
    .replaceAll('Above', '')
    .replaceAll('gorgon', 'gor')
    .slice(0, 28);
}

function codePointSpanToStringSpan(text, span) {
  if (!Number.isInteger(span?.start) || !Number.isInteger(span?.end)) return undefined;
  const chars = Array.from(text ?? '');
  const start = chars.slice(0, span.start).join('').length;
  const end = chars.slice(0, span.end).join('').length;
  return { start, end };
}

function setScorePracticeImportCollapsed(controls, collapsed) {
  if (!controls?.el || !controls?.importToggle) return;
  controls.el.classList.toggle('import-collapsed', collapsed);
  controls.importToggle.textContent = collapsed ? 'Import' : 'Hide';
  controls.importToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

function insertScorePracticeImportToken(textarea, glyphName, source) {
  if (!textarea || !glyphName) return;
  const edit = editGlyphImportText(textarea.value, {
    glyphName,
    source,
    selectionStart: textarea.selectionStart,
    selectionEnd: textarea.selectionEnd,
  });
  textarea.value = edit.text;
  textarea.focus();
  textarea.setSelectionRange(edit.selectionStart, edit.selectionEnd);
}

function openGlyphScoreEditor(controls) {
  const editor = ensureGlyphScoreEditor(controls);
  renderGlyphScoreEditor(editor);
  if (typeof editor.dialog.showModal === 'function' && !editor.dialog.open) {
    editor.dialog.showModal();
  } else {
    editor.dialog.hidden = false;
    editor.dialog.setAttribute('open', '');
  }
}

function ensureGlyphScoreEditor(controls) {
  if (controls.glyphScoreEditor) return controls.glyphScoreEditor;

  const dialog = document.createElement('dialog');
  dialog.className = 'glyph-score-editor-dialog';
  dialog.setAttribute('aria-label', 'Glyph score editor');

  const shell = document.createElement('div');
  shell.className = 'glyph-score-editor-shell';

  const header = document.createElement('div');
  header.className = 'glyph-score-editor-header';
  const headingWrap = document.createElement('div');
  const title = document.createElement('h2');
  title.textContent = 'Glyph Score Editor';
  headingWrap.appendChild(title);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'glyph-score-editor-close';
  close.setAttribute('aria-label', 'Close glyph score editor');
  close.textContent = 'X';
  header.append(headingWrap, close);

  const toolbar = document.createElement('div');
  toolbar.className = 'glyph-score-editor-toolbar';
  const category = document.createElement('select');
  category.className = 'glyph-score-editor-category';
  category.setAttribute('aria-label', 'Glyph category');
  for (const categoryName of SCORE_GLYPH_CLUSTER_CATEGORIES) {
    const option = document.createElement('option');
    option.value = categoryName;
    option.textContent = categoryName;
    category.appendChild(option);
  }
  const status = document.createElement('div');
  status.className = 'glyph-score-editor-status';
  status.textContent = 'Ready';
  toolbar.append(category, status);

  const composer = document.createElement('div');
  composer.className = 'glyph-score-editor-composer';
  composer.setAttribute('aria-label', 'Composed glyph score');

  const grid = document.createElement('div');
  grid.className = 'glyph-score-editor-grid';
  grid.setAttribute('aria-label', 'Glyph catalog');

  const footer = document.createElement('div');
  footer.className = 'glyph-score-editor-footer';
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'glyph-score-editor-clear';
  clear.textContent = 'Clear';
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'glyph-score-editor-remove';
  remove.textContent = 'Remove Selected';
  const use = document.createElement('button');
  use.type = 'button';
  use.className = 'glyph-score-editor-use';
  use.textContent = 'Use in Import';
  footer.append(clear, remove, use);

  shell.append(header, toolbar, composer, grid, footer);
  dialog.appendChild(shell);
  document.body.appendChild(dialog);

  const editor = {
    controls,
    dialog,
    category,
    status,
    composer,
    grid,
    clear,
    remove,
    use,
    state: createGlyphScoreEditorState(),
  };

  close.addEventListener('click', () => closeGlyphScoreEditor(editor));
  category.addEventListener('change', () => renderGlyphScoreEditorCatalog(editor));
  clear.addEventListener('click', () => {
    editor.state = clearGlyphScoreEditorState();
    renderGlyphScoreEditor(editor);
  });
  remove.addEventListener('click', () => {
    editor.state = removeGlyphScoreGroup(editor.state, editor.state.selectedIndex);
    renderGlyphScoreEditor(editor);
  });
  use.addEventListener('click', () => {
    const text = serializeGlyphScoreEditorState(editor.state, {
      source: editor.controls.importSource?.value ?? 'glyph',
    });
    if (!text) {
      editor.status.textContent = 'Add at least one importable glyph first.';
      return;
    }
    editor.controls.importText.value = text;
    editor.controls.importStatus.textContent = 'composed';
    renderScorePracticeImportDiagnostics(editor.controls.importDiagnostics, []);
    renderScorePracticeGlyphPreview(editor.controls);
    closeGlyphScoreEditor(editor);
  });
  composer.addEventListener('click', event => {
    const removeButton = event.target.closest('[data-remove-group-index]');
    if (removeButton) {
      editor.state = removeGlyphScoreGroup(editor.state, Number(removeButton.dataset.removeGroupIndex));
      renderGlyphScoreEditor(editor);
      return;
    }
    const groupButton = event.target.closest('[data-group-index]');
    if (!groupButton) return;
    editor.state = createGlyphScoreEditorState({
      ...editor.state,
      selectedIndex: Number(groupButton.dataset.groupIndex),
    });
    renderGlyphScoreEditor(editor);
  });
  grid.addEventListener('click', event => {
    const button = event.target.closest('[data-cluster-id]');
    if (!button) return;
    const cluster = SCORE_GLYPH_CLUSTER_BY_ID.get(button.dataset.clusterId);
    if (!cluster) return;
    editor.state = applyGlyphScoreCluster(editor.state, cluster);
    renderGlyphScoreEditor(editor);
  });

  controls.glyphScoreEditor = editor;
  return editor;
}

function closeGlyphScoreEditor(editor) {
  if (typeof editor.dialog.close === 'function' && editor.dialog.open) {
    editor.dialog.close();
  } else {
    editor.dialog.hidden = true;
    editor.dialog.removeAttribute('open');
  }
}

function renderGlyphScoreEditor(editor) {
  renderGlyphScoreEditorComposer(editor);
  renderGlyphScoreEditorCatalog(editor);
  editor.status.textContent = editor.state.status || (
    editor.state.groups.length
      ? `${editor.state.groups.length} group${editor.state.groups.length === 1 ? '' : 's'}`
      : 'Choose a quantity to start'
  );
}

function renderGlyphScoreEditorComposer(editor) {
  editor.composer.innerHTML = '';
  if (!editor.state.groups.length) {
    const empty = document.createElement('div');
    empty.className = 'glyph-score-editor-empty';
    empty.textContent = 'No glyphs yet';
    editor.composer.appendChild(empty);
    editor.remove.disabled = true;
    editor.use.disabled = true;
    return;
  }

  editor.remove.disabled = false;
  editor.use.disabled = false;
  editor.state.groups.forEach((group, index) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'glyph-score-editor-group';
    if (index === editor.state.selectedIndex) item.classList.add('selected');
    item.dataset.groupIndex = String(index);
    item.title = glyphScoreGroupLabel(group);

    const cluster = glyphScoreClusterFromGroup(group, index);
    const visual = document.createElement('span');
    visual.className = 'glyph-score-editor-group-visual';
    visual.appendChild(createGlyphClusterElement(cluster, document));
    const label = document.createElement('span');
    label.className = 'glyph-score-editor-group-label';
    label.textContent = String(index + 1);
    item.append(visual, label);
    editor.composer.appendChild(item);
  });
}

function renderGlyphScoreEditorCatalog(editor) {
  editor.grid.innerHTML = '';
  const categoryName = editor.category.value || SCORE_GLYPH_CLUSTER_CATEGORIES[0];
  const clusters = SCORE_GLYPH_CLUSTER_CATALOG.filter(cluster => cluster.category === categoryName);
  for (const cluster of clusters) {
    const info = glyphScoreClusterInfo(cluster);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'glyph-score-editor-catalog-item';
    button.classList.toggle('visual-only', !info.importable);
    button.dataset.clusterId = cluster.id;
    button.title = info.importable
      ? formatGlyphClusterSemantic(cluster.semantic)
      : info.reason;

    const visual = document.createElement('span');
    visual.className = 'glyph-score-editor-catalog-visual';
    visual.appendChild(createGlyphClusterElement(cluster, document));
    const label = document.createElement('span');
    label.className = 'glyph-score-editor-catalog-label';
    label.textContent = cluster.label;
    const semantic = document.createElement('span');
    semantic.className = 'glyph-score-editor-catalog-semantic';
    semantic.textContent = info.importable
      ? (info.insertion === 'modifier' ? 'attach' : 'add')
      : 'visual only';
    button.append(visual, label, semantic);
    editor.grid.appendChild(button);
  }
}

function glyphScoreClusterFromGroup(group, index) {
  return {
    id: `composed-${index}`,
    category: 'Composed',
    label: glyphScoreGroupLabel(group),
    semantic: { kind: 'neume' },
    components: group.tokenNames.map(glyphName => ({
      glyphName,
      slot: glyphScoreTokenSlot(glyphName),
      role: glyphScoreTokenRole(glyphName),
    })),
  };
}

function glyphScoreTokenSlot(glyphName) {
  const token = SCORE_GLYPH_IMPORT_TOKEN_BY_NAME.get(glyphName);
  if (token?.role === 'quantity'
    || token?.role === 'rest'
    || token?.role === 'tempo'
    || token?.role === 'martyria-note') {
    return 'main';
  }
  if (token?.role === 'martyria-sign') return 'below';
  return 'above';
}

function glyphScoreTokenRole(glyphName) {
  const token = SCORE_GLYPH_IMPORT_TOKEN_BY_NAME.get(glyphName);
  return token?.role ?? 'unknown';
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
    setScorePracticeModeVisible(view === 'train');
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
  const toggleBtn    = document.getElementById('ison-toggle-btn');
  const degreeRow    = document.getElementById('ison-degree-buttons');
  const octaveSelect = document.getElementById('ison-octave-select');
  const volSlider    = document.getElementById('ison-volume-slider');

  toggleBtn.addEventListener('click', () => {
    app.isonEnabled = !app.isonEnabled;
    toggleBtn.textContent = app.isonEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.isonEnabled);
    updateIsonVoice(JSON.parse(app.grid.cellsJson()));
  });

  degreeRow.addEventListener('click', e => {
    const btn = e.target.closest('.ison-degree-btn');
    if (!btn) return;
    app.isonDegree = btn.dataset.degree;
    syncIsonControls();
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
  const degreeRow = document.getElementById('ison-degree-buttons');
  const octaveSelect = document.getElementById('ison-octave-select');
  const volSlider = document.getElementById('ison-volume-slider');
  if (toggleBtn) {
    toggleBtn.textContent = app.isonEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.isonEnabled);
  }
  if (degreeRow) {
    for (const btn of degreeRow.querySelectorAll('.ison-degree-btn')) {
      btn.classList.toggle('active', btn.dataset.degree === app.isonDegree);
    }
  }
  if (octaveSelect) {
    const octaveValue = String(app.isonOctave);
    octaveSelect.value = octaveValue;
    for (const option of octaveSelect.options) {
      option.selected = option.value === octaveValue;
    }
  }
  if (volSlider) volSlider.value = String(app.isonVolume);
}

function wireVoicingControls() {
  const row = document.getElementById('voicing-buttons');
  if (!row) return;

  app.engine.setVoicing(app.synthVoicing);
  syncVoicingControls();

  row.addEventListener('click', e => {
    const btn = e.target.closest('.voicing-btn');
    if (!btn) return;
    app.synthVoicing = btn.dataset.voicing;
    app.engine.setVoicing(app.synthVoicing);
    syncVoicingControls();
  });
}

function syncVoicingControls() {
  const row = document.getElementById('voicing-buttons');
  if (!row) return;
  for (const btn of row.querySelectorAll('.voicing-btn')) {
    btn.classList.toggle('active', btn.dataset.voicing === app.synthVoicing);
  }
}

function wireMetronomeControls() {
  const toggleBtn   = document.getElementById('metronome-toggle-btn');
  const bpmInput    = document.getElementById('metronome-bpm-input');
  const beatsSelect = document.getElementById('metronome-beats-select');
  const volSlider   = document.getElementById('metronome-volume-slider');
  const pips        = document.getElementById('metronome-pips');
  if (!toggleBtn) return;

  const m = new Metronome(app.engine);
  app.metronome = m;
  m.setBpm(app.metronomeBpm);
  m.setBeats(app.metronomeBeats);
  m.setVolume(app.metronomeVolume);
  bpmInput.value    = String(app.metronomeBpm);
  beatsSelect.value = String(app.metronomeBeats);
  volSlider.value   = String(app.metronomeVolume);

  function rebuildPips() {
    pips.innerHTML = '';
    for (let i = 0; i < app.metronomeBeats; i++) {
      const dot = document.createElement('span');
      dot.className = 'metronome-pip';
      pips.appendChild(dot);
    }
  }
  rebuildPips();

  m.onBeat = idx => {
    const dots = pips.querySelectorAll('.metronome-pip');
    dots.forEach((d, i) => d.classList.toggle('active', i === idx));
  };

  toggleBtn.addEventListener('click', async () => {
    if (m.isRunning) {
      m.stop();
      toggleBtn.textContent = 'Off';
      toggleBtn.classList.remove('active');
      pips.querySelectorAll('.metronome-pip.active').forEach(d => d.classList.remove('active'));
    } else {
      await m.start();
      toggleBtn.textContent = 'On';
      toggleBtn.classList.add('active');
    }
  });

  bpmInput.addEventListener('change', () => {
    app.metronomeBpm = Math.max(20, Math.min(300, parseInt(bpmInput.value, 10) || app.metronomeBpm));
    bpmInput.value = String(app.metronomeBpm);
    m.setBpm(app.metronomeBpm);
  });

  beatsSelect.addEventListener('change', () => {
    app.metronomeBeats = parseInt(beatsSelect.value, 10);
    m.setBeats(app.metronomeBeats);
    rebuildPips();
  });

  volSlider.addEventListener('input', () => {
    app.metronomeVolume = parseFloat(volSlider.value);
    m.setVolume(app.metronomeVolume);
  });
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

// ── PSOLA pitch-corrected playback ───────────────────────────────────────────

function wirePsolaControls() {
  const toggleBtn = document.getElementById('psola-toggle-btn');
  const volSlider = document.getElementById('psola-volume-slider');
  if (!toggleBtn) return;

  volSlider.value = String(app.psolaVolume);

  const pushVolume = () => {
    app.engine.setPsolaPlayback(app.psolaEnabled ? app.psolaVolume : 0);
  };

  toggleBtn.addEventListener('click', () => {
    app.psolaEnabled = !app.psolaEnabled;
    toggleBtn.textContent = app.psolaEnabled ? 'On' : 'Off';
    toggleBtn.classList.toggle('active', app.psolaEnabled);
    pushVolume();
  });

  volSlider.addEventListener('input', () => {
    app.psolaVolume = parseFloat(volSlider.value);
    if (app.psolaEnabled) pushVolume();
  });
}

// ── Mic input makeup gain ────────────────────────────────────────────────────

function wireMicGainControl() {
  const slider = document.getElementById('mic-gain-slider');
  if (!slider) return;
  slider.value = String(app.voiceInputGain);
  app.engine.setVoiceInputGain(app.voiceInputGain);
  slider.addEventListener('input', () => {
    app.voiceInputGain = parseFloat(slider.value);
    app.engine.setVoiceInputGain(app.voiceInputGain);
  });
}

// ── Reverb send ──────────────────────────────────────────────────────────────

function wireReverbControl() {
  const slider = document.getElementById('reverb-slider');
  if (!slider) return;
  slider.value = String(app.monitorReverbWet);
  app.engine.setMonitorReverb(app.monitorReverbWet);
  slider.addEventListener('input', () => {
    app.monitorReverbWet = parseFloat(slider.value);
    app.engine.setMonitorReverb(app.monitorReverbWet);
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

// ── Zoom / follow-along ──────────────────────────────────────────────────────

function wireZoomFollowControl() {
  const btn = document.getElementById('zoom-follow-btn');
  if (!btn) return;

  btn.addEventListener('click', () => {
    app.zoomFollow = !app.zoomFollow;
    btn.classList.toggle('active', app.zoomFollow);
    btn.setAttribute('aria-pressed', app.zoomFollow ? 'true' : 'false');
    btn.textContent = app.zoomFollow ? 'Follow On' : 'Follow';
    document.body.classList.toggle('zoom-follow-active', app.zoomFollow);
    app.ladder.setZoomFollow(app.zoomFollow);
    app.singscope?.setZoomMode(app.zoomFollow);
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

  wireReferencePlayerControls();
  wireReferencePlaybackLifecycle();

  document.getElementById('recording-upload-input')?.addEventListener('change', event => {
    const input = event.currentTarget;
    importMediaFiles([...input.files])
      .catch(e => {
        console.error('Media file import failed', e);
        setRecordingStatus('Could not import the selected media.');
      })
      .finally(() => {
        input.value = '';
      });
  });

  document.getElementById('recording-url-form')?.addEventListener('submit', event => {
    event.preventDefault();
    const input = document.getElementById('recording-url-input');
    importMediaUrl(input?.value ?? '').then(imported => {
      if (imported && input) input.value = '';
    });
  });

  renderRecordings();
  updateRecordingControls();
}

function wireReferencePlayerControls() {
  document.getElementById('reference-play-pause-btn')?.addEventListener('click', () => {
    const playback = app.activeRecordingPlayback;
    if (!playback) return;
    if (playback.state === 'playing') pauseReferencePlayback('paused');
    else {
      if (playback.state === 'ended') seekReferencePlayback(0);
      resumeReferencePlayback(playback);
    }
  });

  document.getElementById('reference-stop-btn')?.addEventListener('click', () => {
    stopRecordingPlayback();
  });

  document.getElementById('reference-restart-btn')?.addEventListener('click', () => {
    const playback = app.activeRecordingPlayback;
    if (!playback) return;
    seekReferencePlayback(0);
    resumeReferencePlayback(playback);
  });

  document.getElementById('reference-back-btn')?.addEventListener('click', () => {
    seekReferencePlayback((app.activeRecordingPlayback?.currentTimeMs || 0) - REFERENCE_SEEK_STEP_MS);
  });

  document.getElementById('reference-forward-btn')?.addEventListener('click', () => {
    seekReferencePlayback((app.activeRecordingPlayback?.currentTimeMs || 0) + REFERENCE_SEEK_STEP_MS);
  });

  const seek = document.getElementById('reference-player-seek');
  seek?.addEventListener('input', () => {
    const playback = app.activeRecordingPlayback;
    if (!playback) return;
    playback.userSeeking = true;
    updateReferencePlayerTime(Number(seek.value), playback.durationMs);
  });
  seek?.addEventListener('change', () => {
    const playback = app.activeRecordingPlayback;
    if (!playback) return;
    playback.userSeeking = false;
    seekReferencePlayback(Number(seek.value));
  });

  document.getElementById('reference-speed-select')?.addEventListener('change', event => {
    setReferencePlaybackRate(Number(event.currentTarget.value));
  });

  document.getElementById('reference-pitch-slider')?.addEventListener('input', event => {
    setReferencePitchShift(Number(event.currentTarget.value));
  });

  document.getElementById('reference-pitch-reset-btn')?.addEventListener('click', () => {
    setReferencePitchShift(0);
  });

  document.querySelectorAll('[data-reference-pitch-step]').forEach(button => {
    button.addEventListener('click', () => {
      const step = Number(button.dataset.referencePitchStep);
      setReferencePitchShift(app.referencePitchShiftMoria + step);
    });
  });
}

function wireReferencePlaybackLifecycle() {
  const suspend = () => {
    if (document.visibilityState === 'hidden') {
      suspendReferencePlayback('Page hidden. Playback paused.');
    }
  };
  document.addEventListener('visibilitychange', suspend);
  window.addEventListener('pagehide', () => suspendReferencePlayback('Page hidden. Playback paused.'));
  window.addEventListener('pageshow', () => {
    const playback = app.activeRecordingPlayback;
    if (playback?.state === 'suspended') {
      setRecordingStatus(`Playback paused at ${formatDuration(playback.currentTimeMs)}.`);
      renderReferencePlayer();
    }
  });
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
    sourceKind: 'mic',
    analyzeDuringPlayback: false,
    pitchAnalysisComplete: true,
  };

  app.recordings.unshift(recording);
  setRecordingStatus(`Saved ${formatDuration(durationMs)} recording.`);
  renderRecordings();
  updateRecordingControls();
}

async function importMediaFiles(files) {
  const mediaFiles = files.filter(file => file?.size > 0);
  if (!mediaFiles.length) return false;

  stopRecordingPlayback();
  await app.ensureAudio?.();

  let imported = 0;
  for (const file of mediaFiles) {
    try {
      setRecordingStatus(`Importing ${file.name || 'media'}...`);
      await importMediaBlob(file, {
        name: cleanMediaName(file.name, makeImportedMediaName()),
        mimeType: file.type || '',
        extension: extensionForFileName(file.name, file.type),
        sourceKind: 'upload',
      });
      imported++;
    } catch (e) {
      console.error('Media import failed', e);
      setRecordingStatus(`Could not import ${file.name || 'this media file'}.`);
    }
  }

  if (imported > 0) {
    setRecordingStatus(`Imported ${imported} ${imported === 1 ? 'media file' : 'media files'}.`);
  }
  return imported > 0;
}

async function importMediaUrl(rawUrl) {
  const url = parseMediaUrl(rawUrl);
  if (!url) {
    setRecordingStatus('Enter a valid audio, video, or YouTube URL.');
    return false;
  }
  if (isYouTubeUrl(url)) return importYouTubeUrl(url);

  stopRecordingPlayback();
  await app.ensureAudio?.();
  setRecordingStatus('Fetching media URL...');

  try {
    const response = await fetch(url.href);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const mimeType = response.headers.get('content-type') || '';
    const blob = await response.blob();
    await importMediaBlob(blob, {
      name: cleanMediaName(mediaNameFromUrl(url), makeImportedMediaName()),
      mimeType: mimeType || blob.type || '',
      extension: extensionForFileName(url.pathname, mimeType || blob.type),
      sourceKind: 'url',
      sourceUrl: url.href,
    });
    setRecordingStatus('Imported media URL.');
    return true;
  } catch (e) {
    console.error('Media URL import failed', e);
    setRecordingStatus('Could not fetch that URL. Upload the file instead if the server blocks browser access.');
    return false;
  }
}

async function importYouTubeUrl(url) {
  const metubeBaseUrl = configuredMetubeBaseUrl();
  if (metubeBaseUrl) {
    return importYouTubeViaMetube(url, metubeBaseUrl);
  }

  const proxyEndpoint = configuredMediaProxyEndpoint();
  if (proxyEndpoint) return importYouTubeViaGenericProxy(url, proxyEndpoint);

  setRecordingStatus('YouTube extraction needs MeTube or a media proxy. Upload an audio/video file for now.');
  return false;
}

async function importYouTubeViaMetube(url, metubeBaseUrl) {
  stopRecordingPlayback();
  await app.ensureAudio?.();
  setRecordingStatus('Checking MeTube for an existing MP3...');

  try {
    let item = await findExistingMetubeDownload(metubeBaseUrl, url.href);
    if (item?.status === 'finished' && item.filename) {
      await importMetubeDownloadItem(metubeBaseUrl, url, item);
      setRecordingStatus(`Imported existing MeTube MP3: ${item.title || 'YouTube audio'}.`);
      return true;
    }

    if (item) {
      setRecordingStatus(formatMetubeProgress(item));
    } else {
      setRecordingStatus('Sending YouTube link to MeTube as MP3...');
      await metubeAddMp3Download(metubeBaseUrl, url.href);
    }

    item = await waitForMetubeDownload(metubeBaseUrl, url.href, {
      onProgress: status => setRecordingStatus(status),
    });
    await importMetubeDownloadItem(metubeBaseUrl, url, item);
    setRecordingStatus(`Imported ${item.title || 'YouTube audio'} from MeTube.`);
    return true;
  } catch (e) {
    console.error('MeTube import failed', e);
    setRecordingStatus(metubeUserErrorMessage(e));
    return false;
  }
}

async function importYouTubeViaGenericProxy(url, proxyEndpoint) {
  stopRecordingPlayback();
  await app.ensureAudio?.();
  setRecordingStatus('Extracting YouTube audio...');

  try {
    const requestUrl = new URL(proxyEndpoint, location.href);
    requestUrl.searchParams.set('url', url.href);
    const response = await fetch(requestUrl.href);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      if (payload?.audioUrl) return importMediaUrl(payload.audioUrl);
      throw new Error(payload?.error || 'YouTube proxy did not return audio');
    }

    const blob = await response.blob();
    await importMediaBlob(blob, {
      name: cleanMediaName(filenameFromContentDisposition(response) || mediaNameFromUrl(url), makeImportedMediaName()),
      mimeType: contentType || blob.type || '',
      extension: extensionForFileName(filenameFromContentDisposition(response) || '', contentType || blob.type),
      sourceKind: 'youtube',
      sourceUrl: url.href,
    });
    setRecordingStatus('Imported YouTube audio.');
    return true;
  } catch (e) {
    console.error('YouTube import failed', e);
    setRecordingStatus('Could not extract audio from that YouTube link.');
    return false;
  }
}

async function findExistingMetubeDownload(baseUrl, youtubeUrl) {
  const history = await fetchMetubeHistory(baseUrl);
  const item = findMetubeDownload(history, youtubeUrl, youtubeVideoId(youtubeUrl));
  return metubeItemRank(item) >= 2 ? item : null;
}

async function importMetubeDownloadItem(baseUrl, url, item) {
  const blob = await fetchMetubeDownloadBlob(baseUrl, item);
  await importMediaBlob(blob, {
    name: cleanMediaName(item.title || item.filename || mediaNameFromUrl(url), makeImportedMediaName()),
    mimeType: blob.type || 'audio/mpeg',
    extension: extensionForFileName(item.filename || '', blob.type || 'audio/mpeg'),
    sourceKind: 'youtube',
    sourceUrl: url.href,
  });
}

async function metubeAddMp3Download(baseUrl, youtubeUrl) {
  const response = await fetch(metubeApiUrl(baseUrl, 'add'), {
    method: 'POST',
    body: JSON.stringify({
      url: youtubeUrl,
      quality: '192',
      format: 'mp3',
      folder: null,
      custom_name_prefix: null,
      playlist_strict_mode: true,
      playlist_item_limit: 1,
      auto_start: true,
    }),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`metube_add_http_${response.status}${text ? `: ${text}` : ''}`);
  }
  const payload = await response.json().catch(() => null);
  if (payload?.status && payload.status !== 'ok') {
    throw new Error(payload.msg || 'metube_add_failed');
  }
}

async function waitForMetubeDownload(baseUrl, youtubeUrl, { onProgress } = {}) {
  const startedAt = performance.now();
  const targetVideoId = youtubeVideoId(youtubeUrl);
  let lastProgress = '';

  while (performance.now() - startedAt < METUBE_TIMEOUT_MS) {
    const history = await fetchMetubeHistory(baseUrl);
    const item = findMetubeDownload(history, youtubeUrl, targetVideoId);
    if (item) {
      if (item.status === 'finished' && item.filename) return item;
      if (item.status === 'error' || item.status === 'failed' || item.error) {
        throw new Error(item.error || item.msg || 'metube_download_failed');
      }
      const progress = formatMetubeProgress(item);
      if (progress && progress !== lastProgress) {
        lastProgress = progress;
        onProgress?.(progress);
      }
    } else if (lastProgress !== 'Waiting for MeTube to start...') {
      lastProgress = 'Waiting for MeTube to start...';
      onProgress?.(lastProgress);
    }

    await delay(METUBE_POLL_INTERVAL_MS);
  }

  throw new Error('metube_timeout');
}

async function fetchMetubeHistory(baseUrl) {
  const response = await fetch(metubeApiUrl(baseUrl, 'history'));
  if (!response.ok) throw new Error(`metube_history_http_${response.status}`);
  return response.json();
}

function findMetubeDownload(history, youtubeUrl, targetVideoId) {
  const items = [
    ...(history?.queue || []),
    ...(history?.pending || []),
    ...(history?.done || []),
  ];
  return items
    .filter(item => isMatchingMetubeDownload(item, youtubeUrl, targetVideoId))
    .sort((a, b) => {
      const rankDiff = metubeItemRank(b) - metubeItemRank(a);
      if (rankDiff !== 0) return rankDiff;
      return Number(b.timestamp || 0) - Number(a.timestamp || 0);
    })[0] || null;
}

function isMatchingMetubeDownload(item, youtubeUrl, targetVideoId) {
  if (!item) return false;
  const itemVideoId = youtubeVideoId(item.url || '') || item.id;
  const sameSource = targetVideoId
    ? itemVideoId === targetVideoId
    : String(item.url || '') === youtubeUrl;
  if (!sameSource) return false;

  const format = String(item.format || '').toLowerCase();
  const filename = String(item.filename || '').toLowerCase();
  const quality = String(item.quality || '').toLowerCase();
  return format === 'mp3' || filename.endsWith('.mp3') || quality === 'audio';
}

function metubeItemRank(item) {
  if (!item) return 0;
  if (item.status === 'finished' && item.filename) return 3;
  if (item.status === 'error' || item.status === 'failed' || item.error) return 1;
  return 2;
}

function formatMetubeProgress(item) {
  const title = item.title || 'YouTube audio';
  if (Number.isFinite(item.percent)) {
    return `MeTube downloading ${title}: ${Math.round(item.percent)}%`;
  }
  if (item.status === 'preparing') return `MeTube preparing ${title}...`;
  if (item.status === 'pending') return `MeTube queued ${title}...`;
  return `MeTube downloading ${title}...`;
}

async function fetchMetubeDownloadBlob(baseUrl, item) {
  const urls = [
    metubeDownloadUrl(baseUrl, 'audio_download', item),
    metubeDownloadUrl(baseUrl, 'download', item),
  ];
  let lastError = null;

  for (const url of urls) {
    try {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`metube_file_http_${response.status}`);
      return await response.blob();
    } catch (e) {
      lastError = e;
    }
  }

  throw lastError || new Error('metube_file_unavailable');
}

function metubeApiUrl(baseUrl, path) {
  return new URL(path.replace(/^\/+/, ''), ensureTrailingSlash(baseUrl)).href;
}

function metubeDownloadUrl(baseUrl, prefix, item) {
  const parts = [prefix];
  if (item.folder) parts.push(...String(item.folder).split('/').filter(Boolean));
  parts.push(...String(item.filename || '').split('/').filter(Boolean));
  const encodedPath = parts.map(part => encodeURIComponent(part)).join('/');
  return new URL(encodedPath, ensureTrailingSlash(baseUrl)).href;
}

function ensureTrailingSlash(value) {
  return String(value || '').endsWith('/') ? String(value) : `${value}/`;
}

function youtubeVideoId(rawUrl) {
  try {
    const url = new URL(rawUrl);
    const host = url.hostname.toLowerCase().replace(/^www\./, '');
    if (host === 'youtu.be') return url.pathname.replace(/^\/+/, '').split('/')[0] || '';
    if (host === 'youtube.com' || host.endsWith('.youtube.com')) {
      if (url.pathname.startsWith('/shorts/')) return url.pathname.split('/')[2] || '';
      if (url.pathname.startsWith('/embed/')) return url.pathname.split('/')[2] || '';
      return url.searchParams.get('v') || '';
    }
  } catch {}
  return '';
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function importMediaBlob(blob, options = {}) {
  const mimeType = options.mimeType || blob.type || '';
  const sourceBlob = mimeType && blob.type !== mimeType
    ? new Blob([blob], { type: mimeType })
    : blob;
  const url = URL.createObjectURL(sourceBlob);
  let durationMs = 0;
  try {
    durationMs = await readMediaDurationMs(url);
  } catch (e) {
    console.warn('Could not read imported media duration', e);
  }

  const id = `media-${Date.now()}-${app.recordingCounter++}`;
  const recording = {
    id,
    name: cleanMediaName(options.name, makeImportedMediaName()),
    blob: sourceBlob,
    url,
    mimeType,
    extension: options.extension || extensionForFileName(options.name, mimeType),
    normalized: false,
    gain: 1,
    durationMs,
    pitchEvents: [],
    createdAt: new Date(),
    sourceKind: options.sourceKind || 'upload',
    sourceUrl: options.sourceUrl || null,
    analyzeDuringPlayback: true,
    pitchAnalysisComplete: false,
  };

  app.recordings.unshift(recording);
  renderRecordings();
  updateRecordingControls();
  return recording;
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

function compactPitchMessage(msg) {
  return {
    type: 'pitch',
    detected_hz: Number.isFinite(msg.detected_hz) ? msg.detected_hz : null,
    raw_moria: Number.isFinite(msg.raw_moria) ? msg.raw_moria : null,
    snap_moria: Number.isFinite(msg.snap_moria) ? msg.snap_moria : null,
    cell_id: isValidCellId(msg.cell_id) ? msg.cell_id : -1,
    neighbor_id: isValidCellId(msg.neighbor_id) ? msg.neighbor_id : -1,
    neighbor_moria: Number.isFinite(msg.neighbor_moria) ? msg.neighbor_moria : null,
    neighbor_vel: Number.isFinite(msg.neighbor_vel) ? msg.neighbor_vel : 0,
    confidence: Number.isFinite(msg.confidence) ? msg.confidence : 0,
    gate_open: Boolean(msg.gate_open),
  };
}

function recordPitchForActiveTake(msg) {
  if (app.recorder?.state !== 'recording') return;
  app.recordingPitchEvents.push({
    t: Math.max(0, performance.now() - app.recordingStartedAt),
    msg: compactPitchMessage(msg),
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
    const active = app.activeRecordingPlayback?.id === recording.id
      ? app.activeRecordingPlayback
      : null;
    const row = document.createElement('div');
    row.className = 'recording-item';
    if (active) row.classList.add('active');

    const meta = document.createElement('div');
    meta.className = 'recording-meta';
    const name = document.createElement('span');
    name.className = 'recording-name';
    name.textContent = recording.name;
    const details = document.createElement('span');
    details.className = 'recording-details';
    details.textContent = recordingDetails(recording);
    meta.appendChild(name);
    meta.appendChild(details);

    const actions = document.createElement('div');
    actions.className = 'recording-item-actions';

    const playBtn = document.createElement('button');
    playBtn.type = 'button';
    playBtn.textContent = active?.state === 'playing' ? 'Pause' : 'Play';
    playBtn.disabled = active?.state === 'loading';
    playBtn.addEventListener('click', () => {
      playRecording(recording);
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

  const active = app.activeRecordingPlayback;
  if (active?.id === recording.id) {
    if (active.state === 'playing') pauseReferencePlayback('paused');
    else {
      if (active.state === 'ended') seekReferencePlayback(0);
      resumeReferencePlayback(active);
    }
    return;
  }

  stopRecordingPlayback({ silent: true });
  app.singscope?.clear('reference');
  showSingView();
  await app.ensureAudio?.();

  const analyzing = shouldAnalyzeRecordingPlayback(recording);
  if (!analyzing) await ensureRecordingNormalized(recording);
  if (analyzing) {
    recording.pitchEvents = [];
    recording.pitchAnalysisComplete = false;
    renderRecordings();
  }

  const playback = {
    id: recording.id,
    recording,
    audio: null,
    rafId: null,
    graph: null,
    state: 'idle',
    idx: 0,
    referenceLastCellId: null,
    analysisLastCellId: null,
    currentTimeMs: 0,
    durationMs: recording.durationMs || 0,
    playbackRate: app.referencePlaybackRate,
    pitchShiftMoria: app.referencePitchShiftMoria,
    analyzing,
    userSeeking: false,
    handlers: null,
    resumeToken: null,
  };

  app.activeRecordingPlayback = playback;
  prepareReferencePlaybackCursor(playback);
  app.singscope?.setReferencePlayheadMs(0);
  renderRecordings();
  updateRecordingControls();

  await resumeReferencePlayback(playback);
}

async function resumeReferencePlayback(playback = app.activeRecordingPlayback) {
  if (!playback) return;
  const resumeToken = Symbol('reference-resume');
  playback.resumeToken = resumeToken;
  try {
    playback.state = 'loading';
    renderReferencePlayer();
    await app.ensureAudio?.();
    await ensureReferencePlaybackResources(playback);
    if (
      app.activeRecordingPlayback !== playback ||
      playback.resumeToken !== resumeToken ||
      playback.state !== 'loading'
    ) {
      teardownReferencePlaybackResources(playback);
      return;
    }
    setAudioPreservesPitch(playback.audio);
    playback.audio.playbackRate = playback.playbackRate;
    playback.audio.currentTime = Math.max(0, playback.currentTimeMs / 1000);
    await playback.audio.play();
  } catch (e) {
    console.error('Recording playback failed', e);
    if (app.activeRecordingPlayback !== playback) return;
    playback.state = 'error';
    setRecordingStatus('Could not play this recording.');
    renderReferencePlayer();
  }
}

async function ensureReferencePlaybackResources(playback) {
  if (playback.audio) return;

  const audio = new Audio(playback.recording.url);
  audio.preload = 'auto';
  setAudioPreservesPitch(audio);
  audio.playbackRate = playback.playbackRate;

  const handlers = {
    play: () => {
      playback.state = 'playing';
      setRecordingStatus(`Playing ${playback.recording.name}.`);
      startReferencePlaybackTick(playback);
      renderRecordings();
      updateRecordingControls();
    },
    pause: () => {
      if (audio.ended || playback.state === 'suspended') return;
      if (playback.state === 'playing' || playback.state === 'loading') {
        playback.state = 'paused';
        playback.currentTimeMs = audio.currentTime * 1000;
        stopReferencePlaybackTick(playback);
        setRecordingStatus(`Paused at ${formatDuration(playback.currentTimeMs)}.`);
        renderRecordings();
        updateRecordingControls();
      }
    },
    ended: () => finishReferencePlayback(playback),
    loadedmetadata: () => {
      playback.durationMs = Number.isFinite(audio.duration)
        ? audio.duration * 1000
        : playback.recording.durationMs || playback.durationMs;
      renderReferencePlayer();
    },
  };

  audio.addEventListener('play', handlers.play);
  audio.addEventListener('pause', handlers.pause);
  audio.addEventListener('ended', handlers.ended);
  audio.addEventListener('loadedmetadata', handlers.loadedmetadata);

  playback.audio = audio;
  playback.handlers = handlers;
  playback.graph = await createStereoPlaybackGraph(audio, {
    onPitch: playback.analyzing ? rawMsg => captureReferencePitch(playback, rawMsg) : null,
    pitchShiftMoria: playback.pitchShiftMoria,
  });
}

function captureReferencePitch(playback, rawMsg) {
  if (rawMsg.type !== 'pitch' || app.activeRecordingPlayback !== playback) return;
  const base = normalizePitchMessage(rawMsg, playback.analysisLastCellId);
  playback.analysisLastCellId = base.lastCellId;
  const pitchEvent = {
    t: Math.max(0, playback.audio.currentTime * 1000),
    msg: compactPitchMessage(base.msg),
  };
  playback.recording.pitchEvents.push(pitchEvent);
  displayReferencePitchEvent(playback, pitchEvent);
}

function startReferencePlaybackTick(playback) {
  stopReferencePlaybackTick(playback);
  const tick = () => {
    if (app.activeRecordingPlayback !== playback || playback.state !== 'playing') return;
    playback.currentTimeMs = (playback.audio?.currentTime || 0) * 1000;
    playback.durationMs = Number.isFinite(playback.audio?.duration)
      ? playback.audio.duration * 1000
      : playback.durationMs;
    app.singscope?.setReferencePlayheadMs(playback.currentTimeMs);
    pushDueReferencePitchEvents(playback);
    renderReferencePlayer();
    playback.rafId = requestAnimationFrame(tick);
  };
  playback.rafId = requestAnimationFrame(tick);
}

function stopReferencePlaybackTick(playback) {
  if (playback?.rafId !== null && playback?.rafId !== undefined) {
    cancelAnimationFrame(playback.rafId);
    playback.rafId = null;
  }
}

function pushDueReferencePitchEvents(playback) {
  if (playback.analyzing) return;
  const events = playback.recording.pitchEvents || [];
  while (playback.idx < events.length && events[playback.idx].t <= playback.currentTimeMs) {
    displayReferencePitchEvent(playback, events[playback.idx]);
    playback.idx++;
  }
}

function displayReferencePitchEvent(playback, event) {
  const display = normalizePitchMessage(event.msg, playback.referenceLastCellId, {
    pitchShiftMoria: playback.pitchShiftMoria,
  });
  playback.referenceLastCellId = display.lastCellId;
  app.singscope?.pushReferencePitch(display.msg, { atMs: event.t });
}

function prepareReferencePlaybackCursor(playback) {
  const events = playback.recording.pitchEvents || [];
  playback.idx = lowerBoundPitchEvent(events, playback.currentTimeMs);
  playback.referenceLastCellId = null;
}

function lowerBoundPitchEvent(events, timeMs) {
  let lo = 0;
  let hi = events.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if ((events[mid]?.t ?? 0) < timeMs) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function finishReferencePlayback(playback) {
  if (app.activeRecordingPlayback !== playback) return;
  stopReferencePlaybackTick(playback);
  playback.state = 'ended';
  playback.currentTimeMs = playback.durationMs || playback.currentTimeMs;
  playback.analyzing = false;
  if (playback.recording.pitchEvents.length) {
    playback.recording.pitchEvents.sort((a, b) => (a.t || 0) - (b.t || 0));
    playback.recording.analyzeDuringPlayback = false;
    playback.recording.pitchAnalysisComplete = true;
  }
  app.singscope?.setReferencePlayheadMs(playback.currentTimeMs);
  setRecordingStatus(playback.recording.pitchEvents.length
    ? `Playback finished. Captured ${playback.recording.pitchEvents.length} reference points.`
    : 'Playback finished.');
  renderRecordings();
  updateRecordingControls();
}

function pauseReferencePlayback(state = 'paused') {
  const playback = app.activeRecordingPlayback;
  if (!playback) return;
  playback.state = state;
  playback.currentTimeMs = Number.isFinite(playback.audio?.currentTime)
    ? playback.audio.currentTime * 1000
    : playback.currentTimeMs;
  stopReferencePlaybackTick(playback);
  playback.audio?.pause();
  app.singscope?.setReferencePlayheadMs(playback.currentTimeMs);
  setRecordingStatus(state === 'suspended'
    ? `Playback paused at ${formatDuration(playback.currentTimeMs)}.`
    : `Paused at ${formatDuration(playback.currentTimeMs)}.`);
  renderRecordings();
  updateRecordingControls();
}

function suspendReferencePlayback(message) {
  const playback = app.activeRecordingPlayback;
  if (!playback || !['playing', 'loading', 'paused'].includes(playback.state)) return;
  pauseReferencePlayback('suspended');
  teardownReferencePlaybackResources(playback);
  if (message) setRecordingStatus(message);
  renderReferencePlayer();
}

function teardownReferencePlaybackResources(playback) {
  if (!playback) return;
  stopReferencePlaybackTick(playback);

  if (playback.audio && playback.handlers) {
    playback.audio.removeEventListener('play', playback.handlers.play);
    playback.audio.removeEventListener('pause', playback.handlers.pause);
    playback.audio.removeEventListener('ended', playback.handlers.ended);
    playback.audio.removeEventListener('loadedmetadata', playback.handlers.loadedmetadata);
  }

  if (playback.audio) {
    try { playback.audio.pause(); } catch {}
    try { playback.audio.removeAttribute('src'); } catch {}
    try { playback.audio.load(); } catch {}
  }

  playback.graph?.cleanup?.();
  playback.graph = null;
  playback.audio = null;
  playback.handlers = null;
}

function seekReferencePlayback(timeMs) {
  const playback = app.activeRecordingPlayback;
  if (!playback) return;

  const durationMs = playback.durationMs || playback.recording.durationMs || 0;
  const clampedMs = Math.max(0, durationMs ? Math.min(timeMs, durationMs) : timeMs);
  playback.currentTimeMs = clampedMs;
  playback.state = playback.state === 'ended' ? 'paused' : playback.state;

  if (playback.audio) {
    playback.audio.currentTime = clampedMs / 1000;
  }

  if (playback.analyzing) {
    playback.recording.pitchEvents = [];
    playback.recording.pitchAnalysisComplete = false;
    playback.analysisLastCellId = null;
    renderRecordings();
  }
  rebuildReferenceTrace(playback);
  setRecordingStatus(`Playback position ${formatDuration(playback.currentTimeMs)}.`);
  renderReferencePlayer();
}

function rebuildReferenceTrace(playback) {
  app.singscope?.clear('reference');
  app.singscope?.setReferencePlayheadMs(playback.currentTimeMs);
  playback.referenceLastCellId = null;

  const events = playback.recording.pitchEvents || [];
  const startMs = Math.max(0, playback.currentTimeMs - REFERENCE_TRACE_PREFILL_MS);
  let idx = lowerBoundPitchEvent(events, startMs);
  while (idx < events.length && events[idx].t <= playback.currentTimeMs) {
    displayReferencePitchEvent(playback, events[idx]);
    idx++;
  }
  playback.idx = idx;
}

function setReferencePlaybackRate(rate) {
  const nextRate = Number.isFinite(rate)
    ? Math.max(0.25, Math.min(2, rate))
    : 1;
  app.referencePlaybackRate = nextRate;
  const playback = app.activeRecordingPlayback;
  if (playback) {
    playback.playbackRate = nextRate;
    if (playback.audio) {
      setAudioPreservesPitch(playback.audio);
      playback.audio.playbackRate = nextRate;
    }
  }
  renderReferencePlayer();
}

function setReferencePitchShift(moria) {
  const nextMoria = Number.isFinite(moria)
    ? Math.max(REFERENCE_PITCH_MIN_MORIA, Math.min(REFERENCE_PITCH_MAX_MORIA, Math.round(moria)))
    : 0;
  app.referencePitchShiftMoria = nextMoria;
  const playback = app.activeRecordingPlayback;
  if (playback) {
    playback.pitchShiftMoria = nextMoria;
    playback.graph?.setPitchShift?.(nextMoria);
    rebuildReferenceTrace(playback);
  }
  renderReferencePlayer();
}

function setAudioPreservesPitch(audio) {
  if (!audio) return;
  audio.preservesPitch = true;
  audio.mozPreservesPitch = true;
  audio.webkitPreservesPitch = true;
}

function renderReferencePlayer() {
  const player = document.getElementById('reference-player');
  if (!player) return;
  const playback = app.activeRecordingPlayback;
  player.classList.toggle('hidden', !playback);

  const title = document.getElementById('reference-player-title');
  if (title) title.textContent = playback?.recording?.name || 'Reference';

  const durationMs = playback?.durationMs || playback?.recording?.durationMs || 0;
  const currentMs = playback?.currentTimeMs || 0;
  updateReferencePlayerTime(currentMs, durationMs);

  const seek = document.getElementById('reference-player-seek');
  if (seek && playback) {
    seek.max = String(Math.max(1, Math.round(durationMs)));
    if (!playback.userSeeking) seek.value = String(Math.round(currentMs));
    seek.disabled = durationMs <= 0;
  } else if (seek) {
    seek.value = '0';
    seek.disabled = true;
  }

  const playPause = document.getElementById('reference-play-pause-btn');
  if (playPause) {
    playPause.disabled = !playback || playback.state === 'loading';
    playPause.textContent = playback?.state === 'playing' ? 'Pause' : 'Play';
  }

  const stop = document.getElementById('reference-stop-btn');
  if (stop) stop.disabled = !playback;
  const restart = document.getElementById('reference-restart-btn');
  if (restart) restart.disabled = !playback;
  const back = document.getElementById('reference-back-btn');
  if (back) back.disabled = !playback;
  const forward = document.getElementById('reference-forward-btn');
  if (forward) forward.disabled = !playback;

  const speed = document.getElementById('reference-speed-select');
  if (speed) speed.value = String(playback?.playbackRate ?? app.referencePlaybackRate);

  const pitchSlider = document.getElementById('reference-pitch-slider');
  if (pitchSlider) pitchSlider.value = String(playback?.pitchShiftMoria ?? app.referencePitchShiftMoria);
  const pitchReadout = document.getElementById('reference-pitch-readout');
  if (pitchReadout) pitchReadout.textContent = formatPitchShift(playback?.pitchShiftMoria ?? app.referencePitchShiftMoria);
}

function updateReferencePlayerTime(currentMs = 0, durationMs = 0) {
  const time = document.getElementById('reference-player-time');
  if (time) {
    time.textContent = `${formatDuration(currentMs)} / ${formatDuration(durationMs)}`;
  }
}

function formatPitchShift(moria) {
  const value = Number.isFinite(moria) ? Math.round(moria) : 0;
  if (value === 0) return '0m';
  return `${value > 0 ? '+' : ''}${value}m`;
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

async function createStereoPlaybackGraph(audio, options = {}) {
  const ctx = app.engine?.audioContext;
  if (!ctx) return null;

  let source = null;
  let pitchNode = null;
  let analyzer = null;
  let routedDirect = false;
  try {
    source = ctx.createMediaElementSource(audio);
  } catch (e) {
    console.warn('Stereo recording playback routing unavailable; using direct element output.', e);
    return null;
  }

  try {
    pitchNode = await app.engine.createPitchShiftNode({
      pitchShiftMoria: Number.isFinite(options.pitchShiftMoria) ? options.pitchShiftMoria : 0,
    });
    source.connect(pitchNode);
    pitchNode.connect(ctx.destination);
  } catch (e) {
    console.warn('Reference pitch shifter unavailable; using direct media output.', e);
    try {
      source.connect(ctx.destination);
      routedDirect = true;
    } catch (routeError) {
      console.warn('Recording playback routing unavailable.', routeError);
    }
  }

  if (options.onPitch) {
    try {
      analyzer = await app.engine.createMediaPitchAnalyzer(options.onPitch);
      source.connect(analyzer.input);
    } catch (e) {
      console.warn('Media pitch analysis unavailable; playing without reference analysis.', e);
      setRecordingStatus('Playing without pitch analysis for this file.');
    }
  }

  return {
    setPitchShift: moria => {
      pitchNode?.port?.postMessage?.({ type: 'pitch_shift', moria });
    },
    cleanup: () => {
      analyzer?.cleanup?.();
      try { pitchNode?.disconnect(); } catch {}
      try { source.disconnect(); } catch {}
      if (routedDirect) {
        try { source.disconnect(ctx.destination); } catch {}
      }
    },
  };
}

function stopRecordingPlayback(options = {}) {
  const playback = app.activeRecordingPlayback;
  if (!playback) return;
  playback.state = 'stopped';
  teardownReferencePlaybackResources(playback);
  app.activeRecordingPlayback = null;
  app.singscope?.clear('reference');
  app.singscope?.setReferencePlayheadMs(null);
  if (!options.silent) setRecordingStatus('Playback stopped.');
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
  renderReferencePlayer();
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
  mimeType = String(mimeType || '').toLowerCase();
  if (mimeType.includes('mpeg') || mimeType.includes('mp3')) return 'mp3';
  if (mimeType.includes('mp4')) return 'm4a';
  if (mimeType.includes('x-m4a')) return 'm4a';
  if (mimeType.includes('aac')) return 'aac';
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('wav')) return 'wav';
  if (mimeType.includes('flac')) return 'flac';
  return 'webm';
}

function extensionForFileName(name, mimeType) {
  const match = String(name || '').match(/\.([A-Za-z0-9]{1,8})(?:[?#].*)?$/);
  return match ? match[1].toLowerCase() : extensionForMimeType(mimeType);
}

function recordingDetails(recording) {
  const source = recording.sourceKind === 'mic'
    ? (recording.normalized ? 'normalized' : recording.extension)
    : recordingSourceLabel(recording);
  let pitchLabel = `${recording.pitchEvents.length} pitch points`;
  if (recording.pitchAnalysisComplete && recording.sourceKind !== 'mic') {
    pitchLabel = `${recording.pitchEvents.length} reference points`;
  } else if (recording.analyzeDuringPlayback) {
    pitchLabel = recording.pitchEvents.length
      ? `${recording.pitchEvents.length} partial points`
      : 'analyzes on play';
  }
  return [
    formatDuration(recording.durationMs),
    source,
    pitchLabel,
  ].join(' · ');
}

function recordingSourceLabel(recording) {
  if (recording.sourceKind === 'youtube') return 'youtube';
  if (recording.sourceKind === 'url') return 'url';
  return recording.extension ? `imported ${recording.extension}` : 'imported';
}

function shouldAnalyzeRecordingPlayback(recording) {
  return Boolean(recording.analyzeDuringPlayback && !recording.pitchAnalysisComplete);
}

function parseMediaUrl(rawUrl) {
  const value = String(rawUrl || '').trim();
  if (!value) return null;
  try {
    return new URL(value, location.href);
  } catch {
    return null;
  }
}

function isYouTubeUrl(url) {
  const host = url.hostname.toLowerCase().replace(/^www\./, '');
  return host === 'youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com');
}

function configuredMetubeBaseUrl() {
  const globalEndpoint = globalThis.CHANTERLAB_METUBE_URL;
  const configured = typeof globalEndpoint === 'string' && globalEndpoint.trim()
    ? globalEndpoint.trim()
    : new URLSearchParams(location.search).get(METUBE_QUERY_PARAM);
  return configured || DEFAULT_METUBE_BASE_URL;
}

function configuredMediaProxyEndpoint() {
  const globalEndpoint = globalThis.CHANTERLAB_MEDIA_PROXY_URL;
  if (typeof globalEndpoint === 'string' && globalEndpoint.trim()) {
    return globalEndpoint.trim();
  }
  return new URLSearchParams(location.search).get(MEDIA_PROXY_QUERY_PARAM) || '';
}

function metubeUserErrorMessage(error) {
  const message = String(error?.message || error || '');
  if (message === 'metube_timeout') {
    return 'MeTube did not finish the MP3 within 10 minutes.';
  }
  if (message.includes('Failed to fetch') || message.includes('NetworkError')) {
    return 'Could not reach MeTube from the browser. Enable MeTube CORS for this ChanterLab origin.';
  }
  if (message.startsWith('metube_file_http_')) {
    return 'MeTube finished the MP3, but the audio file could not be fetched.';
  }
  if (message.startsWith('metube_add_http_') || message.startsWith('metube_history_http_')) {
    return 'MeTube rejected the browser request. Check MeTube CORS and reverse-proxy access.';
  }
  return `MeTube import failed: ${message}`;
}

function filenameFromContentDisposition(response) {
  const header = response.headers.get('content-disposition') || '';
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    try {
      return decodeURIComponent(utf8Match[1].trim());
    } catch {}
  }
  const asciiMatch = header.match(/filename="?([^";]+)"?/i);
  return asciiMatch ? asciiMatch[1].trim() : '';
}

function mediaNameFromUrl(url) {
  if (isYouTubeUrl(url)) {
    const id = url.hostname.toLowerCase().includes('youtu.be')
      ? url.pathname.replace(/^\/+/, '')
      : url.searchParams.get('v');
    return id ? `youtube-${id}` : 'youtube-audio';
  }
  const last = decodeURIComponent(url.pathname.split('/').filter(Boolean).pop() || '');
  return last || url.hostname;
}

function cleanMediaName(name, fallback) {
  const value = String(name || '')
    .replace(/\.[A-Za-z0-9]{1,8}$/, '')
    .replace(/[\\/:*?"<>|]+/g, '-')
    .trim();
  return (value || fallback || makeImportedMediaName()).slice(0, 96);
}

function makeImportedMediaName() {
  const stamp = new Date().toISOString()
    .replace(/\.\d+Z$/, '')
    .replace(/[:-]/g, '')
    .replace('T', '-');
  return `media-${stamp}`;
}

function readMediaDurationMs(url) {
  return new Promise((resolve, reject) => {
    const audio = new Audio();
    let settled = false;
    const timeoutId = setTimeout(() => finish(0), 5000);
    const finish = value => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      audio.removeAttribute('src');
      audio.load();
      resolve(value);
    };
    const fail = error => {
      if (settled) return;
      settled = true;
      clearTimeout(timeoutId);
      reject(error);
    };
    audio.preload = 'metadata';
    audio.addEventListener('loadedmetadata', () => {
      const durationMs = Number.isFinite(audio.duration) ? audio.duration * 1000 : 0;
      finish(durationMs);
    }, { once: true });
    audio.addEventListener('error', () => fail(new Error('metadata load failed')), { once: true });
    audio.src = url;
  });
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
