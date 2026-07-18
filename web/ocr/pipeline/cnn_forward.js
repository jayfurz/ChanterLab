// Hand-rolled CNN forward pass in pure JavaScript. No TFJS, no ONNX runtime.
// Loads weights from the PyTorch-exported JSON and classifies 48×48 grayscale crops.
// Architecture: Conv→ReLU→MaxPool→Conv→ReLU→MaxPool→Conv→ReLU→MaxPool→Conv→ReLU→GAP→Linear→Softmax

let weights = null;
let meta = null;
let ready = false;

export async function loadWeights(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Failed to load weights: ${response.status}`);
  const data = await response.json();
  weights = data.weights;
  meta = { classes: data.classes, cellSize: data.cellSize };
  ready = true;
  return meta;
}

export function isReady() { return ready; }
export function getMeta() { return meta; }

// Classify a 48×48 Float32Array (grayscale, values 0–1, 0=ink, 1=bg).
// Returns [{ glyphName, confidence }] sorted by confidence, topK entries.
export function classify(crop, topK = 5) {
  if (!ready) throw new Error('Weights not loaded.');

  // Input: [48, 48] → [1, 1, 48, 48]
  let x = new Float32Array(1 * 1 * 48 * 48);
  x.set(crop);

  // Stage 1: Conv2d(1→32, 3×3, pad=1) + ReLU + MaxPool(2)
  x = conv2d(x, [1, 1, 48, 48], weights['conv.0.weight'], weights['conv.0.bias'], 32);
  x = relu(x);
  x = maxpool2d(x, [1, 32, 48, 48], 2);
  // → [1, 32, 24, 24]

  // Stage 2: Conv2d(32→64, 3×3, pad=1) + ReLU + MaxPool(2)
  x = conv2d(x, [1, 32, 24, 24], weights['conv.3.weight'], weights['conv.3.bias'], 64);
  x = relu(x);
  x = maxpool2d(x, [1, 64, 24, 24], 2);
  // → [1, 64, 12, 12]

  // Stage 3: Conv2d(64→128, 3×3, pad=1) + ReLU + MaxPool(2)
  x = conv2d(x, [1, 64, 12, 12], weights['conv.6.weight'], weights['conv.6.bias'], 128);
  x = relu(x);
  x = maxpool2d(x, [1, 128, 12, 12], 2);
  // → [1, 128, 6, 6]

  // Stage 4: Conv2d(128→192, 3×3, pad=1) + ReLU
  x = conv2d(x, [1, 128, 6, 6], weights['conv.9.weight'], weights['conv.9.bias'], 192);
  x = relu(x);
  // → [1, 192, 6, 6]

  // GlobalAveragePool → [1, 192, 1, 1] → [192]
  x = globalAvgPool(x, [1, 192, 6, 6]);

  // Dense → [numClasses] + Softmax
  const numClasses = weights['fc.weight'].length; // fc.weight shape: [numClasses, 192]
  let logits = new Float32Array(numClasses);
  const w = weights['fc.weight'];
  const b = weights['fc.bias'];
  for (let i = 0; i < numClasses; i++) {
    let sum = b[i];
    for (let j = 0; j < 192; j++) {
      sum += x[j] * w[i][j];
    }
    logits[i] = sum;
  }

  // Softmax
  const maxLogit = Math.max(...logits);
  let sumExp = 0;
  const probs = new Float32Array(numClasses);
  for (let i = 0; i < numClasses; i++) {
    probs[i] = Math.exp(logits[i] - maxLogit);
    sumExp += probs[i];
  }
  for (let i = 0; i < numClasses; i++) {
    probs[i] /= sumExp;
  }

  // Top-K
  return Array.from(probs)
    .map((conf, i) => ({
      glyphName: meta.classes[i]?.name ?? `class_${i}`,
      codepoint: meta.classes[i]?.codepoint,
      confidence: conf,
    }))
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, topK);
}

// ── Conv2D: input [N,C,H,W], kernel [O,C,Kh,Kw], bias [O], output [N,O,H,W] (same padding) ──
function conv2d(x, shape, kernel, bias, outC) {
  const [N, C, H, W] = shape;
  const Kh = kernel[0][0].length;
  const Kw = kernel[0][0][0].length;
  const pad = Kh >> 1;
  const out = new Float32Array(N * outC * H * W);

  for (let n = 0; n < N; n++) {
    for (let oc = 0; oc < outC; oc++) {
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          let sum = bias[oc];
          for (let ic = 0; ic < C; ic++) {
            for (let ky = 0; ky < Kh; ky++) {
              for (let kx = 0; kx < Kw; kx++) {
                const iy = y + ky - pad;
                const ix = x + kx - pad;
                if (iy >= 0 && iy < H && ix >= 0 && ix < W) {
                  sum += x[((n * C + ic) * H + iy) * W + ix] * kernel[oc][ic][ky][kx];
                }
              }
            }
          }
          out[((n * outC + oc) * H + y) * W + x] = sum;
        }
      }
    }
  }
  return out;
}

// ── ReLU ──
function relu(x) {
  for (let i = 0; i < x.length; i++) if (x[i] < 0) x[i] = 0;
  return x;
}

// ── MaxPool2D: kernel=size, stride=size (square) ──
function maxpool2d(x, shape, size) {
  const [N, C, H, W] = shape;
  const outH = H / size;
  const outW = W / size;
  const out = new Float32Array(N * C * outH * outW);

  for (let n = 0; n < N; n++) {
    for (let c = 0; c < C; c++) {
      for (let y = 0; y < outH; y++) {
        for (let x = 0; x < outW; x++) {
          let maxVal = -Infinity;
          for (let ky = 0; ky < size; ky++) {
            for (let kx = 0; kx < size; kx++) {
              const iy = y * size + ky;
              const ix = x * size + kx;
              const v = x[((n * C + c) * H + iy) * W + ix];
              if (v > maxVal) maxVal = v;
            }
          }
          out[((n * C + c) * outH + y) * outW + x] = maxVal;
        }
      }
    }
  }
  return out;
}

// ── Global Average Pool: [N, C, H, W] → [N*C] ──
function globalAvgPool(x, shape) {
  const [N, C, H, W] = shape;
  const out = new Float32Array(N * C);
  const area = H * W;
  for (let n = 0; n < N; n++) {
    for (let c = 0; c < C; c++) {
      let sum = 0;
      for (let i = 0; i < area; i++) {
        sum += x[((n * C + c) * H * W) + i];
      }
      out[n * C + c] = sum / area;
    }
  }
  return out;
}
