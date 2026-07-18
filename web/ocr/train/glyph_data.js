// Training data generator: renders Neanes glyphs to grayscale tensors with augmentation.
// Runs entirely in the browser using Canvas2D + the Neanes font.

import { NEANES_GLYPH_MAP } from '../atlas/font_glyph_map.js';

const CELL = 48;
const NUM_CLASSES = NEANES_GLYPH_MAP.length;

// Label map: glyphIndex → { name, codepoint, classIndex }
const LABEL_MAP = NEANES_GLYPH_MAP.map((g, i) => ({
  index: i,
  name: g.name,
  codepoint: g.codepoint,
  character: characterForCodepoint(g.codepoint),
})).filter(l => l.character);

const NAME_TO_INDEX = new Map(LABEL_MAP.map(l => [l.name, l.index]));
const INDEX_TO_NAME = LABEL_MAP.map(l => l.name);

export const CLASS_COUNT = LABEL_MAP.length;
export { LABEL_MAP, NAME_TO_INDEX, INDEX_TO_NAME };

export function characterForCodepoint(codepoint) {
  if (typeof codepoint !== 'string') return undefined;
  const match = /^U\+([0-9A-F]{4,6})$/i.exec(codepoint.trim());
  if (!match) return undefined;
  return String.fromCodePoint(Number.parseInt(match[1], 16));
}

// Render one glyph to a Float32Array grayscale tensor [CELL, CELL, 1].
// Returns { tensor, labelIndex } or null if the glyph can't be rendered.
export function renderGlyphSample(labelEntry, augment = true) {
  const canvas = new OffscreenCanvas(CELL * 2, CELL * 2);
  const ctx = canvas.getContext('2d');

  const fontSize = augment
    ? CELL * (1.6 + (Math.random() - 0.5) * 0.3)
    : CELL * 1.6;

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // Rotation
  if (augment) {
    const angle = (Math.random() - 0.5) * 10 * Math.PI / 180;
    ctx.translate(canvas.width / 2, canvas.height / 2);
    ctx.rotate(angle);
    ctx.translate(-canvas.width / 2, -canvas.height / 2);
  }

  ctx.fillStyle = '#000000';
  ctx.font = `${fontSize}px "Neanes"`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(labelEntry.character, canvas.width / 2, canvas.height / 2);

  // Blur
  if (augment && Math.random() < 0.4) {
    ctx.filter = `blur(${0.5 + Math.random() * 2}px)`;
    ctx.drawImage(canvas, 0, 0);
    ctx.filter = 'none';
  }

  // Extract grayscale, downsample to CELL×CELL
  const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const gray = downsampleGray(imageData.data, canvas.width, CELL);

  // Noise
  if (augment) {
    for (let i = 0; i < gray.length; i += 1) {
      const noise = (Math.random() - 0.5) * 8;
      gray[i] = Math.max(0, Math.min(255, gray[i] + noise));
    }
  }

  return { data: gray, label: labelEntry.index };
}

function downsampleGray(rgba, srcSize, dstSize) {
  const factor = srcSize / dstSize;
  const out = new Float32Array(dstSize * dstSize);
  for (let y = 0; y < dstSize; y += 1) {
    for (let x = 0; x < dstSize; x += 1) {
      const sx0 = Math.floor(x * factor);
      const sy0 = Math.floor(y * factor);
      const sx1 = Math.min(srcSize, Math.ceil((x + 1) * factor));
      const sy1 = Math.min(srcSize, Math.ceil((y + 1) * factor));
      let sum = 0, count = 0;
      for (let sy = sy0; sy < sy1; sy += 1) {
        for (let sx = sx0; sx < sx1; sx += 1) {
          const i = (sy * srcSize + sx) * 4;
          sum += rgba[i] * 0.299 + rgba[i + 1] * 0.587 + rgba[i + 2] * 0.114;
          count += 1;
        }
      }
      out[y * dstSize + x] = count ? (sum / count) / 255 : 1;
    }
  }
  return out;
}

// Generate a batch of training samples.
// samplesPerClass: how many augmented versions per glyph.
// Returns { xs: Float32Array[N*CELL*CELL], ys: Float32Array[N*CLASSES] }
export async function generateTrainingBatch(samplesPerClass = 8, onProgress) {
  const totalClasses = LABEL_MAP.length;
  const totalSamples = totalClasses * samplesPerClass;
  const xs = new Float32Array(totalSamples * CELL * CELL);
  const ys = new Float32Array(totalSamples * CLASS_COUNT);

  let done = 0;
  for (let ci = 0; ci < totalClasses; ci += 1) {
    const label = LABEL_MAP[ci];
    for (let s = 0; s < samplesPerClass; s += 1) {
      const sample = renderGlyphSample(label, s > 0); // first sample is clean, rest augmented
      if (!sample) continue;
      const offset = (ci * samplesPerClass + s) * CELL * CELL;
      xs.set(sample.data, offset);
      ys[ci * samplesPerClass + s + ci * (CLASS_COUNT - 1)] = 1; // one-hot — FIX
      done += 1;
    }
    if (onProgress && ci % 20 === 0) onProgress(done, totalSamples);
  }

  // Fix one-hot encoding properly
  for (let ci = 0; ci < totalClasses; ci += 1) {
    for (let s = 0; s < samplesPerClass; s += 1) {
      const row = ci * samplesPerClass + s;
      const base = row * CLASS_COUNT;
      ys.fill(0, base, base + CLASS_COUNT);
      ys[base + ci] = 1;
    }
  }

  if (onProgress) onProgress(totalSamples, totalSamples);
  return { xs, ys, totalSamples, cellSize: CELL, numClasses: CLASS_COUNT };
}
