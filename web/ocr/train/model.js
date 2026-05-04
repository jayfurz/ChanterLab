// Small CNN for Byzantine neume glyph classification.
// Input: 48×48 grayscale. Output: softmax over ~200 glyph classes.

import * as tf from '@tensorflow/tfjs';

const CELL = 48;

export function createGlyphClassifier(numClasses) {
  const model = tf.sequential();

  model.add(tf.layers.conv2d({
    inputShape: [CELL, CELL, 1],
    filters: 32,
    kernelSize: 3,
    padding: 'same',
    activation: 'relu',
    kernelInitializer: 'heNormal',
  }));
  model.add(tf.layers.maxPooling2d({ poolSize: 2, strides: 2 }));

  model.add(tf.layers.conv2d({
    filters: 64,
    kernelSize: 3,
    padding: 'same',
    activation: 'relu',
    kernelInitializer: 'heNormal',
  }));
  model.add(tf.layers.maxPooling2d({ poolSize: 2, strides: 2 }));

  model.add(tf.layers.conv2d({
    filters: 128,
    kernelSize: 3,
    padding: 'same',
    activation: 'relu',
    kernelInitializer: 'heNormal',
  }));
  model.add(tf.layers.globalAveragePooling2d({ dataFormat: 'channelsLast' }));

  model.add(tf.layers.dropout({ rate: 0.4 }));
  model.add(tf.layers.dense({
    units: numClasses,
    activation: 'softmax',
    kernelInitializer: 'glorotNormal',
  }));

  return model;
}

export function compileModel(model) {
  model.compile({
    optimizer: tf.train.adam(0.001),
    loss: 'categoricalCrossentropy',
    metrics: ['accuracy'],
  });
}

// Convert { xs: Float32Array, ys: Float32Array } to tf.Tensors.
export function tensorsFromBatch(batch) {
  const xs = tf.tensor4d(batch.xs, [batch.totalSamples, CELL, CELL, 1]);
  const ys = tf.tensor2d(batch.ys, [batch.totalSamples, batch.numClasses]);
  return { xs, ys };
}

// Train the model and return final accuracy.
export async function trainModel(model, batch, options = {}) {
  const { xs, ys } = tensorsFromBatch(batch);
  const epochs = options.epochs ?? 30;
  const valSplit = options.validationSplit ?? 0.2;
  const batchSize = options.batchSize ?? 32;

  const history = await model.fit(xs, ys, {
    epochs,
    batchSize,
    validationSplit: valSplit,
    shuffle: true,
    callbacks: options.onEpoch ? [{
      onEpochEnd: (epoch, logs) => options.onEpoch(epoch, logs),
    }] : undefined,
  });

  xs.dispose();
  ys.dispose();

  return history;
}

// Classify a single 48×48 grayscale crop (Float32Array[CELL*CELL], values 0-1).
// Returns [{ glyphName, classIndex, confidence }] sorted by confidence.
export function classifyCrop(model, grayData, indexToName, topK = 5) {
  const input = tf.tensor4d(grayData, [1, CELL, CELL, 1]);
  const predictions = model.predict(input);
  const values = predictions.dataSync();
  input.dispose();
  predictions.dispose();

  return Array.from(values)
    .map((conf, i) => ({ glyphName: indexToName[i] ?? `class_${i}`, classIndex: i, confidence: conf }))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, topK);
}

export const INPUT_SIZE = CELL;
