import { rgbaToGray } from '../pipeline/buffers.js';
import { recognizePage } from '../pipeline/recognize.js';
import { buildNeanesTemplates } from '../pipeline/templates.js';
import {
  semanticTokensFromGlyphs,
  chantScoreFromGlyphGroups,
} from '../../score/glyph_import.js';
import { resolveGlyphGroups } from '../../score/glyph_group_resolver.js';
import { compileChantScore } from '../../score/compiler.js?v=chant-script-engine-phase6w';
import { characterForCodepoint } from '../synth/layout.js';

const $ = id => document.getElementById(id);

const state = {
  imageBitmap: undefined,
  grayBuffer: undefined,
  templates: undefined,
  result: undefined,
};

async function ensureTemplates(cellSize) {
  if (state.templates && state.templates[0]?.cellSize === cellSize) return state.templates;
  setStatus(`Building templates at ${cellSize}px…`);
  state.templates = await buildNeanesTemplates({ cellSize });
  setStatus(`Templates ready (${state.templates.length} glyphs).`);
  return state.templates;
}

function setStatus(text) {
  $('status').textContent = text;
}

async function handleFile(file) {
  if (!file) return;
  setStatus(`Loading ${file.name}…`);
  const bitmap = await createImageBitmap(file);
  state.imageBitmap = bitmap;
  drawSourceImage(bitmap);
  await runRecognition();
}

function drawSourceImage(bitmap) {
  const canvas = $('source');
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(bitmap, 0, 0);
}

function readSourceGray() {
  const canvas = $('source');
  const ctx = canvas.getContext('2d');
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  return rgbaToGray(imageData.data, canvas.width, canvas.height);
}

async function runRecognition() {
  if (!state.imageBitmap) return;
  const cellSize = Number($('cellSize').value) || 48;
  const minPixels = Number($('minPixels').value) || 12;
  const templates = await ensureTemplates(cellSize);

  setStatus('Recognising…');
  state.grayBuffer = readSourceGray();
  const result = recognizePage(state.grayBuffer, templates, {
    minComponentPixels: minPixels,
    topK: 4,
  });
  state.result = result;

  drawOverlay(result);
  renderTokenList(result);
  renderCompiled(result);
  setStatus(`${result.tokens.length} glyphs · ${result.lineCount} line(s) · threshold ${result.binaryThreshold}`);
}

function drawOverlay(result) {
  const overlay = $('overlay');
  overlay.width = state.imageBitmap.width;
  overlay.height = state.imageBitmap.height;
  const ctx = overlay.getContext('2d');
  ctx.clearRect(0, 0, overlay.width, overlay.height);

  ctx.lineWidth = 1.5;
  ctx.font = '11px ui-monospace, monospace';
  ctx.textBaseline = 'bottom';
  for (const token of result.tokens) {
    const { x, y, w, h } = token.region.bbox;
    ctx.strokeStyle = colorForConfidence(token.confidence);
    ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
    if ($('showLabels').checked) {
      ctx.fillStyle = colorForConfidence(token.confidence);
      ctx.fillText(`${token.glyphName} ${(token.confidence * 100 | 0)}%`, x, y - 1);
    }
  }
}

function colorForConfidence(c) {
  if (c >= 0.85) return 'rgba(40, 180, 80, 0.95)';
  if (c >= 0.7) return 'rgba(220, 170, 30, 0.95)';
  return 'rgba(220, 70, 70, 0.95)';
}

function renderTokenList(result) {
  const wrap = $('tokens');
  wrap.innerHTML = '';
  for (const token of result.tokens) {
    const item = document.createElement('div');
    item.className = 'token';
    const main = document.createElement('span');
    main.className = 'glyph';
    main.style.fontFamily = '"Neanes"';
    main.textContent = characterForCodepoint(token.codepoint) ?? '?';
    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = `${token.glyphName} · ${(token.confidence * 100 | 0)}%`;
    item.appendChild(main);
    item.appendChild(label);
    if (token.alternates?.length) {
      const alts = document.createElement('span');
      alts.className = 'alternates';
      alts.textContent = '↳ ' + token.alternates.slice(0, 3)
        .map(a => `${a.glyphName} ${(a.confidence * 100 | 0)}%`)
        .join(' · ');
      item.appendChild(alts);
    }
    wrap.appendChild(item);
  }
}

function renderCompiled(result) {
  const out = $('compiled');
  if (!result.tokens.length) {
    out.textContent = '(no glyphs recognized)';
    return;
  }
  const semantic = semanticTokensFromGlyphs(result.tokens);
  const groups = resolveGlyphGroups(semantic);
  const startDegree = $('startDegree').value || 'Ni';
  const compiled = chantScoreFromGlyphGroups(groups, {
    title: 'OCR Imported Page',
    startDegree,
    bpm: 120,
  });
  const final = compileChantScore(compiled.score, { diagnostics: [...compiled.diagnostics] });
  const lines = [];
  lines.push(`Groups: ${groups.length}`);
  lines.push(`Notes:  ${final.notes.length}`);
  lines.push(`Rests:  ${final.rests.length}`);
  lines.push(`Diagnostics: ${final.diagnostics.length}`);
  if (final.notes.length) {
    lines.push('');
    lines.push('Note sequence:');
    lines.push(final.notes.map(note => `${note.degree}${note.register ? `(${note.register})` : ''}`).join(' '));
  }
  if (final.diagnostics.length) {
    lines.push('');
    lines.push('Diagnostics:');
    for (const diag of final.diagnostics.slice(0, 12)) {
      lines.push(`  [${diag.severity}] ${diag.code} — ${diag.message}`);
    }
  }
  out.textContent = lines.join('\n');
}

window.addEventListener('DOMContentLoaded', () => {
  $('file').addEventListener('change', e => handleFile(e.target.files?.[0]));
  $('runBtn').addEventListener('click', runRecognition);
  $('showLabels').addEventListener('change', () => state.result && drawOverlay(state.result));

  const dropZone = $('dropZone');
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('hover'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('hover'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('hover');
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  });
});
