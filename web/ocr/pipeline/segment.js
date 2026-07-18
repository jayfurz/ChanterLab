// Connected-component segmentation on a binarized grayscale buffer.
// Input: { width, height, data } where data[i] === 0 is ink, 255 is background.
// Output: an array of components { bbox, pixelCount }.

import { bboxesOverlapHorizontally, bboxCenter } from './buffers.js';

const NEIGHBOURS_8 = [
  [-1, -1], [0, -1], [1, -1],
  [-1,  0],          [1,  0],
  [-1,  1], [0,  1], [1,  1],
];

export function findConnectedComponents(buffer, options = {}) {
  const minPixels = options.minPixels ?? 6;
  const { width, height, data } = buffer;
  const labels = new Int32Array(width * height);
  const components = [];
  let nextLabel = 1;

  const stack = new Int32Array(width * height);

  for (let i = 0; i < data.length; i += 1) {
    if (data[i] !== 0) continue;
    if (labels[i] !== 0) continue;

    let stackSize = 0;
    stack[stackSize++] = i;
    labels[i] = nextLabel;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let pixelCount = 0;

    while (stackSize > 0) {
      const idx = stack[--stackSize];
      const x = idx % width;
      const y = (idx - x) / width;
      pixelCount += 1;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;

      for (const [dx, dy] of NEIGHBOURS_8) {
        const nx = x + dx;
        const ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
        const nIdx = ny * width + nx;
        if (labels[nIdx] !== 0) continue;
        if (data[nIdx] !== 0) continue;
        labels[nIdx] = nextLabel;
        stack[stackSize++] = nIdx;
      }
    }

    if (pixelCount >= minPixels) {
      components.push({
        label: nextLabel,
        pixelCount,
        bbox: {
          x: minX,
          y: minY,
          w: maxX - minX + 1,
          h: maxY - minY + 1,
        },
      });
    }
    nextLabel += 1;
  }

  return components;
}

// Group components into vertical neume columns by horizontal overlap.
// Returns { columns: [{ bbox, componentIndices, mainIndex, aboveIndices, belowIndices }] }.
export function groupComponentsIntoColumns(components, options = {}) {
  if (!components.length) return { columns: [] };
  const overlapTolerance = options.overlapTolerance ?? 0.4;

  const sorted = components
    .map((component, index) => ({ ...component, _index: index }))
    .sort((a, b) => bboxCenter(a.bbox).x - bboxCenter(b.bbox).x);

  const columns = [];
  for (const component of sorted) {
    const target = columns.find(col => columnContains(col, component, overlapTolerance));
    if (target) {
      target.componentIndices.push(component._index);
      target.bbox = unionBBox(target.bbox, component.bbox);
    } else {
      columns.push({
        bbox: { ...component.bbox },
        componentIndices: [component._index],
      });
    }
  }

  for (const col of columns) {
    const items = col.componentIndices
      .map(i => ({ index: i, comp: components[i] }))
      .sort((a, b) => a.comp.bbox.y - b.comp.bbox.y);
    let mainIndex = items[0].index;
    let mainPixels = items[0].comp.pixelCount;
    for (const item of items) {
      if (item.comp.pixelCount > mainPixels) {
        mainIndex = item.index;
        mainPixels = item.comp.pixelCount;
      }
    }
    const mainComp = components[mainIndex];
    const mainCenterY = bboxCenter(mainComp.bbox).y;
    col.mainIndex = mainIndex;
    col.aboveIndices = items
      .filter(item => item.index !== mainIndex && bboxCenter(item.comp.bbox).y < mainCenterY)
      .map(item => item.index);
    col.belowIndices = items
      .filter(item => item.index !== mainIndex && bboxCenter(item.comp.bbox).y > mainCenterY)
      .map(item => item.index);
  }

  return { columns };
}

// Split components into chant lines by y-banding using horizontal projection.
// A line is a contiguous y-range where components cluster.
export function partitionComponentsIntoLines(components, options = {}) {
  if (!components.length) return [];
  const tolerance = options.lineHeightTolerance ?? 0.6;

  const sorted = [...components].sort((a, b) => bboxCenter(a.bbox).y - bboxCenter(b.bbox).y);
  const heights = sorted.map(c => c.bbox.h);
  const medianHeight = median(heights);
  const lineGap = medianHeight * (1 + tolerance);

  const lines = [];
  let currentLine = [];
  let currentMaxY = -Infinity;
  for (const component of sorted) {
    const cy = bboxCenter(component.bbox).y;
    if (currentLine.length === 0 || cy - currentMaxY <= lineGap) {
      currentLine.push(component);
      currentMaxY = Math.max(currentMaxY, cy);
    } else {
      lines.push(currentLine);
      currentLine = [component];
      currentMaxY = cy;
    }
  }
  if (currentLine.length) lines.push(currentLine);
  return lines;
}

function columnContains(column, component, tolerance) {
  const colCenter = column.bbox.x + column.bbox.w / 2;
  const compCenter = component.bbox.x + component.bbox.w / 2;
  const reference = Math.max(column.bbox.w, component.bbox.w);
  const distance = Math.abs(colCenter - compCenter);
  if (distance <= reference * tolerance) return true;
  return bboxesOverlapHorizontally(column.bbox, component.bbox);
}

function unionBBox(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const right = Math.max(a.x + a.w, b.x + b.w);
  const bottom = Math.max(a.y + a.h, b.y + b.h);
  return { x, y, w: right - x, h: bottom - y };
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  if (sorted.length % 2) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}
