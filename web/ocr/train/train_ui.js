import * as tf from '@tensorflow/tfjs';
import { generateTrainingBatch, CLASS_COUNT, INDEX_TO_NAME, LABEL_MAP } from './glyph_data.js';
import { createGlyphClassifier, compileModel, trainModel, classifyCrop } from './model.js';
import { ensureFontReady } from '../synth/render_browser.js';

const $ = id => document.getElementById(id);

const state = {
  model: undefined,
  batch: undefined,
  modelArtifacts: undefined,
};

async function generateData() {
  const samplesPerClass = Number($('samplesPerClass').value) || 8;
  $('genBtn').disabled = true;
  $('genStatus').textContent = 'Rendering glyphs…';

  const batch = await generateTrainingBatch(samplesPerClass, (done, total) => {
    $('genStatus').textContent = `Rendered ${done}/${total} samples`;
  });

  state.batch = batch;
  $('genStatus').textContent = `${batch.totalSamples} samples · ${batch.numClasses} classes · ${batch.cellSize}×${batch.cellSize}px`;
  $('genBtn').disabled = false;
  $('trainBtn').disabled = false;
}

async function train() {
  if (!state.batch) return;

  $('trainBtn').disabled = true;
  $('trainStatus').textContent = 'Training…';
  $('trainProgress').value = 0;

  const model = createGlyphClassifier(state.batch.numClasses);
  compileModel(model);

  const epochs = Number($('epochs').value) || 30;
  const batchSize = Number($('batchSize').value) || 32;
  const history = await trainModel(model, state.batch, {
    epochs,
    batchSize,
    onEpoch: (epoch, logs) => {
      const pct = ((epoch + 1) / epochs * 100);
      $('trainProgress').value = pct;
      $('trainStatus').textContent =
        `Epoch ${epoch + 1}/${epochs} · acc=${(logs.acc * 100).toFixed(1)}% · val_acc=${(logs.val_acc * 100).toFixed(1)}% · loss=${logs.loss.toFixed(3)}`;
    },
  });

  state.model = model;

  const finalAcc = history.history.val_acc[history.history.val_acc.length - 1];
  $('trainStatus').textContent =
    `Done. Val accuracy: ${(finalAcc * 100).toFixed(1)}% · ${state.batch.totalSamples} samples · ${epochs} epochs`;
  $('trainBtn').disabled = false;
  $('downloadBtn').disabled = false;
  $('testBtn').disabled = false;
}

async function downloadModel() {
  if (!state.model) return;
  $('downloadBtn').disabled = true;
  $('downloadBtn').textContent = 'Saving…';

  await state.model.save('downloads://chant-glyph-cnn');
  $('downloadBtn').textContent = 'Download Model';
  $('downloadBtn').disabled = false;
}

async function testModel() {
  if (!state.model) return;
  const cellSize = 48;
  const canvas = new OffscreenCanvas(cellSize * 2, cellSize * 2);
  const ctx = canvas.getContext('2d');

  // Pick 10 random classes and classify one sample each
  const indices = tf.util.createShuffledIndices(Math.min(CLASS_COUNT, 10)).slice(0, 5);
  const results = [];

  for (const ci of indices) {
    const label = LABEL_MAP[ci];
    if (!label?.character) continue;

    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000000';
    ctx.font = `${cellSize * 1.6}px "Neanes"`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label.character, canvas.width / 2, canvas.height / 2);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const gray = new Float32Array(cellSize * cellSize);
    const factor = 2;
    for (let y = 0; y < cellSize; y++) {
      for (let x = 0; x < cellSize; x++) {
        const sx = Math.floor(x * factor);
        const sy = Math.floor(y * factor);
        const i = (sy * canvas.width + sx) * 4;
        gray[y * cellSize + x] = (imageData.data[i] * 0.299 + imageData.data[i + 1] * 0.587 + imageData.data[i + 2] * 0.114) / 255;
      }
    }

    const top = classifyCrop(state.model, gray, INDEX_TO_NAME, 3);
    results.push({ expected: label.name, top });
  }

  const lines = results.map(r =>
    `${r.expected}\n  → ${r.top.map(t => `${t.glyphName} ${(t.confidence * 100).toFixed(0)}%`).join(' · ')}`
  );
  $('testResults').textContent = lines.join('\n\n');
}

window.addEventListener('DOMContentLoaded', async () => {
  try {
    await ensureFontReady('Neanes', 48);
    $('fontStatus').textContent = 'Neanes font ready.';
  } catch {
    // Headless fallback: just wait for the font to be available
    await new Promise(r => setTimeout(r, 2000));
    $('fontStatus').textContent = 'Neanes font ready.';
  }

  $('genBtn').addEventListener('click', generateData);
  $('trainBtn').addEventListener('click', train);
  $('downloadBtn').addEventListener('click', downloadModel);
  $('testBtn').addEventListener('click', testModel);
});
