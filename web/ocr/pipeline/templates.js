// Browser-side template builder: rasterize every known SBMuFL glyph from the
// bundled Neanes font into a fixed-size grayscale buffer for NCC matching.

import { listGlyphImportTokens } from '../../score/glyph_import.js';
import { createTemplate } from './classify.js';
import { ensureFontReady } from '../synth/render_browser.js';

const DEFAULT_CELL = 48;

export async function buildNeanesTemplates(options = {}) {
  const cellSize = options.cellSize ?? DEFAULT_CELL;
  const fontFamily = options.fontFamily ?? 'Neanes';
  await ensureFontReady(fontFamily, cellSize);

  const supersample = 2;
  const renderSize = cellSize * supersample;
  const canvas = options.canvas ?? new OffscreenCanvas(renderSize, renderSize);
  const ctx = canvas.getContext('2d');

  const tokens = listGlyphImportTokens().filter(token => token.codepoint);
  const templates = [];
  for (const token of tokens) {
    const character = characterForCodepoint(token.codepoint);
    if (!character) continue;
    const buffer = rasterizeGlyph({
      character,
      cellSize,
      renderSize,
      fontFamily,
      ctx,
    });
    if (!buffer) continue;
    templates.push(createTemplate({ glyphName: token.glyphName, codepoint: token.codepoint, buffer }));
  }
  return templates;
}

export function rasterizeGlyph({ character, cellSize, renderSize, fontFamily, ctx }) {
  ctx.save();
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, renderSize, renderSize);
  ctx.fillStyle = '#000000';
  const fontPx = Math.round(renderSize * 0.85);
  ctx.font = `${fontPx}px "${fontFamily}"`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(character, renderSize / 2, renderSize / 2);
  ctx.restore();

  const imageData = ctx.getImageData(0, 0, renderSize, renderSize);
  return downsampleToGray(imageData.data, renderSize, cellSize);
}

function downsampleToGray(rgba, srcSize, dstSize) {
  const factor = srcSize / dstSize;
  const data = new Uint8ClampedArray(dstSize * dstSize);
  for (let y = 0; y < dstSize; y += 1) {
    for (let x = 0; x < dstSize; x += 1) {
      const srcX0 = Math.floor(x * factor);
      const srcY0 = Math.floor(y * factor);
      const srcX1 = Math.min(srcSize, Math.ceil((x + 1) * factor));
      const srcY1 = Math.min(srcSize, Math.ceil((y + 1) * factor));
      let sum = 0;
      let count = 0;
      for (let sy = srcY0; sy < srcY1; sy += 1) {
        for (let sx = srcX0; sx < srcX1; sx += 1) {
          const i = (sy * srcSize + sx) * 4;
          const luma = rgba[i] * 0.299 + rgba[i + 1] * 0.587 + rgba[i + 2] * 0.114;
          sum += luma;
          count += 1;
        }
      }
      data[y * dstSize + x] = count ? (sum / count) | 0 : 255;
    }
  }
  return { width: dstSize, height: dstSize, data };
}

function characterForCodepoint(codepoint) {
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(String(codepoint).trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}
