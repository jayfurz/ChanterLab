import init, { JsTuningGrid } from './pkg/byzorgan_core.js';
import { ScaleLadder    } from './ui/scale_ladder.js';
import { AudioEngine    } from './audio/audio_engine.js';
import { VKeyboard      } from './ui/vkeyboard.js';
import { Singscope      } from './ui/singscope.js';
import { PthoraPalette  } from './ui/pthora_palette.js';
import { ShadingPalette } from './ui/shading_palette.js';

// ── App state ────────────────────────────────────────────────────────────────

const PRESETS = [
  { label: 'Diatonic',      genus: 'Diatonic',      degree: 'Ni'  },
  { label: 'Hard Chromatic',genus: 'HardChromatic',  degree: 'Pa'  },
  { label: 'Soft Chromatic',genus: 'SoftChromatic',  degree: 'Ni'  },
  { label: 'Grave Diatonic',genus: 'GraveDiatonic',  degree: 'Ga'  },
  { label: 'Enharmonic Zo', genus: 'EnharmonicZo',   degree: 'Zo'  },
  { label: 'Enharmonic Ga', genus: 'EnharmonicGa',   degree: 'Ga'  },
];

const app = {
  grid:           null,
  ladder:         null,
  singscope:      null,
  engine:         null,
  keyboard:       null,
  activePresetIdx: 0,
  // Ison state
  isonEnabled:    false,
  isonDegree:     'Ni',
  isonOctave:     0,
  isonVolume:     0.5,
  // Mic / PSOLA correction state. Off by default — chanters should hear
  // their own voice first and opt in to correction as a training aid.
  correctionEnabled: false,
  correctionVolume:  0.5,
};

// ── Boot ─────────────────────────────────────────────────────────────────────

async function main() {
  await init();

  app.grid   = new JsTuningGrid();
  app.engine = new AudioEngine();

  const canvas  = document.getElementById('scale-ladder');
  app.ladder    = new ScaleLadder(canvas, app);
  app.keyboard  = new VKeyboard(app.engine, app.ladder);

  const singCanvas  = document.getElementById('singscope');
  app.singscope     = new Singscope(singCanvas);
  app.singscope.start();

  buildPresetButtons();
  wireControls();
  wirePalettes();
  wireAccidentalPopup();
  wirePresetSaveLoad();
  wireIsonControls();
  wireCorrectionControls();
  wireAudioInit();

  gridChanged();
}

// ── Called whenever the grid state changes ────────────────────────────────────

function gridChanged() {
  app.ladder.refresh();
  if (app.singscope) app.singscope.setRowMap(app.ladder.rowMap);
  const cells = JSON.parse(app.grid.cellsJson());
  app.keyboard.rebuildKeyMap(cells);
  app.engine.updateTuning(cells, app.grid.refNiHz);
  updateIsonVoice(cells);
}

// ── Audio init on first user gesture ─────────────────────────────────────────

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
      app.engine.updateTuning(cells, app.grid.refNiHz);
      updateIsonVoice(cells);
      // Correction defaults to off; the synth's own default is 0.5, so we
      // override explicitly on first init.
      app.engine.setCorrectionVolume(
        app.correctionEnabled ? app.correctionVolume : 0
      );
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
  if (!msg.gate_open || msg.cell_id < 0) {
    app.ladder.setDetectedCell(null, null, 0);
  } else {
    app.ladder.setDetectedCell(
      msg.cell_id,
      msg.neighbor_id >= 0 ? msg.neighbor_id : null,
      msg.neighbor_vel,
    );
  }
  if (app.singscope) app.singscope.pushPitch(msg);
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
  app.grid.applyPthora(0, p.genus, p.degree);
  app.activePresetIdx = idx;

  document.querySelectorAll('.preset-btn').forEach((b, i) => {
    b.classList.toggle('active', i === idx);
  });
  gridChanged();
}

// ── Wiring ────────────────────────────────────────────────────────────────────

function wireControls() {
  const slider    = document.getElementById('ni-hz-slider');
  const niDisplay = document.getElementById('ni-hz-display');
  slider.addEventListener('input', () => {
    const hz = parseFloat(slider.value);
    niDisplay.textContent = hz.toFixed(2);
    app.grid.refNiHz = hz;
    gridChanged();
  });

  document.getElementById('shift-up-btn').addEventListener('click', () => {
    // Placeholder — viewport shift not yet in WASM API.
  });
  document.getElementById('shift-down-btn').addEventListener('click', () => {
    // placeholder
  });

  document.getElementById('reset-btn').addEventListener('click', () => {
    app.grid = new JsTuningGrid();
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

// ── Preset save/load ──────────────────────────────────────────────────────────

const STORAGE_KEY = 'byzorgan_presets';

function loadStoredPresets() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
  catch { return {}; }
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
