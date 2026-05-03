export function renderLayoutToCanvas(layout, canvas, options = {}) {
  const { background = '#ffffff', glyphColor = '#000000', drawBBoxes = false } = options;
  const dpr = options.devicePixelRatio ?? globalThis.devicePixelRatio ?? 1;

  canvas.width = Math.ceil(layout.width * dpr);
  canvas.height = Math.ceil(layout.height * dpr);
  canvas.style.width = `${layout.width}px`;
  canvas.style.height = `${layout.height}px`;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, layout.width, layout.height);
  ctx.fillStyle = glyphColor;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';

  for (const glyph of layout.glyphs) {
    if (!glyph.character) continue;
    const fontSize = Math.round(glyph.bbox.h);
    ctx.font = `${fontSize}px "${layout.fontFamily ?? 'Neanes'}"`;
    const cx = glyph.bbox.x + glyph.bbox.w / 2;
    const baselineY = glyph.bbox.y + glyph.bbox.h;
    ctx.fillText(glyph.character, cx, baselineY);
  }

  if (drawBBoxes) {
    ctx.lineWidth = 1;
    for (const glyph of layout.glyphs) {
      ctx.strokeStyle = bboxColorForSlot(glyph.slot);
      ctx.strokeRect(glyph.bbox.x + 0.5, glyph.bbox.y + 0.5, glyph.bbox.w - 1, glyph.bbox.h - 1);
    }
  }

  return canvas;
}

function bboxColorForSlot(slot) {
  if (slot === 'main') return 'rgba(0, 100, 220, 0.55)';
  if (slot === 'above') return 'rgba(180, 60, 60, 0.55)';
  if (slot === 'below') return 'rgba(40, 140, 60, 0.55)';
  return 'rgba(120, 120, 120, 0.55)';
}

export async function ensureFontReady(family, size = 48, sample = '\u{1D046}') {
  if (!globalThis.document?.fonts?.load) return false;
  await globalThis.document.fonts.load(`${size}px "${family}"`, sample);
  return globalThis.document.fonts.check(`${size}px "${family}"`);
}
