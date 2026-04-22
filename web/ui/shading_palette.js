// ShadingPalette — draggable tetrachord shadings.
//
// Drop payload: `{type: 'shading', shading}` where shading is one of
// 'Zygos', 'Kliton', 'SpathiKe', 'SpathiGa', or '' to clear.
// ScaleLadder's drop handler gates these to degree cells only.

const ITEMS = [
  // Zygos (yoke) — two parallel bars, evoking the paired tetrachord.
  { label: 'Zygos',    shading: 'Zygos',    svg: `
      <g stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none">
        <line x1="6" y1="8"  x2="18" y2="8"/>
        <line x1="6" y1="16" x2="18" y2="16"/>
      </g>` },
  // Kliton — a single slope.
  { label: 'Kliton',   shading: 'Kliton',   svg: `
      <g stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none">
        <polyline points="5,18 12,6 19,18"/>
      </g>` },
  // Spathi on Ke — blade with crossguard near the top.
  { label: 'Spathi Ke', shading: 'SpathiKe', svg: `
      <g stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none">
        <line x1="12" y1="4"  x2="12" y2="20"/>
        <line x1="7"  y1="8"  x2="17" y2="8"/>
      </g>` },
  // Spathi on Ga — blade with crossguard near the bottom.
  { label: 'Spathi Ga', shading: 'SpathiGa', svg: `
      <g stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none">
        <line x1="12" y1="4"  x2="12" y2="20"/>
        <line x1="7"  y1="16" x2="17" y2="16"/>
      </g>` },
  // Clear — dashed circle to mean "remove".
  { label: 'Clear',    shading: '',         svg: `
      <g stroke="currentColor" stroke-width="1.6" fill="none" stroke-dasharray="2 2">
        <circle cx="12" cy="12" r="7"/>
      </g>` },
];

export class ShadingPalette {
  constructor(container) {
    container.innerHTML = '';
    for (const item of ITEMS) {
      const el = document.createElement('div');
      el.className = 'shading-icon';
      el.draggable = true;
      el.title = item.shading
        ? `${item.label} — drop on a degree cell to apply this shading`
        : `${item.label} — drop on a degree cell to clear shading`;
      el.innerHTML = `<svg viewBox="0 0 24 24" class="palette-glyph" aria-hidden="true">${item.svg}</svg>`
                   + `<span class="palette-label">${item.label}</span>`;
      el.addEventListener('dragstart', e => {
        e.dataTransfer.setData('application/json', JSON.stringify({
          type: 'shading',
          shading: item.shading,
        }));
        e.dataTransfer.effectAllowed = 'copy';
      });
      container.appendChild(el);
    }
  }
}
