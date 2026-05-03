// CNN-based recognizer for Byzantine chant notation.
// Loads a TFJS model trained via /ocr/train.html and classifies glyph crops.
// Same output shape as recognize.js → drops into the existing import pipeline.

import { binarizeGray, cropGrayBuffer } from './buffers.js';
import {
  findConnectedComponents,
  groupComponentsIntoColumns,
} from './segment.js';
import { bboxCenter } from './buffers.js';
import { INDEX_TO_NAME, NAME_TO_INDEX, CLASS_COUNT } from '../train/glyph_data.js';

const CELL = 48;

export async function loadModelFromFiles(modelJson, weightBin) {
  const { loadGraphModel, loadLayersModel } = await import('@tensorflow/tfjs');
  return loadLayersModel(tf.io.browserFiles([modelJson, weightBin]));
}

export async function loadModelFromIndexedDB(key = 'chant-glyph-cnn') {
  const { loadLayersModel } = await import('@tensorflow/tfjs');
  return loadLayersModel(`indexeddb://${key}`);
}

// Main entry point: page image → tokens (same interface as recognize.js)
export function recognizePageCNN(grayBuffer, model, options = {}) {
  const binary = binarizeGray(grayBuffer, options.binaryThreshold ?? 'otsu');
  const components = findConnectedComponents(binary, { minPixels: options.minComponentPixels ?? 6 });
  const { columns } = groupComponentsIntoColumns(components);
  const linesOfColumns = partitionColumnsIntoLines(columns, components);

  const tokens = [];
  let lineIndex = 0;
  for (const lineColumns of linesOfColumns) {
    for (const column of lineColumns) {
      const componentIndices = [column.mainIndex, ...(column.aboveIndices ?? []), ...(column.belowIndices ?? [])];
      for (const componentIndex of componentIndices) {
        const component = components[componentIndex];
        if (!component) continue;
        const crop = cropGrayBuffer(grayBuffer, padBBox(component.bbox, 2, grayBuffer));
        const fitted = fitToCell(crop, CELL);
        const topK = classifyCropTFJS(model, fitted, options.topK ?? 5);
        if (!topK.length) continue;
        const [best, ...alternates] = topK;
        tokens.push({
          glyphName: best.glyphName,
          confidence: best.confidence,
          source: 'ocr',
          region: { bbox: { ...component.bbox }, line: lineIndex, role: 'neume' },
          ...(alternates.length ? {
            alternates: alternates.map(a => ({ glyphName: a.glyphName, confidence: a.confidence })),
          } : {}),
        });
      }
    }
    lineIndex += 1;
  }

  return { tokens, components, lineCount: linesOfColumns.length };
}

// TFJS classify a single CELL×CELL Float32Array (values 0-1, lighter=higher).
function classifyCropTFJS(model, grayData, topK = 5) {
  const tf = requireTensorFlow();
  const input = tf.tensor4d(grayData, [1, CELL, CELL, 1]);
  const predictions = model.predict(input);
  const values = predictions.dataSync();
  input.dispose();
  predictions.dispose();

  return Array.from(values)
    .map((conf, i) => ({
      glyphName: INDEX_TO_NAME[i] ?? `class_${i}`,
      confidence: conf,
    }))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, topK);
}

function fitToCell(buffer, cellSize) {
  const data = new Float32Array(cellSize * cellSize);
  // Center the crop in the cell with aspect-ratio preservation
  const scale = Math.min(cellSize / buffer.width, cellSize / buffer.height);
  const sw = Math.round(buffer.width * scale);
  const sh = Math.round(buffer.height * scale);
  const ox = Math.floor((cellSize - sw) / 2);
  const oy = Math.floor((cellSize - sh) / 2);

  // Fill with white (1.0)
  data.fill(1);

  for (let y = 0; y < sh; y++) {
    for (let x = 0; x < sw; x++) {
      const sx = Math.floor(x / scale);
      const sy = Math.floor(y / scale);
      if (sx < buffer.width && sy < buffer.height) {
        data[(oy + y) * cellSize + (ox + x)] = 1 - buffer.data[sy * buffer.width + sx] / 255;
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
  let currentMaxBottom = -Infinity;
  for (const entry of annotated) {
    if (current.length === 0 || entry.mainBottom - currentMaxBottom <= lineGap) {
      current.push(entry.column);
      currentMaxBottom = Math.max(currentMaxBottom, entry.mainBottom);
    } else {
      lines.push(current);
      current = [entry.column];
      currentMaxBottom = entry.mainBottom;
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

// Lazy-load TFJS — avoids bundling it until the CNN recognizer is selected.
let _tf = undefined;
function requireTensorFlow() {
  if (!_tf) {
    throw new Error('TensorFlow.js must be imported before calling CNN recognizer. Import @tensorflow/tfjs first.');
  }
  return _tf;
}
export function setTensorFlow(tf) { _tf = tf; }
