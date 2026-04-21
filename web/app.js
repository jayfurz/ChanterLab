import init, { JsTuningGrid } from './pkg/byzorgan_core.js';
import { ScaleLadder } from './ui/scale_ladder.js';

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
  grid: null,
  ladder: null,
  activePresetIdx: 0,
};

// ── Boot ─────────────────────────────────────────────────────────────────────

async function main() {
  await init();

  app.grid = new JsTuningGrid();

  // ScaleLadder
  const canvas = document.getElementById('scale-ladder');
  app.ladder = new ScaleLadder(canvas, app);

  buildPresetButtons();
  wireControls();
  wirePalettes();
  wireAccidentalPopup();
  wirePresetSaveLoad();

  app.ladder.refresh();
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
  // Reset grid with the chosen genus: apply pthora at moria 0 on a fresh grid.
  app.grid = new JsTuningGrid();
  app.grid.applyPthora(0, p.genus, p.degree);
  app.activePresetIdx = idx;

  document.querySelectorAll('.preset-btn').forEach((b, i) => {
    b.classList.toggle('active', i === idx);
  });
  app.ladder.refresh();
}

// ── Wiring ────────────────────────────────────────────────────────────────────

function wireControls() {
  // Ni Hz slider
  const slider = document.getElementById('ni-hz-slider');
  const niDisplay = document.getElementById('ni-hz-display');
  slider.addEventListener('input', () => {
    const hz = parseFloat(slider.value);
    niDisplay.textContent = hz.toFixed(2);
    app.grid.refNiHz = hz;
    app.ladder.refresh();
  });

  // Viewport shift
  document.getElementById('shift-up-btn').addEventListener('click', () => {
    // Not yet implemented in WASM API — placeholder for Phase 2.7 extension.
    // Would need a shiftViewport method on JsTuningGrid.
  });
  document.getElementById('shift-down-btn').addEventListener('click', () => {
    // placeholder
  });

  // Reset
  document.getElementById('reset-btn').addEventListener('click', () => {
    app.grid = new JsTuningGrid();
    app.activePresetIdx = 0;
    document.querySelectorAll('.preset-btn').forEach((b, i) => {
      b.classList.toggle('active', i === 0);
    });
    app.ladder.refresh();
  });
}

// ── Palettes ──────────────────────────────────────────────────────────────────

const PTHORA_ITEMS = [
  { label: 'Diatonic · Ni',      genus: 'Diatonic',      degree: 'Ni'  },
  { label: 'Hard Chr · Pa',      genus: 'HardChromatic',  degree: 'Pa'  },
  { label: 'Soft Chr · Ni',      genus: 'SoftChromatic',  degree: 'Ni'  },
  { label: 'Grave Di · Ga',      genus: 'GraveDiatonic',  degree: 'Ga'  },
  { label: 'Enh Zo · Zo',        genus: 'EnharmonicZo',   degree: 'Zo'  },
  { label: 'Enh Ga · Ga',        genus: 'EnharmonicGa',   degree: 'Ga'  },
];

const SHADING_ITEMS = [
  { label: 'Zygos',   shading: 'Zygos'   },
  { label: 'Kliton',  shading: 'Kliton'  },
  { label: 'Spathi A',shading: 'SpathiA' },
  { label: 'Spathi B',shading: 'SpathiB' },
  { label: '(clear)', shading: ''         },
];

function wirePalettes() {
  const pthoraContainer = document.getElementById('pthora-palette');
  PTHORA_ITEMS.forEach(item => {
    const el = document.createElement('div');
    el.className = 'pthora-icon';
    el.draggable = true;
    el.textContent = item.label;
    el.addEventListener('dragstart', e => {
      e.dataTransfer.setData('application/json', JSON.stringify({ type: 'pthora', genus: item.genus, degree: item.degree }));
    });
    pthoraContainer.appendChild(el);
  });

  const shadingContainer = document.getElementById('shading-palette');
  SHADING_ITEMS.forEach(item => {
    const el = document.createElement('div');
    el.className = 'shading-icon';
    el.draggable = true;
    el.textContent = item.label;
    el.addEventListener('dragstart', e => {
      e.dataTransfer.setData('application/json', JSON.stringify({ type: 'shading', shading: item.shading }));
    });
    shadingContainer.appendChild(el);
  });
}

// ── Accidental popup ──────────────────────────────────────────────────────────

let _accPopupCell = null;

function wireAccidentalPopup() {
  const popup = document.getElementById('accidental-popup');

  // Preset offset buttons.
  [-8, -6, -4, -2, +2, +4, +6, +8].forEach(offset => {
    const btn = document.createElement('button');
    btn.className = 'acc-btn';
    btn.textContent = (offset > 0 ? '+' : '') + offset;
    btn.addEventListener('click', () => {
      if (_accPopupCell) {
        app.grid.setAccidental(_accPopupCell.moria, offset);
        app.ladder.refresh();
      }
      hideAccidentalPopup();
    });
    document.getElementById('acc-preset-btns').appendChild(btn);
  });

  // Custom input.
  document.getElementById('acc-custom-apply').addEventListener('click', () => {
    const val = parseInt(document.getElementById('acc-custom-input').value, 10);
    if (!isNaN(val) && val % 2 === 0 && _accPopupCell) {
      app.grid.setAccidental(_accPopupCell.moria, val);
      app.ladder.refresh();
    }
    hideAccidentalPopup();
  });

  // Clear.
  document.getElementById('acc-clear-btn').addEventListener('click', () => {
    if (_accPopupCell) {
      app.grid.clearOverride(_accPopupCell.moria);
      app.ladder.refresh();
    }
    hideAccidentalPopup();
  });

  // Dismiss on outside click.
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
      const json = presets[name];
      try {
        app.grid = JsTuningGrid.fromJson(json);
        app.ladder.refresh();
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
      const json = app.grid.toJson();
      const stored = loadStoredPresets();
      stored[name] = json;
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
