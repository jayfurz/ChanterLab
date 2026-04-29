import test from 'node:test';
import assert from 'node:assert/strict';

import {
  editGlyphImportText,
  glyphImportTokenText,
} from '../glyph_editor.js';

test('glyph editor replaces mutually exclusive duration signs in selected group', () => {
  const edit = editGlyphImportText('ison apli oligon', {
    glyphName: 'klasma',
    source: 'glyph',
    selectionStart: 0,
    selectionEnd: 'ison apli'.length,
  });

  assert.equal(edit.text, 'ison klasma oligon');
  assert.equal(edit.selectionStart, 'ison klasma'.length);
  assert.equal(edit.selectionEnd, 'ison klasma'.length);
});

test('glyph editor appends exclusive modifier to selected anchor group', () => {
  const edit = editGlyphImportText('ison oligon', {
    glyphName: 'apli',
    source: 'glyph',
    selectionStart: 0,
    selectionEnd: 'ison'.length,
  });

  assert.equal(edit.text, 'ison apli oligon');
});

test('glyph editor replaces mutually exclusive temporal signs in current group', () => {
  const edit = editGlyphImportText('ison gorgonAbove oligon', {
    glyphName: 'digorgon',
    source: 'glyph',
    selectionStart: 'ison gorgonAbove'.length,
    selectionEnd: 'ison gorgonAbove'.length,
  });

  assert.equal(edit.text, 'ison digorgon oligon');
});

test('glyph editor replaces all legacy duplicate exclusive modifiers', () => {
  const edit = editGlyphImportText('ison gorgonAbove digorgon oligon', {
    glyphName: 'trigorgon',
    source: 'glyph',
    selectionStart: 0,
    selectionEnd: 'ison gorgonAbove digorgon'.length,
  });

  assert.equal(edit.text, 'ison trigorgon oligon');
});

test('glyph editor treats pthora and chroa as one exclusive mode-sign family', () => {
  const edit = editGlyphImportText('ison fthoraSoftChromaticDiAbove oligon', {
    glyphName: 'chroaZygosAbove',
    source: 'glyph',
    selectionStart: 0,
    selectionEnd: 'ison fthoraSoftChromaticDiAbove'.length,
  });

  assert.equal(edit.text, 'ison chroaZygosAbove oligon');
});

test('glyph editor inserts source-specific glyph text while preserving exclusive replacement', () => {
  const apli = glyphImportTokenText('apli', 'sbmufl');
  const dipli = glyphImportTokenText('dipli', 'sbmufl');
  const edit = editGlyphImportText(`\uE000${apli}\uE001`, {
    glyphName: 'dipli',
    source: 'sbmufl',
    selectionStart: 0,
    selectionEnd: `\uE000${apli}`.length,
  });

  assert.equal(edit.text, `\uE000${dipli}\uE001`);
});
