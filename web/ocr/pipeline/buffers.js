// Generic ImageData-shaped buffer helpers usable in both Node and the browser.
// All buffers here are { width, height, data: Uint8ClampedArray } with one byte per pixel
// (grayscale, 0 = black ink, 255 = white background) unless noted otherwise.

export function createGrayBuffer(width, height, fill = 255) {
  const data = new Uint8ClampedArray(width * height);
  if (fill !== 0) data.fill(fill);
  return { width, height, data };
}

export function cropGrayBuffer(buffer, bbox) {
  const x = Math.max(0, Math.floor(bbox.x));
  const y = Math.max(0, Math.floor(bbox.y));
  const w = Math.min(buffer.width - x, Math.ceil(bbox.w));
  const h = Math.min(buffer.height - y, Math.ceil(bbox.h));
  const out = createGrayBuffer(w, h, 255);
  for (let row = 0; row < h; row += 1) {
    const srcStart = (y + row) * buffer.width + x;
    const dstStart = row * w;
    for (let col = 0; col < w; col += 1) {
      out.data[dstStart + col] = buffer.data[srcStart + col];
    }
  }
  return out;
}

export function resampleGrayBuffer(buffer, targetW, targetH) {
  const out = createGrayBuffer(targetW, targetH, 255);
  if (buffer.width === 0 || buffer.height === 0) return out;
  const xRatio = buffer.width / targetW;
  const yRatio = buffer.height / targetH;
  for (let y = 0; y < targetH; y += 1) {
    const srcY = Math.min(buffer.height - 1, Math.floor(y * yRatio));
    for (let x = 0; x < targetW; x += 1) {
      const srcX = Math.min(buffer.width - 1, Math.floor(x * xRatio));
      out.data[y * targetW + x] = buffer.data[srcY * buffer.width + srcX];
    }
  }
  return out;
}

export function rgbaToGray(rgba, width, height) {
  const out = new Uint8ClampedArray(width * height);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 1) {
    // Rec. 601 luma; preserve background as bright (255), ink as dark (0).
    out[j] = (rgba[i] * 0.299 + rgba[i + 1] * 0.587 + rgba[i + 2] * 0.114) | 0;
  }
  return { width, height, data: out };
}

export function binarizeGray(buffer, threshold = 'otsu') {
  const t = threshold === 'otsu' ? otsuThreshold(buffer.data) : threshold;
  const data = new Uint8ClampedArray(buffer.data.length);
  for (let i = 0; i < buffer.data.length; i += 1) {
    data[i] = buffer.data[i] <= t ? 0 : 255;
  }
  return { width: buffer.width, height: buffer.height, data, threshold: t };
}

export function otsuThreshold(data) {
  const histogram = new Uint32Array(256);
  for (let i = 0; i < data.length; i += 1) histogram[data[i]] += 1;

  const total = data.length;
  let sum = 0;
  for (let i = 0; i < 256; i += 1) sum += i * histogram[i];

  let sumB = 0;
  let wB = 0;
  let maxBetween = 0;
  let bestT = 127;
  for (let t = 0; t < 256; t += 1) {
    wB += histogram[t];
    if (wB === 0) continue;
    const wF = total - wB;
    if (wF === 0) break;
    sumB += t * histogram[t];
    const mB = sumB / wB;
    const mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > maxBetween) {
      maxBetween = between;
      bestT = t;
    }
  }
  return bestT;
}

export function bbox(width, height) {
  return { x: 0, y: 0, w: width, h: height };
}

export function bboxesOverlapHorizontally(a, b) {
  const aRight = a.x + a.w;
  const bRight = b.x + b.w;
  const left = Math.max(a.x, b.x);
  const right = Math.min(aRight, bRight);
  return right > left;
}

export function bboxCenter(b) {
  return { x: b.x + b.w / 2, y: b.y + b.h / 2 };
}
