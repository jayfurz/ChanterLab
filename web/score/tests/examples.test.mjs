import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  chantScriptExampleText,
  compileChantScriptExample,
  listChantScriptExamples,
} from '../examples.js';
import { hasErrorDiagnostics } from '../diagnostics.js';

const DOC_FIXTURE_BY_ID = Object.freeze({
  'diatonic-ladder': 'diatonic_ladder.chant',
  'lyrics-melisma': 'lyrics_melisma.chant',
  'soft-chromatic-phrase': 'soft_chromatic_phrase.chant',
  'symbolic-timing-steal': 'symbolic_timing_steal.chant',
  'temporal-rules': 'temporal_rules.chant',
});

function readDocFixture(name) {
  return readFileSync(
    new URL(`../../../docs/examples/chant_scripts/${name}`, import.meta.url),
    'utf8'
  );
}

function normalizeFixtureText(text) {
  return text.replace(/\r\n/g, '\n').replace(/\n?$/, '\n');
}

test('embedded browser examples mirror docs seed fixtures', () => {
  for (const example of listChantScriptExamples()) {
    const docFixture = DOC_FIXTURE_BY_ID[example.id];
    assert.ok(docFixture, example.id);
    assert.equal(
      normalizeFixtureText(chantScriptExampleText(example.id)),
      normalizeFixtureText(readDocFixture(docFixture)),
      example.id
    );
  }
});

test('example loader compiles every seed fixture without errors', () => {
  for (const example of listChantScriptExamples()) {
    const compiled = compileChantScriptExample(example.id);
    assert.equal(hasErrorDiagnostics(compiled.diagnostics), false, example.id);
    assert.ok(compiled.notes.length > 0, example.id);
  }
});
