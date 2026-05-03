// End-to-end recognition: grayscale page buffer + templates -> SourceTokens with
// region + confidence + alternates. The output array is what compileGlyphGroups
// wants once you wrap each token in a length-1 array (or call the resolver
// directly via the existing import path).

import { binarizeGray, cropGrayBuffer, bboxCenter } from './buffers.js';
import {
  findConnectedComponents,
  groupComponentsIntoColumns,
} from './segment.js';
import { classifyCandidate } from './classify.js';

const DEFAULT_OPTIONS = Object.freeze({
  binaryThreshold: 'otsu',
  minComponentPixels: 6,
  topK: 4,
});

export function recognizePage(grayBuffer, templates, options = {}) {
  const config = { ...DEFAULT_OPTIONS, ...options };
  const binary = binarizeGray(grayBuffer, config.binaryThreshold);
  const components = findConnectedComponents(binary, { minPixels: config.minComponentPixels });
  const { columns } = groupComponentsIntoColumns(components);
  const linesOfColumns = partitionColumnsIntoLines(columns, components);

  const tokens = [];
  let lineIndex = 0;
  for (const lineColumns of linesOfColumns) {
    for (const column of lineColumns) {
      const ordered = orderedComponentIndices(column);
      for (const componentIndex of ordered) {
        const component = components[componentIndex];
        if (!component) continue;
        const candidate = cropGrayBuffer(grayBuffer, padBBox(component.bbox, 2, grayBuffer));
        const matches = classifyCandidate(candidate, templates, { topK: config.topK });
        if (!matches.length) continue;
        const [best, ...alternates] = matches;
        tokens.push({
          glyphName: best.glyphName,
          codepoint: best.codepoint,
          confidence: best.confidence,
          source: 'ocr',
          region: { bbox: { ...component.bbox }, line: lineIndex, role: 'neume' },
          alternates: alternates.map(alt => ({
            glyphName: alt.glyphName,
            codepoint: alt.codepoint,
            confidence: alt.confidence,
          })),
        });
      }
    }
    lineIndex += 1;
  }

  return {
    tokens,
    components,
    lineCount: linesOfColumns.length,
    binaryThreshold: binary.threshold,
  };
}

function partitionColumnsIntoLines(columns, components, options = {}) {
  if (!columns.length) return [];
  const tolerance = options.lineGapFactor ?? 0.6;

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
  const lineGap = medianHeight * (1 + tolerance);

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

  for (const line of lines) {
    line.sort((a, b) => bboxCenter(a.bbox).x - bboxCenter(b.bbox).x);
  }
  return lines;
}

function orderedComponentIndices(column) {
  const main = column.mainIndex;
  const above = column.aboveIndices ?? [];
  const below = column.belowIndices ?? [];
  return [main, ...above, ...below].filter(i => Number.isInteger(i));
}

function padBBox(bbox, padding, buffer) {
  const x = Math.max(0, bbox.x - padding);
  const y = Math.max(0, bbox.y - padding);
  const right = Math.min(buffer.width, bbox.x + bbox.w + padding);
  const bottom = Math.min(buffer.height, bbox.y + bbox.h + padding);
  return { x, y, w: right - x, h: bottom - y };
}
