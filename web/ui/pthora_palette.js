// PthoraPalette — draggable pthora items.
//
// Each item carries a drop payload of `{type: 'pthora', genus, degree}` which
// ScaleLadder's drop handler routes into `grid.applyPthora(moria, genus, degree)`.
//
// Icons are inline SVG ladder-fragments whose line spacing mirrors each
// genus's step pattern — a visual cue, not a literal rendering.

const ITEMS = [
  { label: 'Diatonic',  genus: 'Diatonic',       degree: 'Ni', pattern: [5, 10, 15, 20] },
  { label: 'Hard Chr',  genus: 'HardChromatic',  degree: 'Pa', pattern: [4, 6, 17, 20] },
  { label: 'Soft Chr',  genus: 'SoftChromatic',  degree: 'Ni', pattern: [5, 8, 15, 19] },
  { label: 'Grave Di',  genus: 'GraveDiatonic',  degree: 'Ga', pattern: [4, 6, 12, 17, 20] },
  { label: 'Enh Zo',    genus: 'EnharmonicZo',   degree: 'Zo', pattern: [4, 6, 12, 20] },
  { label: 'Enh Ga',    genus: 'EnharmonicGa',   degree: 'Ga', pattern: [4, 6, 10, 14, 18, 20] },
];

function glyph(pattern) {
  const lines = pattern
    .map(y => `<line x1="5" y1="${y}" x2="19" y2="${y}"/>`)
    .join('');
  return `<svg viewBox="0 0 24 24" class="palette-glyph" aria-hidden="true">`
       + `<g stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none">${lines}</g>`
       + `</svg>`;
}

export class PthoraPalette {
  constructor(container) {
    container.innerHTML = '';
    for (const item of ITEMS) {
      const el = document.createElement('div');
      el.className = 'pthora-icon';
      el.draggable = true;
      el.title = `${item.label} — drop on a cell to apply this pthora rooted at ${item.degree}`;
      el.innerHTML = glyph(item.pattern)
                   + `<span class="palette-label">${item.label}</span>`;
      el.addEventListener('dragstart', e => {
        e.dataTransfer.setData('application/json', JSON.stringify({
          type: 'pthora',
          genus: item.genus,
          degree: item.degree,
        }));
        e.dataTransfer.effectAllowed = 'copy';
      });
      container.appendChild(el);
    }
  }
}
