import test from 'node:test';
import assert from 'node:assert/strict';

import { createTemplate, classifyCandidate } from '../../ocr/pipeline/classify.js';
import { createGrayBuffer } from '../../ocr/pipeline/buffers.js';

function paintHorizontalBar(buffer, y, h) {
  for (let row = 0; row < h; row += 1) {
    for (let col = 0; col < buffer.width; col += 1) {
      buffer.data[(y + row) * buffer.width + col] = 0;
    }
  }
}

function paintVerticalBar(buffer, x, w) {
  for (let col = 0; col < w; col += 1) {
    for (let row = 0; row < buffer.height; row += 1) {
      buffer.data[row * buffer.width + (x + col)] = 0;
    }
  }
}

function makeTemplates() {
  const horizontal = createGrayBuffer(16, 16, 255);
  paintHorizontalBar(horizontal, 7, 2);
  const vertical = createGrayBuffer(16, 16, 255);
  paintVerticalBar(vertical, 7, 2);
  return [
    createTemplate({ glyphName: 'horizontal-bar', codepoint: 'U+EE00', buffer: horizontal }),
    createTemplate({ glyphName: 'vertical-bar', codepoint: 'U+EE01', buffer: vertical }),
  ];
}

test('NCC classifier ranks the matching shape highest', () => {
  const templates = makeTemplates();
  const candidate = createGrayBuffer(16, 16, 255);
  paintHorizontalBar(candidate, 7, 2);
  const matches = classifyCandidate(candidate, templates);
  assert.equal(matches.length, 2);
  assert.equal(matches[0].glyphName, 'horizontal-bar');
  assert.ok(matches[0].confidence > matches[1].confidence);
  assert.ok(matches[0].confidence > 0.9, `expected > 0.9, got ${matches[0].confidence}`);
});

test('NCC classifier resamples differently sized candidates to match template size', () => {
  const templates = makeTemplates();
  const candidate = createGrayBuffer(32, 32, 255);
  paintHorizontalBar(candidate, 14, 4);
  const matches = classifyCandidate(candidate, templates);
  assert.equal(matches[0].glyphName, 'horizontal-bar');
});

test('NCC classifier returns at most topK matches', () => {
  const templates = makeTemplates();
  const candidate = createGrayBuffer(16, 16, 255);
  paintHorizontalBar(candidate, 7, 2);
  const matches = classifyCandidate(candidate, templates, { topK: 1 });
  assert.equal(matches.length, 1);
});
