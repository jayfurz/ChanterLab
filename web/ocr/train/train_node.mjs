// Node.js CNN training script. Runs without a browser using @napi-rs/canvas + tfjs-node.
import * as tf from '@tensorflow/tfjs';
import '@tensorflow/tfjs-backend-cpu';
await tf.ready();
import pkg from '@napi-rs/canvas';
import fs from 'fs';

const { createCanvas, GlobalFonts } = pkg;
const CELL = 48;

// ── Setup ─────────────────────────────────────────────────────────

const fontBuf = fs.readFileSync('/mnt/data/code/chanterlab-score-engine/web/fonts/neanes/Neanes.otf');
GlobalFonts.register(fontBuf, 'Neanes');
console.log('Font registered.');

// Build glyph list from the font map
import { NEANES_GLYPH_MAP } from '../atlas/font_glyph_map.js';

const GLYPHS = NEANES_GLYPH_MAP
  .map((g, i) => ({
    index: i,
    name: g.name,
    codepoint: g.codepoint,
    character: characterForCodepoint(g.codepoint),
  }))
  .filter(g => g.character);

function characterForCodepoint(cp) {
  const m = /^U\+([0-9A-F]{4,6})$/i.exec(cp?.trim() ?? '');
  return m ? String.fromCodePoint(parseInt(m[1], 16)) : undefined;
}

const NUM_CLASSES = GLYPHS.length;
console.log(`${NUM_CLASSES} classes.`);

// ── Data generation ──────────────────────────────────────────────

function renderGlyph(character, augment) {
  const size = CELL * 2;
  const c = createCanvas(size, size);
  const ctx = c.getContext('2d');

  const fontSize = augment ? CELL * (1.6 + (Math.random() - 0.5) * 0.3) : CELL * 1.6;

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, size, size);

  if (augment) {
    const angle = (Math.random() - 0.5) * 10 * Math.PI / 180;
    ctx.translate(size / 2, size / 2);
    ctx.rotate(angle);
    ctx.translate(-size / 2, -size / 2);
  }

  ctx.fillStyle = '#000000';
  ctx.font = `${fontSize}px "Neanes"`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(character, size / 2, size / 2);

  if (augment && Math.random() < 0.4) {
    ctx.filter = `blur(${0.5 + Math.random() * 2}px)`;
    ctx.drawImage(c, 0, 0);
    ctx.filter = 'none';
  }

  const img = ctx.getImageData(0, 0, size, size);
  return downsample(img.data, size, CELL, augment);
}

function downsample(rgba, srcSize, dstSize, augment) {
  const factor = srcSize / dstSize;
  const out = new Float32Array(dstSize * dstSize);
  for (let y = 0; y < dstSize; y++) {
    for (let x = 0; x < dstSize; x++) {
      const sx0 = Math.floor(x * factor);
      const sy0 = Math.floor(y * factor);
      const sx1 = Math.min(srcSize, Math.ceil((x + 1) * factor));
      const sy1 = Math.min(srcSize, Math.ceil((y + 1) * factor));
      let sum = 0, count = 0;
      for (let sy = sy0; sy < sy1; sy++) {
        for (let sx = sx0; sx < sx1; sx++) {
          const i = (sy * srcSize + sx) * 4;
          sum += rgba[i] * 0.299 + rgba[i + 1] * 0.587 + rgba[i + 2] * 0.114;
          count++;
        }
      }
      let v = count ? sum / count / 255 : 1;
      if (augment) v += (Math.random() - 0.5) * 0.03;
      out[y * dstSize + x] = Math.max(0, Math.min(1, v));
    }
  }
  return out;
}

function generateData(samplesPerClass) {
  const total = NUM_CLASSES * samplesPerClass;
  const xs = new Float32Array(total * CELL * CELL);
  const ys = new Float32Array(total * NUM_CLASSES);

  for (let ci = 0; ci < NUM_CLASSES; ci++) {
    const g = GLYPHS[ci];
    for (let s = 0; s < samplesPerClass; s++) {
      const data = renderGlyph(g.character, s > 0); // s=0 = clean
      const offset = (ci * samplesPerClass + s) * CELL * CELL;
      xs.set(data, offset);
      ys[(ci * samplesPerClass + s) * NUM_CLASSES + ci] = 1;
    }
    if (ci % 50 === 0) console.log(`  rendered ${ci}/${NUM_CLASSES} classes`);
  }
  return { xs, ys, total, cellSize: CELL, numClasses: NUM_CLASSES };
}

// ── Model ─────────────────────────────────────────────────────────

function createModel() {
  const model = tf.sequential();
  model.add(tf.layers.conv2d({
    inputShape: [CELL, CELL, 1],
    filters: 32, kernelSize: 3, padding: 'same',
    activation: 'relu', kernelInitializer: 'heNormal',
  }));
  model.add(tf.layers.maxPooling2d({ poolSize: 2, strides: 2 }));
  model.add(tf.layers.conv2d({
    filters: 64, kernelSize: 3, padding: 'same',
    activation: 'relu', kernelInitializer: 'heNormal',
  }));
  model.add(tf.layers.maxPooling2d({ poolSize: 2, strides: 2 }));
  model.add(tf.layers.conv2d({
    filters: 128, kernelSize: 3, padding: 'same',
    activation: 'relu', kernelInitializer: 'heNormal',
  }));
  model.add(tf.layers.globalAveragePooling2d({ dataFormat: 'channelsLast' }));
  model.add(tf.layers.dropout({ rate: 0.4 }));
  model.add(tf.layers.dense({
    units: NUM_CLASSES, activation: 'softmax',
    kernelInitializer: 'glorotNormal',
  }));
  model.compile({
    optimizer: tf.train.adam(0.001),
    loss: 'categoricalCrossentropy',
    metrics: ['accuracy'],
  });
  return model;
}

// ── Train ─────────────────────────────────────────────────────────

const SAMPLES_PER_CLASS = 10;
console.log(`\nGenerating ${NUM_CLASSES} × ${SAMPLES_PER_CLASS} = ${NUM_CLASSES * SAMPLES_PER_CLASS} samples...`);
const data = generateData(SAMPLES_PER_CLASS);
console.log(`Data ready: ${data.total} samples.`);

const model = createModel();
const xs = tf.tensor4d(data.xs, [data.total, CELL, CELL, 1]);
const ys = tf.tensor2d(data.ys, [data.total, data.numClasses]);

console.log('\nTraining...');
const start = Date.now();
await model.fit(xs, ys, {
  epochs: 30,
  batchSize: 32,
  validationSplit: 0.2,
  shuffle: true,
  callbacks: {
    onEpochEnd: (epoch, logs) => {
      console.log(`  epoch ${String(epoch + 1).padStart(2)}  acc=${(logs.acc*100).toFixed(1)}%  val_acc=${(logs.val_acc*100).toFixed(1)}%  loss=${logs.loss.toFixed(3)}`);
    },
  },
});
console.log(`Done in ${Math.round((Date.now() - start) / 1000)}s`);

xs.dispose();
ys.dispose();

// ── Save ──────────────────────────────────────────────────────────

const outDir = '/mnt/data/code/chanterlab-score-engine/web/ocr/train/chant_cnn_model';
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });
await model.save(`file://${outDir}`);

// Write class index
const classIndex = GLYPHS.map(g => ({ name: g.name, codepoint: g.codepoint }));
fs.writeFileSync(`${outDir}/classes.json`, JSON.stringify(classIndex));

console.log(`\nModel saved to ${outDir}`);
console.log('Files:', fs.readdirSync(outDir).join(', '));
