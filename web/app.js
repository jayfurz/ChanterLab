import init, { JsTuningGrid } from './pkg/chanterlab_core.js';
import { ScaleLadder    } from './ui/scale_ladder.js';
import { AudioEngine    } from './audio/audio_engine.js';
import { VKeyboard      } from './ui/vkeyboard.js';
import { Singscope      } from './ui/singscope.js';
import { NoteIndicator  } from './ui/note_indicator.js?v=0.1.0-alpha.3';
import { ExerciseMode   } from './ui/exercise_mode.js?v=0.1.0-alpha.3';
import { PthoraPalette, buildQuickPthoraControls } from './ui/pthora_palette.js';
import { ShadingPalette, buildQuickShadingControls } from './ui/shading_palette.js';

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
const APP_VERSION = '0.1.0-alpha.3';
const HELP_RELEASE_ID = APP_VERSION;

const app = {
  grid:            null,
  ladder:          null,
  singscope:       null,
  noteIndicator:   null,
  exercise:        null,
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
  wireMobileTabs();
  syncAppVersionText();
  wireHelpDialog();
  wireAudioInit();

  gridChanged();
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

  const snap = (msg.gate_open && msg.raw_moria !== null)
    ? nearestEnabledMoriaCell(msg.raw_moria, app.voiceLastCellId)
    : null;
  if (snap) {
    msg.cell_id = snap.primary;
    msg.neighbor_id = snap.neighbor?.cell_id ?? -1;
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

  if (!msg.gate_open || !isValidCellId(msg.cell_id)) {
    app.ladder.setDetectedCell(null, null, 0);
    app.noteIndicator?.clear();
  } else {
    app.ladder.setDetectedCell(
      msg.cell_id,
      isValidCellId(msg.neighbor_id) ? msg.neighbor_id : null,
      msg.neighbor_vel,
    );
    app.noteIndicator?.showPitch(msg);
  }
  if (app.singscope) app.singscope.pushPitch(msg);
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
        ? { cell_id: below.cell_id, vel: total > 0 ? a3 / total : 0.5 }
        : { cell_id: above.cell_id, vel: total > 0 ? a2 / total : 0.5 };
    } else {
      neighbor = { cell_id: (below ?? above).cell_id, vel: 0.5 };
    }
  }

  return { primary: primary.cell_id, neighbor };
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

function syncReferenceControls() {
  const slider = document.getElementById('ni-hz-slider');
  if (slider) slider.value = app.refNiHz.toFixed(2);
  updateReferenceNiDisplay(app.refNiHz);
}

function wireControls() {
  const slider    = document.getElementById('ni-hz-slider');

  syncReferenceControls();
  slider.addEventListener('input', () => {
    setReferenceNiHz(parseFloat(slider.value));
  });

  document.getElementById('ni-snap-up-btn').addEventListener('click', () => {
    setReferenceNiHz(midiToHz(nextMidiFromHz(app.refNiHz, 1)));
  });
  document.getElementById('ni-snap-down-btn').addEventListener('click', () => {
    setReferenceNiHz(midiToHz(nextMidiFromHz(app.refNiHz, -1)));
  });

  document.getElementById('reset-btn').addEventListener('click', () => {
    app.grid = new JsTuningGrid();
    app.grid.refNiHz = app.refNiHz;
    app.activePresetIdx = 0;
    document.querySelectorAll('.preset-btn').forEach((b, i) => {
      b.classList.toggle('active', i === 0);
    });
    gridChanged();
  });
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
    drop = {
      type: 'pthora',
      genus: payload.genus,
      degree: payload.degree,
      dropMoria: cell.moria,
      dropDegree: cell.degree,
    };
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
}

function updateIsonVoice(cells) {
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
