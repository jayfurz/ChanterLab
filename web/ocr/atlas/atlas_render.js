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
  ctx.save();
  ctx.beginPath();
  ctx.rect(cell.x, cell.y, cell.cellWidth, cell.cellHeight);
  ctx.clip();

  // Cell border
  ctx.strokeStyle = '#e5e7eb';
  ctx.lineWidth = 1;
  ctx.strokeRect(cell.x + 0.5, cell.y + 0.5, cell.cellWidth - 1, cell.cellHeight - 1);

  const glyphZone = cell.y + Math.round(cell.cellHeight * 0.62);
  const labelZone = cell.y + Math.round(cell.cellHeight * 0.70);

  // Thin separator between glyph and label zone
  ctx.strokeStyle = '#f3f4f6';
  ctx.beginPath();
  ctx.moveTo(cell.x + 8, labelZone);
  ctx.lineTo(cell.x + cell.cellWidth - 8, labelZone);
  ctx.stroke();

  // Glyph — anchored so it stays within the glyph zone
  if (cell.character) {
    ctx.fillStyle = '#000000';
    ctx.font = `${config.glyphSize}px "${fontFamily}"`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    const cx = cell.x + cell.cellWidth / 2;
    const glyphBaseline = glyphZone - Math.round(config.glyphSize * 0.12);
    ctx.fillText(cell.character, cx, glyphBaseline);
  }

  // Label — wrapped, clipped to label zone
  ctx.fillStyle = '#1f2937';
  ctx.font = `${config.labelSize}px ui-monospace, "SF Mono", Menlo, Consolas, monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const maxChars = Math.floor(cell.cellWidth / (config.labelSize * 0.62));
  const lines = wrapGlyphName(cell.glyphName, maxChars);
  const lineHeight = config.labelSize + 2;
  const maxLabelLines = Math.floor((cell.y + cell.cellHeight - labelZone - 4) / lineHeight);
  const visibleLines = lines.slice(0, maxLabelLines);
  const labelY0 = labelZone + 4;
  for (let i = 0; i < visibleLines.length; i += 1) {
    ctx.fillText(visibleLines[i], cell.x + cell.cellWidth / 2, labelY0 + i * lineHeight);
  }

  // Codepoint hint (top-right of cell)
  ctx.fillStyle = '#9ca3af';
  ctx.font = '9px ui-monospace, "SF Mono", monospace';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'top';
  ctx.fillText(cell.codepoint.replace('U+', ''), cell.x + cell.cellWidth - 4, cell.y + 4);

  ctx.restore();
}
