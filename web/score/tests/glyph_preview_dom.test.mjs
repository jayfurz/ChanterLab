import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createGlyphPreviewStrip,
  renderGlyphPreview,
} from '../glyph_preview_dom.js';
import { glyphPreviewFromText } from '../glyph_render.js';

test('shared glyph preview DOM renders modifier clusters with score-practice classes', () => {
  const documentRef = fakeDocument();
  const previewEl = documentRef.createElement('div');

  const preview = renderGlyphPreview(previewEl, {
    text: 'fthoraSoftChromaticDiAbove oligon chroaZygosAbove apostrofos',
    source: 'glyph',
    documentRef,
  });

  assert.equal(preview.clusters.length, 2);
  assert.equal(previewEl.children.length, 2);
  assert.equal(previewEl.children[0].className, 'score-practice-glyph-preview-strip');
  assert.equal(previewEl.children[1].className, 'score-practice-glyph-preview-summary');
  assert.equal(previewEl.classList.toggles.get('has-errors'), false);

  const firstCluster = previewEl.children[0].children[0];
  assert.equal(firstCluster.tagName, 'BUTTON');
  assert.match(firstCluster.className, /score-practice-glyph-cluster/);
  assert.match(firstCluster.className, /has-above/);
  assert.equal(firstCluster.children[0].className, 'score-practice-glyph-slot above');
  assert.equal(firstCluster.children[0].children[0].className, 'score-practice-glyph-preview-item pthora');
  assert.equal(firstCluster.children[1].children[0].className, 'score-practice-glyph-preview-item quantity');
});

test('shared glyph preview strip can render atlas clusters as non-button elements', () => {
  const documentRef = fakeDocument();
  const sourceText = 'gorgonAbove oligon';
  const preview = glyphPreviewFromText(sourceText, { source: 'glyph-name' });

  const strip = createGlyphPreviewStrip(preview, {
    sourceText,
    documentRef,
    clusterTag: 'span',
  });

  assert.equal(strip.className, 'score-practice-glyph-preview-strip');
  assert.equal(strip.children.length, 1);
  assert.equal(strip.children[0].tagName, 'SPAN');
  assert.match(strip.children[0].className, /score-practice-glyph-cluster/);
  assert.equal(strip.children[0].dataset.sourceStart, '0');
  assert.equal(strip.children[0].dataset.sourceEnd, '18');
});

function fakeDocument() {
  return {
    createElement(tagName) {
      const tag = tagName.toUpperCase();
      return {
        tagName: tag,
        children: [],
        dataset: {},
        attributes: {},
        className: '',
        textContent: '',
        title: '',
        innerHTML: '',
        classList: {
          toggles: new Map(),
          toggle(name, force) {
            this.toggles.set(name, force);
          },
        },
        appendChild(child) {
          this.children.push(child);
          return child;
        },
        append(...children) {
          this.children.push(...children);
        },
        setAttribute(name, value) {
          this.attributes[name] = String(value);
        },
      };
    },
  };
}
