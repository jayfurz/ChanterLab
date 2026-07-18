// CNN-based recognizer using hand-rolled JS forward pass.
// Loads weights from the PyTorch-exported JSON. Same output shape as recognize.js.

import { binarizeGray, cropGrayBuffer, bboxCenter } from './buffers.js';
import { findConnectedComponents, groupComponentsIntoColumns } from './segment.js';
import { loadWeights, classify, isReady, getMeta } from './cnn_forward.js';

const CELL = 48;

// Main entry point — same interface as recognize.js
export function recognizePageCNN(grayBuffer, options = {}) {
  if (!isReady()) throw new Error('CNN weights not loaded. Call initCNN(url) first.');

  const binary = binarizeGray(grayBuffer, options.binaryThreshold ?? 'otsu');
  const components = findConnectedComponents(binary, { minPixels: options.minComponentPixels ?? 6 });
  const { columns } = groupComponentsIntoColumns(components);
  const linesOfColumns = partitionColumnsIntoLines(columns, components);

  const tokens = [];
  let lineIndex = 0;
  for (const lineColumns of linesOfColumns) {
    for (const column of lineColumns) {
      for (const idx of componentIndices(column)) {
        const component = components[idx];
        if (!component) continue;
        const crop = cropGrayBuffer(grayBuffer, padBBox(component.bbox, 2, grayBuffer));
        const fitted = fitToCell(crop);
        const topK = classify(fitted, options.topK ?? 5);
        if (!topK.length) continue;
        const [best, ...alternates] = topK;
        tokens.push({
          glyphName: best.glyphName,
          codepoint: best.codepoint,
          confidence: best.confidence,
          source: 'ocr',
          region: { bbox: { ...component.bbox }, line: lineIndex, role: 'neume' },
          ...(alternates.length ? {
            alternates: alternates.map(a => ({ glyphName: a.glyphName, codepoint: a.codepoint, confidence: a.confidence })),
          } : {}),
        });
      }
    }
    lineIndex += 1;
  }
  return { tokens, components, lineCount: linesOfColumns.length };
}

export async function initCNN(url = '../train/chant_cnn_model/weights.json') {
  return loadWeights(url);
}

function componentIndices(column) {
  return [column.mainIndex, ...(column.aboveIndices ?? []), ...(column.belowIndices ?? [])]
    .filter(i => Number.isInteger(i));
}

function fitToCell(buffer) {
  const data = new Float32Array(CELL * CELL);
  data.fill(1); // white

  const scale = Math.min(CELL / buffer.width, CELL / buffer.height);
  const sw = Math.round(buffer.width * scale);
  const sh = Math.round(buffer.height * scale);
  const ox = Math.floor((CELL - sw) / 2);
  const oy = Math.floor((CELL - sh) / 2);

  for (let y = 0; y < sh; y++) {
    for (let x = 0; x < sw; x++) {
      const sx = Math.floor(x / scale);
      const sy = Math.floor(y / scale);
      if (sx < buffer.width && sy < buffer.height) {
        data[(oy + y) * CELL + (ox + x)] = 1 - buffer.data[sy * buffer.width + sx] / 255;
      }
    }
  }
  return data;
}

function partitionColumnsIntoLines(columns, components) {
  if (!columns.length) return [];
  const annotated = columns.map(col => {
    const main = components[col.mainIndex];
    return {
      column: col,
      mainBottom: main ? main.bbox.y + main.bbox.h : bboxCenter(col.bbox).y,
      mainHeight: main ? main.bbox.h : col.bbox.h,
    };
  });
  annotated.sort((a, b) => a.mainBottom - b.mainBottom);
  const heights = annotated.map(a => a.mainHeight);
  const medianHeight = heights.slice().sort((a, b) => a - b)[heights.length >> 1] ?? 1;
  const lineGap = medianHeight * 1.6;

  const lines = [];
  let current = [];
  let maxBottom = -Infinity;
  for (const entry of annotated) {
    if (!current.length || entry.mainBottom - maxBottom <= lineGap) {
      current.push(entry.column);
      maxBottom = Math.max(maxBottom, entry.mainBottom);
    } else {
      lines.push(current);
      current = [entry.column];
      maxBottom = entry.mainBottom;
    }
  }
  if (current.length) lines.push(current);
  for (const line of lines) line.sort((a, b) => bboxCenter(a.bbox).x - bboxCenter(b.bbox).x);
  return lines;
}

function padBBox(bbox, padding, buffer) {
  const x = Math.max(0, bbox.x - padding);
  const y = Math.max(0, bbox.y - padding);
  const right = Math.min(buffer.width, bbox.x + bbox.w + padding);
  const bottom = Math.min(buffer.height, bbox.y + bbox.h + padding);
  return { x, y, w: right - x, h: bottom - y };
}
