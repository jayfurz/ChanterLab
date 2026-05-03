import { planAtlas } from './atlas_layout.js';
import { renderAtlasToCanvas } from './atlas_render.js';
import { ensureFontReady } from '../synth/render_browser.js';

const $ = id => document.getElementById(id);

function readConfig() {
  return {
    columns: Number($('columns').value) || 8,
    cellWidth: Number($('cellWidth').value) || 140,
    cellHeight: Number($('cellHeight').value) || 112,
    glyphSize: Number($('glyphSize').value) || 64,
    labelSize: Number($('labelSize').value) || 10,
  };
}

async function render() {
  const config = readConfig();
  const layout = planAtlas(config);
  await ensureFontReady('Neanes', config.glyphSize);
  renderAtlasToCanvas(layout, $('atlas'));
  $('status').textContent = `${layout.glyphCount} glyphs · ${layout.width}×${layout.height}px · ${layout.sections.length} sections`;
  $('downloadBtn').disabled = false;
}

function downloadPng() {
  $('atlas').toBlob(blob => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chant-glyph-atlas-${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, 'image/png');
}

window.addEventListener('DOMContentLoaded', () => {
  $('renderBtn').addEventListener('click', () => { render().catch(err => console.error(err)); });
  $('downloadBtn').addEventListener('click', downloadPng);
  render().catch(err => console.error(err));
});
