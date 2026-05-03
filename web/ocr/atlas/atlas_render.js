import { wrapGlyphName } from './atlas_layout.js';

export function renderAtlasToCanvas(layout, canvas, options = {}) {
  const dpr = options.devicePixelRatio ?? globalThis.devicePixelRatio ?? 1;
  const fontFamily = options.fontFamily ?? 'Neanes';

  canvas.width = Math.ceil(layout.width * dpr);
  canvas.height = Math.ceil(layout.height * dpr);
  canvas.style.width = `${layout.width}px`;
  canvas.style.height = `${layout.height}px`;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, layout.width, layout.height);

  for (const section of layout.sections) {
    drawSection(ctx, section, layout, fontFamily);
  }

  return canvas;
}

function drawSection(ctx, section, layout, fontFamily) {
  const { config } = layout;

  // Section header
  ctx.fillStyle = '#111827';
  ctx.font = '600 14px system-ui, -apple-system, "Segoe UI", sans-serif';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(section.label, config.marginX, section.top + 12);

  // Header underline
  ctx.strokeStyle = '#d1d5db';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(config.marginX, section.top + config.headerHeight - 6);
  ctx.lineTo(layout.width - config.marginX, section.top + config.headerHeight - 6);
  ctx.stroke();

  for (const cell of section.cells) drawCell(ctx, cell, config, fontFamily);
}

function drawCell(ctx, cell, config, fontFamily) {
  // Cell border (very subtle so the model can see grid structure)
  ctx.strokeStyle = '#e5e7eb';
  ctx.lineWidth = 1;
  ctx.strokeRect(cell.x + 0.5, cell.y + 0.5, cell.cellWidth - 1, cell.cellHeight - 1);

  // Glyph
  if (cell.character) {
    ctx.fillStyle = '#000000';
    ctx.font = `${config.glyphSize}px "${fontFamily}"`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const cx = cell.x + cell.cellWidth / 2;
    const cy = cell.y + config.glyphSize / 2 + 6;
    ctx.fillText(cell.character, cx, cy);
  }

  // Label (wrapped if long)
  ctx.fillStyle = '#1f2937';
  ctx.font = `${config.labelSize}px ui-monospace, "SF Mono", Menlo, Consolas, monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  const lines = wrapGlyphName(cell.glyphName, Math.floor(cell.cellWidth / (config.labelSize * 0.62)));
  const lineHeight = config.labelSize + 2;
  const labelBottom = cell.y + cell.cellHeight - 6;
  for (let i = 0; i < lines.length; i += 1) {
    const y = labelBottom - (lines.length - 1 - i) * lineHeight;
    ctx.fillText(lines[i], cell.x + cell.cellWidth / 2, y);
  }

  // Codepoint hint (faint, top-right of cell)
  ctx.fillStyle = '#9ca3af';
  ctx.font = `9px ui-monospace, "SF Mono", monospace`;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'top';
  ctx.fillText(cell.codepoint.replace('U+', ''), cell.x + cell.cellWidth - 4, cell.y + 4);
}
