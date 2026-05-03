// Normalized cross-correlation classifier over a set of glyph templates.
// Templates and candidates are grayscale buffers of identical size (cellSize×cellSize),
// 0 = ink, 255 = background.

import { resampleGrayBuffer, cropGrayBuffer } from './buffers.js';

export function createTemplate({ glyphName, codepoint, buffer }) {
  const cellSize = buffer.width;
  if (buffer.height !== cellSize) {
    throw new Error(`Template ${glyphName} must be square, got ${buffer.width}×${buffer.height}`);
  }
  const inverted = invertForMatching(buffer.data);
  const stats = computeStats(inverted);
  return {
    glyphName,
    codepoint,
    cellSize,
    data: inverted,
    mean: stats.mean,
    norm: stats.norm,
    inkPixels: stats.inkPixels,
  };
}

export function classifyCandidate(candidateBuffer, templates, options = {}) {
  if (!templates.length) return [];
  const cellSize = templates[0].cellSize;
  const fitted = candidateBuffer.width === cellSize && candidateBuffer.height === cellSize
    ? candidateBuffer
    : resampleGrayBuffer(centerOnSquare(candidateBuffer), cellSize, cellSize);
  const inverted = invertForMatching(fitted.data);
  const candidateStats = computeStats(inverted);
  if (candidateStats.norm <= 0) return [];

  const scores = [];
  for (const template of templates) {
    const score = nccScore(inverted, candidateStats, template);
    if (Number.isFinite(score)) scores.push({ template, score });
  }

  scores.sort((a, b) => b.score - a.score);
  const topK = options.topK ?? 5;
  return scores.slice(0, topK).map(({ template, score }) => ({
    glyphName: template.glyphName,
    codepoint: template.codepoint,
    confidence: clamp01((score + 1) / 2),
    rawScore: score,
  }));
}

function nccScore(candidateData, candidateStats, template) {
  let dot = 0;
  for (let i = 0; i < candidateData.length; i += 1) {
    dot += (candidateData[i] - candidateStats.mean) * (template.data[i] - template.mean);
  }
  const denom = candidateStats.norm * template.norm;
  if (denom <= 0) return 0;
  return dot / denom;
}

function computeStats(inverted) {
  let sum = 0;
  let inkPixels = 0;
  for (let i = 0; i < inverted.length; i += 1) {
    sum += inverted[i];
    if (inverted[i] > 32) inkPixels += 1;
  }
  const mean = sum / inverted.length;
  let sumSq = 0;
  for (let i = 0; i < inverted.length; i += 1) {
    const d = inverted[i] - mean;
    sumSq += d * d;
  }
  return { mean, norm: Math.sqrt(sumSq), inkPixels };
}

function invertForMatching(grayData) {
  // For NCC we want ink to be HIGH and background LOW; input has ink=0, bg=255.
  const out = new Float32Array(grayData.length);
  for (let i = 0; i < grayData.length; i += 1) {
    out[i] = 255 - grayData[i];
  }
  return out;
}

function centerOnSquare(buffer) {
  const side = Math.max(buffer.width, buffer.height);
  const offsetX = Math.floor((side - buffer.width) / 2);
  const offsetY = Math.floor((side - buffer.height) / 2);
  const data = new Uint8ClampedArray(side * side).fill(255);
  for (let y = 0; y < buffer.height; y += 1) {
    for (let x = 0; x < buffer.width; x += 1) {
      data[(y + offsetY) * side + (x + offsetX)] = buffer.data[y * buffer.width + x];
    }
  }
  return { width: side, height: side, data };
}

function clamp01(value) {
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

export function cropAndClassify(buffer, bbox, templates, options) {
  const crop = cropGrayBuffer(buffer, bbox);
  return classifyCandidate(crop, templates, options);
}
