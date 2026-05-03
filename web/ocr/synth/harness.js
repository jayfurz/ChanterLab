import { semanticTokenGroupsFromGlyphText } from '../../score/glyph_import.js';
import {
  GLYPH_IMPORT_SAMPLE_FIXTURES,
} from '../../score/glyph_import_samples.js';
import { planSyntheticPage, groundTruthFromLayout } from './layout.js';
import { renderLayoutToCanvas, ensureFontReady } from './render_browser.js';

const $ = id => document.getElementById(id);

const state = {
  layout: undefined,
  manifest: undefined,
  pageBlob: undefined,
};

function populateSamples() {
  const select = $('sample');
  for (const sample of GLYPH_IMPORT_SAMPLE_FIXTURES) {
    if (sample.source !== 'glyph') continue;
    const opt = document.createElement('option');
    opt.value = sample.id;
    opt.textContent = sample.title;
    select.appendChild(opt);
  }
}

function readOptions() {
  return {
    fontSize: Number($('fontSize').value) || 48,
    pageWidth: Number($('pageWidth').value) || 1024,
    marginX: Number($('marginX').value) || 32,
    marginY: Number($('marginY').value) || 32,
    lineHeight: Number($('lineHeight').value) || 132,
  };
}

async function render() {
  const text = $('text').value.trim();
  if (!text) return;
  const groups = semanticTokenGroupsFromGlyphText(text);
  const layout = planSyntheticPage(groups, readOptions());
  state.layout = layout;
  state.manifest = groundTruthFromLayout(layout);

  await ensureFontReady('Neanes', layout.fontSize);
  renderLayoutToCanvas(layout, $('canvas'), { drawBBoxes: $('showBoxes').checked });

  $('summary').textContent =
    `${layout.glyphs.length} glyphs · ${layout.groups.length} groups · ` +
    `${layout.width}×${layout.height}px`;
  $('downloadPng').disabled = false;
  $('downloadJson').disabled = false;
}

function loadSample() {
  const id = $('sample').value;
  const sample = GLYPH_IMPORT_SAMPLE_FIXTURES.find(s => s.id === id);
  if (!sample) return;
  $('text').value = sample.text;
}

function downloadJson() {
  if (!state.manifest) return;
  const blob = new Blob([JSON.stringify(state.manifest, null, 2)], { type: 'application/json' });
  triggerDownload(blob, `synth_${Date.now()}.json`);
}

function downloadPng() {
  $('canvas').toBlob(blob => {
    if (!blob) return;
    triggerDownload(blob, `synth_${Date.now()}.png`);
  }, 'image/png');
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

window.addEventListener('DOMContentLoaded', () => {
  populateSamples();
  $('renderBtn').addEventListener('click', () => { render().catch(err => console.error(err)); });
  $('loadSampleBtn').addEventListener('click', loadSample);
  $('downloadPng').addEventListener('click', downloadPng);
  $('downloadJson').addEventListener('click', downloadJson);
  $('text').value = 'ison oligon oligon apostrofos gorgonAbove leimma2';
  render().catch(err => console.error(err));
});
