// PthoraPalette — 3×8 grid of full-region pthora items.
//
// Rows are genera (Diatonic, Western, Soft Chromatic, Hard Chromatic). Columns
// are the eight scale degrees (Ni low, Pa, Vou, Ga, Di, Ke, Zo, Ni high). Dropping
// a cell on the ladder re-roots a region at that moria using the row's genus
// and the column's target degree.
//
// Glyphs come from Neanes (SBMuFL), rendered as single Private-Use-Area
// codepoints. Diatonic gives each degree a distinct glyph; the chromatic
// genera only ship two glyphs each in SBMuFL, so those rows alternate
// per-column — matching Byzantine practice where adjacent notes alternate
// between two pthora forms.
//
// Each slot carries `{type: 'pthora', genus, degree}`. ScaleLadder's drop
// handler routes it into `grid.applyPthora(moria, genus, degree)`.

import { makeDraggable } from './pointer_drag.js';

// Column order — mirrors the scale walking upward.
const DEGREES = [
  { label: 'Ni',  degree: 'Ni',  octaveHint: 'low'  },
  { label: 'Pa',  degree: 'Pa'                      },
  { label: 'Vou', degree: 'Vou'                     },
  { label: 'Ga',  degree: 'Ga'                      },
  { label: 'Di',  degree: 'Di'                      },
  { label: 'Ke',  degree: 'Ke'                      },
  { label: 'Zo',  degree: 'Zo'                      },
  { label: 'Ni′', degree: 'Ni',  octaveHint: 'high' },
];

// SBMuFL codepoints in Neanes.otf.
const CP = {
  DIAT_NI_LOW:  '',
  DIAT_PA:      '',
  DIAT_VOU:     '',
  DIAT_GA:      '',
  DIAT_DI:      '',
  DIAT_KE:      '',
  DIAT_ZO:      '',
  DIAT_NI_HIGH: '',
  HARD_PA:      '',
  HARD_DI:      '',
  SOFT_DI:      '',
  SOFT_KE:      '',
};

// Per-column glyphs for each genus. Diatonic has a unique glyph per degree.
// Chromatic rows alternate; the alternation starts with the "Di" form at
// column 0 (Ni-low), matching the user's rotation preference.
const DIATONIC_GLYPHS = [
  CP.DIAT_NI_LOW, CP.DIAT_PA, CP.DIAT_VOU, CP.DIAT_GA,
  CP.DIAT_DI, CP.DIAT_KE, CP.DIAT_ZO, CP.DIAT_NI_HIGH,
];
const SOFT_CHR_GLYPHS = [
  CP.SOFT_DI, CP.SOFT_KE, CP.SOFT_DI, CP.SOFT_KE,
  CP.SOFT_DI, CP.SOFT_KE, CP.SOFT_DI, CP.SOFT_KE,
];
const HARD_CHR_GLYPHS = [
  CP.HARD_DI, CP.HARD_PA, CP.HARD_DI, CP.HARD_PA,
  CP.HARD_DI, CP.HARD_PA, CP.HARD_DI, CP.HARD_PA,
];
const WESTERN_SYMBOLS = ['do', 're', 'mi', 'fa', 'so', 'la', 'ti', "do'"];

const ROWS = [
  { label: 'Diatonic', genus: 'Diatonic', glyphs: DIATONIC_GLYPHS },
  { label: 'Soft Chr', genus: 'SoftChromatic', glyphs: SOFT_CHR_GLYPHS },
  { label: 'Hard Chr', genus: 'HardChromatic', glyphs: HARD_CHR_GLYPHS },
  { label: 'Western',
    genus: 'Western',
    glyphs: WESTERN_SYMBOLS,
    glyphClass: 'palette-glyph-western',
  }
];

export function buildQuickPthoraControls({ genusSelect, degreeContainer, onPick }) {
  if (!genusSelect || !degreeContainer || !onPick) return;
  degreeContainer.innerHTML = '';
  for (const col of DEGREES) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'quick-pthora-btn';
    btn.textContent = col.label;
    btn.title = `Apply selected pthora as ${col.label} to the sung note`;
    btn.addEventListener('click', () => {
      onPick({ type: 'pthora', genus: genusSelect.value, degree: col.degree });
    });
    degreeContainer.appendChild(btn);
  }
}

export class PthoraPalette {
  constructor(container) {
    container.innerHTML = '';

    // Column header: degree labels.
    const headerRow = document.createElement('div');
    headerRow.className = 'pthora-column-labels';
    const spacer = document.createElement('span');
    spacer.textContent = '';
    headerRow.appendChild(spacer);
    for (const col of DEGREES) {
      const s = document.createElement('span');
      s.textContent = col.label;
      headerRow.appendChild(s);
    }
    container.appendChild(headerRow);

    // Three grid rows.
    for (const row of ROWS) {
      const rowEl = document.createElement('div');
      rowEl.className = 'pthora-row';

      const labelEl = document.createElement('div');
      labelEl.className = 'pthora-row-label';
      labelEl.textContent = row.label;
      rowEl.appendChild(labelEl);

      for (let i = 0; i < DEGREES.length; i++) {
        const col = DEGREES[i];
        const glyph = row.glyphs[i];
        const el = document.createElement('div');
        el.className = 'pthora-icon';
        el.title = `${row.label} pthora - drop on a note, or click while singing, to re-root as ${col.label}`;
        el.tabIndex = 0;
        el.setAttribute('role', 'button');
        const glyphEl = document.createElement('span');
        glyphEl.className = row.glyphClass ?? 'palette-glyph-sbmufl';
        glyphEl.textContent = glyph;
        el.appendChild(glyphEl);
        const degreeEl = document.createElement('span');
        degreeEl.className = 'palette-degree-label';
        degreeEl.textContent = col.label;
        el.appendChild(degreeEl);

        makeDraggable(el, {
          payload: () => ({ type: 'pthora', genus: row.genus, degree: col.degree }),
          targetSelector: '#scale-ladder',
          clickEvent: 'chanterlab:palette-click',
        });
        rowEl.appendChild(el);
      }

      container.appendChild(rowEl);
    }
  }
}
