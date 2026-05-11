import test from 'node:test';
import assert from 'node:assert/strict';

import {
  findConnectedComponents,
  groupComponentsIntoColumns,
  partitionComponentsIntoLines,
} from '../../ocr/pipeline/segment.js';
import { createGrayBuffer } from '../../ocr/pipeline/buffers.js';

function paintRect(buffer, x, y, w, h, color = 0) {
  for (let row = 0; row < h; row += 1) {
    for (let col = 0; col < w; col += 1) {
      const idx = (y + row) * buffer.width + (x + col);
      buffer.data[idx] = color;
    }
  }
}

test('connected components finds isolated rectangles with their bboxes', () => {
  const buffer = createGrayBuffer(40, 20, 255);
  paintRect(buffer, 2, 4, 6, 10);
  paintRect(buffer, 20, 4, 6, 10);
  const components = findConnectedComponents(buffer);
  assert.equal(components.length, 2);
  const sorted = components.sort((a, b) => a.bbox.x - b.bbox.x);
  assert.deepEqual(sorted[0].bbox, { x: 2, y: 4, w: 6, h: 10 });
  assert.deepEqual(sorted[1].bbox, { x: 20, y: 4, w: 6, h: 10 });
});

test('connected components ignores tiny noise components', () => {
  const buffer = createGrayBuffer(20, 20, 255);
  paintRect(buffer, 1, 1, 1, 1);
  paintRect(buffer, 5, 5, 6, 6);
  const components = findConnectedComponents(buffer, { minPixels: 4 });
  assert.equal(components.length, 1);
  assert.equal(components[0].pixelCount, 36);
});

test('groupComponentsIntoColumns merges vertically stacked components into one column', () => {
  const components = [
    { bbox: { x: 10, y: 0, w: 8, h: 6 }, pixelCount: 30 },     // above
    { bbox: { x: 10, y: 12, w: 10, h: 12 }, pixelCount: 100 }, // main
    { bbox: { x: 11, y: 28, w: 8, h: 6 }, pixelCount: 30 },    // below
    { bbox: { x: 50, y: 12, w: 10, h: 12 }, pixelCount: 110 }, // separate column
  ];
  const { columns } = groupComponentsIntoColumns(components);
  assert.equal(columns.length, 2);
  const left = columns[0];
  assert.equal(left.componentIndices.length, 3);
  assert.equal(left.mainIndex, 1, 'largest pixel count is the main glyph');
  assert.deepEqual(left.aboveIndices, [0]);
  assert.deepEqual(left.belowIndices, [2]);
});

test('partitionComponentsIntoLines splits components by y-banding', () => {
  const components = [
    { bbox: { x: 10, y: 0, w: 12, h: 12 }, pixelCount: 100 },
    { bbox: { x: 30, y: 1, w: 12, h: 12 }, pixelCount: 100 },
    { bbox: { x: 10, y: 60, w: 12, h: 12 }, pixelCount: 100 },
    { bbox: { x: 30, y: 61, w: 12, h: 12 }, pixelCount: 100 },
  ];
  const lines = partitionComponentsIntoLines(components);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].length, 2);
  assert.equal(lines[1].length, 2);
});
