// PthoraPalette — full-region pthora items.
//
// Diatonic and Western rows target the eight scale-degree positions. Soft and
// hard chromatic rows target the four cyclic chromatic phases; the drop target
// supplies the degree name, while the phase determines how the interval cycle
// is anchored.
//
// Glyphs come from Neanes (SBMuFL), rendered as single Private-Use-Area
// codepoints. Diatonic gives each degree a distinct glyph; the chromatic
// genera only ship two glyphs each in SBMuFL, so phase buttons reuse them by
// parity.
//
// Each slot carries `{type: 'pthora', genus, degree?, phase?}`. ScaleLadder's
// drop handler resolves the target cell before calling the engine.

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

// Per-column glyphs for degree-targeted genera.
const DIATONIC_GLYPHS = [
  CP.DIAT_NI_LOW, CP.DIAT_PA, CP.DIAT_VOU, CP.DIAT_GA,
  CP.DIAT_DI, CP.DIAT_KE, CP.DIAT_ZO, CP.DIAT_NI_HIGH,
];
const WESTERN_SYMBOLS = ['do', 're', 'mi', 'fa', 'so', 'la', 'ti', "do'"];

const ROWS = [
  { label: 'Diatonic', genus: 'Diatonic', kind: 'degree', glyphs: DIATONIC_GLYPHS },
  {
    label: 'Soft Chr',
    genus: 'SoftChromatic',
    kind: 'phase',
    phases: [
      { phase: 0, label: '0 Di', glyph: CP.SOFT_DI },
      { phase: 1, label: '1 Ke', glyph: CP.SOFT_KE },
      { phase: 2, label: '2 Di', glyph: CP.SOFT_DI },
      { phase: 3, label: '3 Ke', glyph: CP.SOFT_KE },
    ],
  },
  {
    label: 'Hard Chr',
    genus: 'HardChromatic',
    kind: 'phase',
    phases: [
      { phase: 0, label: '0 Pa', glyph: CP.HARD_PA },
      { phase: 1, label: '1 Di', glyph: CP.HARD_DI },
      { phase: 2, label: '2 Pa', glyph: CP.HARD_PA },
      { phase: 3, label: '3 Di', glyph: CP.HARD_DI },
    ],
  },
  { label: 'Western',
    genus: 'Western',
    kind: 'degree',
    glyphs: WESTERN_SYMBOLS,
    glyphClass: 'palette-glyph-western',
  }
];

const CHROMATIC_PHASES_BY_GENUS = Object.fromEntries(
  ROWS.filter(row => row.kind === 'phase').map(row => [row.genus, row.phases])
);

export function buildQuickPthoraControls({ genusSelect, degreeContainer, onPick }) {
  if (!genusSelect || !degreeContainer || !onPick) return;
  const render = () => {
    degreeContainer.innerHTML = '';
    const genus = genusSelect.value;
    const phases = CHROMATIC_PHASES_BY_GENUS[genus];
    const options = phases ?? DEGREES;
    degreeContainer.classList.toggle('phase-options', Boolean(phases));
    for (const option of options) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'quick-pthora-btn';
      btn.textContent = option.label;
      btn.title = phases
        ? `Apply ${genus === 'SoftChromatic' ? 'soft' : 'hard'} chromatic phase ${option.phase} to the sung note`
        : `Apply selected pthora as ${option.label} to the sung note`;
      btn.addEventListener('click', () => {
        onPick({
          type: 'pthora',
          genus,
          degree: phases ? null : option.degree,
          phase: phases ? option.phase : null,
        });
      });
      degreeContainer.appendChild(btn);
    }
  };
  genusSelect.addEventListener('change', render);
  render();
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
      rowEl.className = `pthora-row ${row.kind === 'phase' ? 'pthora-phase-row' : ''}`;

      const labelEl = document.createElement('div');
      labelEl.className = 'pthora-row-label';
      labelEl.textContent = row.label;
      rowEl.appendChild(labelEl);

      if (row.kind === 'phase') {
        for (const phase of row.phases) {
          const el = document.createElement('div');
          el.className = 'pthora-icon pthora-phase-icon';
          el.title = `${row.label} phase ${phase.phase} - drop on a note, or click while singing, to anchor that note in this chromatic phase`;
          el.tabIndex = 0;
          el.setAttribute('role', 'button');
          const glyphEl = document.createElement('span');
          glyphEl.className = 'palette-glyph-sbmufl';
          glyphEl.textContent = phase.glyph;
          el.appendChild(glyphEl);
          const degreeEl = document.createElement('span');
          degreeEl.className = 'palette-degree-label';
          degreeEl.textContent = phase.label;
          el.appendChild(degreeEl);

          makeDraggable(el, {
            payload: () => ({
              type: 'pthora',
              genus: row.genus,
              degree: null,
              phase: phase.phase,
            }),
            targetSelector: '#scale-ladder',
            clickEvent: 'chanterlab:palette-click',
          });
          rowEl.appendChild(el);
        }
        container.appendChild(rowEl);
        continue;
      }

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
