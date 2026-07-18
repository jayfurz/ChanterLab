import test from 'node:test';
import assert from 'node:assert/strict';

import { createGrayBuffer } from '../../ocr/pipeline/buffers.js';
import { createTemplate } from '../../ocr/pipeline/classify.js';
import { recognizePage } from '../../ocr/pipeline/recognize.js';
import { semanticTokensFromGlyphs } from '../glyph_import.js';
import { resolveGlyphGroups } from '../glyph_group_resolver.js';

// Visually distinct stamp shapes that map to real glyph names.
// They never need to look like Neanes glyphs — only that NCC can tell them apart.
const STAMPS = {
  ison: drawCircle,            // filled circle
  oligon: drawHorizontalBar,   // top-heavy bar
  apostrofos: drawDownStroke,  // diagonal down-right
  gorgonAbove: drawXShape,     // small X, used as modifier
  apli: drawSingleDot,         // small dot, used below the anchor
};

function drawCircle(buffer, cx, cy, size) {
  const radius = size / 2 - 1;
  for (let dy = -radius; dy <= radius; dy += 1) {
    for (let dx = -radius; dx <= radius; dx += 1) {
      if (dx * dx + dy * dy <= radius * radius) {
        const x = cx + dx;
        const y = cy + dy;
        if (x >= 0 && x < buffer.width && y >= 0 && y < buffer.height) {
          buffer.data[y * buffer.width + x] = 0;
        }
      }
    }
  }
}

function drawHorizontalBar(buffer, cx, cy, size) {
  const half = size / 2 - 1;
  for (let dy = -1; dy <= 1; dy += 1) {
    for (let dx = -half; dx <= half; dx += 1) {
      const x = cx + dx;
      const y = cy + dy;
      if (x >= 0 && x < buffer.width && y >= 0 && y < buffer.height) {
        buffer.data[y * buffer.width + x] = 0;
      }
    }
  }
}

function drawDownStroke(buffer, cx, cy, size) {
  const half = size / 2 - 1;
  for (let i = -half; i <= half; i += 1) {
    const x = cx + i;
    const y = cy + i;
    if (x >= 0 && x < buffer.width && y >= 0 && y < buffer.height) {
      buffer.data[y * buffer.width + x] = 0;
      if (x + 1 < buffer.width) buffer.data[y * buffer.width + (x + 1)] = 0;
    }
  }
}

function drawXShape(buffer, cx, cy, size) {
  const half = size / 2 - 1;
  for (let i = -half; i <= half; i += 1) {
    const points = [
      [cx + i, cy + i],
      [cx + i, cy - i],
    ];
    for (const [x, y] of points) {
      if (x >= 0 && x < buffer.width && y >= 0 && y < buffer.height) {
        buffer.data[y * buffer.width + x] = 0;
      }
    }
  }
}

function drawSingleDot(buffer, cx, cy) {
  for (let dy = -1; dy <= 1; dy += 1) {
    for (let dx = -1; dx <= 1; dx += 1) {
      const x = cx + dx;
      const y = cy + dy;
      if (x >= 0 && x < buffer.width && y >= 0 && y < buffer.height) {
        buffer.data[y * buffer.width + x] = 0;
      }
    }
  }
}

function buildSyntheticTemplates(cellSize = 24) {
  return Object.entries(STAMPS).map(([glyphName, draw]) => {
    const buffer = createGrayBuffer(cellSize, cellSize, 255);
    const cx = cellSize / 2 | 0;
    const cy = cellSize / 2 | 0;
    if (glyphName === 'apli') draw(buffer, cx, cy);
    else draw(buffer, cx, cy, cellSize - 4);
    return createTemplate({ glyphName, codepoint: glyphMockCodepoint(glyphName), buffer });
  });
}

function glyphMockCodepoint(glyphName) {
  const codepoints = { ison: 'U+E000', oligon: 'U+E001', apostrofos: 'U+E021', gorgonAbove: 'U+E0F0', apli: 'U+E0D2' };
  return codepoints[glyphName];
}

test('recognize -> resolver pipeline round-trips a synthetic single-line page', () => {
  const cellSize = 24;
  const templates = buildSyntheticTemplates(cellSize);
  const buffer = createGrayBuffer(400, 80, 255);

  // Three glyph columns laid out with margin and space:
  // [0] ison at x=40   [1] oligon at x=120   [2] apostrofos+gorgonAbove at x=200
  drawCircle(buffer, 40, 40, cellSize - 4);
  drawHorizontalBar(buffer, 120, 40, cellSize - 4);
  drawDownStroke(buffer, 200, 40, cellSize - 4);
  drawXShape(buffer, 200, 12, cellSize - 4);

  const result = recognizePage(buffer, templates, { minComponentPixels: 4 });
  const names = result.tokens.map(token => token.glyphName);
  assert.ok(names.includes('ison'), `expected ison, got ${names.join(', ')}`);
  assert.ok(names.includes('oligon'));
  assert.ok(names.includes('apostrofos'));
  assert.ok(names.includes('gorgonAbove'));

  for (const token of result.tokens) {
    assert.ok(token.region?.bbox, 'every recognized token has a region.bbox');
    assert.ok(typeof token.confidence === 'number', 'every token has a confidence');
    assert.equal(token.source, 'ocr');
  }

  // Feed straight into the existing semantic + resolver path.
  const semanticTokens = semanticTokensFromGlyphs(result.tokens);
  const groups = resolveGlyphGroups(semanticTokens);
  const namesByGroup = groups.map(group =>
    group.map(token => token.source[0].glyphName).filter(Boolean).sort()
  );

  assert.deepEqual(
    namesByGroup,
    [['ison'], ['oligon'], ['apostrofos', 'gorgonAbove']]
  );
});
