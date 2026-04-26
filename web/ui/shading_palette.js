// ShadingPalette — local modifiers (chroa + enharmonic + generic sharp/flat).
//
// Unlike pthorae (which re-root a full region), these only affect the
// immediate neighborhood of the drop target.
//
// Drop payload: `{type: 'shading', shading}` where shading is one of
// 'Zygos', 'Kliton', 'Spathi', 'Enharmonic', 'DiesisGeniki', 'YfesisGeniki',
// or '' to clear. ScaleLadder's drop handler gates these to degree cells
// only.
//
// Glyphs come from Neanes (SBMuFL), rendered as single Private-Use-Area
// codepoints.

import { makeDraggable } from './pointer_drag.js';

// SBMuFL Neanes codepoints (PUA). Using \u escapes so the source is ASCII.
const CP = {
  ZYGOS:          '',  // chroaZygos
  KLITON:         '',  // chroaKliton
  SPATHI:         '',  // chroaSpathi
  ENHARMONIC:     '',  // fthoraEnharmonic
  DIESIS_GENIKI:  '',  // diesisGenikiAbove
  YFESIS_GENIKI:  '',  // yfesisGenikiAbove
};

const ITEMS = [
  { label: 'Zygos',   shading: 'Zygos',        glyph: CP.ZYGOS,
    tip: 'Zygos - drop on a degree cell, or click while singing, to apply this chroa' },
  { label: 'Kliton',  shading: 'Kliton',       glyph: CP.KLITON,
    tip: 'Kliton - drop on a degree cell, or click while singing, to apply this chroa' },
  { label: 'Spathi',  shading: 'Spathi',       glyph: CP.SPATHI,
    tip: 'Spathi - click while singing or drop on a degree cell to apply adjacent 4-moria intervals' },
  { label: 'Ajem',    shading: 'Enharmonic',   glyph: CP.ENHARMONIC,
    tip: 'Enharmonic (Ajem) - click while singing or drop to apply the enharmonic modifier' },
  { label: '♯ Gen',   shading: 'DiesisGeniki', glyph: CP.DIESIS_GENIKI,
    tip: 'Geniki Diesis (general sharp) - click while singing or drop to raise this note' },
  { label: '♭ Gen',   shading: 'YfesisGeniki', glyph: CP.YFESIS_GENIKI,
    tip: 'Geniki Yfesis (general flat) - click while singing or drop to lower this note' },
  { label: 'Clear',   shading: '',             glyph: '',
    tip: 'Clear shading on the sung note or dropped target region' },
];

export function buildQuickShadingControls({ container, onPick }) {
  if (!container || !onPick) return;
  container.innerHTML = '';
  for (const item of ITEMS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'quick-shading-btn';
    btn.textContent = item.label;
    btn.title = item.tip;
    btn.addEventListener('click', () => {
      onPick({ type: 'shading', shading: item.shading });
    });
    container.appendChild(btn);
  }
}

export class ShadingPalette {
  constructor(container) {
    container.innerHTML = '';
    const row = document.createElement('div');
    row.className = 'shading-row';
    for (const item of ITEMS) {
      const el = document.createElement('div');
      el.className = 'shading-icon';
      el.title = item.tip;
      el.tabIndex = 0;
      el.setAttribute('role', 'button');

      if (item.glyph) {
        el.innerHTML = `<span class="palette-glyph-sbmufl">${item.glyph}</span>`
                     + `<span class="palette-label">${item.label}</span>`;
      } else {
        // Clear: no glyph, just the label in a dashed box.
        el.innerHTML = `<span class="palette-label">${item.label}</span>`;
        el.style.borderStyle = 'dashed';
      }

      makeDraggable(el, {
        payload: () => ({ type: 'shading', shading: item.shading }),
        targetSelector: '#scale-ladder',
        clickEvent: 'chanterlab:palette-click',
      });
      row.appendChild(el);
    }
    container.appendChild(row);
  }
}
