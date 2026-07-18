/* from_musicxml.js — adapter: parsed MusicXML model -> timed-score document.
 *
 * Input is the training app's parsed model (training-prototype/js/model.js
 * parseMusicXML output): parts of { voiceKey, voiceName, index, notes }, each
 * note { midi, startBeat, durBeat, measure, lyric, lyricVerses } with beats in
 * quarter notes, ties pre-merged, and rests omitted (gaps are implicit).
 *
 * The adapter replicates the beat->seconds math the app's three consumers
 * share (voices.js buildScopeLane, scoring-ui.js buildScoreTargets,
 * transport.js scheduleAll): a single global BPM, a measure-range loop window
 * from the min/max note beats (model.js measureBeatRange), and the window
 * filter `startBeat >= winStart-EPS && startBeat < winEnd-EPS`. Transpose is
 * a timeline-level pitch offset applied where MIDI leaves the model; the
 * notated pitch is preserved in anchors.notatedMidi and the engraving is
 * untouched (sourceRef points at it).
 *
 * Determinism: same parsed model + same options -> byte-identical document.
 * Event IDs index into the part's FULL note array, so an event keeps its ID
 * no matter which loop window is exported.
 */

import {
  CONTRACT_NAME,
  CONTRACT_VERSION,
  DEFAULT_A4_HZ,
  hzFromMidi,
} from './timed_score.js';

export const FROM_MUSICXML_ADAPTER = 'musicxml-satb-parsed';
export const FROM_MUSICXML_ADAPTER_VERSION = '1.0.0';

const EPS = 1e-6; // window filter epsilon, as in voices.js/scoring-ui.js

export function timedScoreFromParsedMusicXML(parsed, options = {}) {
  const {
    scoreId,
    title = null,
    bpm,
    transposeSemitones = 0,
    fromMeasure = 1,
    toMeasure = null,
    sections = null,
    sourceRef = null,
  } = options;

  if (!parsed || !Array.isArray(parsed.parts)) throw new Error('timedScoreFromParsedMusicXML: parsed model required');
  if (typeof scoreId !== 'string' || !scoreId) throw new Error('timedScoreFromParsedMusicXML: scoreId required');
  if (!Number.isFinite(bpm) || bpm <= 0) throw new Error('timedScoreFromParsedMusicXML: positive bpm required');
  const transpose = Math.round(Number(transposeSemitones) || 0);
  const to = Number.isFinite(toMeasure) ? toMeasure : (parsed.measureCount || 1);
  const from = Number.isFinite(fromMeasure) ? fromMeasure : 1;

  // model.js measureBeatRange: window = min startBeat / max (startBeat+durBeat)
  // over notes whose measure falls in [from, to].
  let winStart = Infinity;
  let winEnd = 0;
  for (const part of parsed.parts) {
    for (const n of part.notes) {
      if (n.measure >= from && n.measure <= to) {
        winStart = Math.min(winStart, n.startBeat);
        winEnd = Math.max(winEnd, n.startBeat + n.durBeat);
      }
    }
  }
  if (!Number.isFinite(winStart)) {
    winStart = 0;
    winEnd = 0;
  }

  const spb = 60 / bpm;
  let sawLyric = false;
  const events = [];
  const parts = parsed.parts.map((part) => ({
    id: part.voiceKey,
    name: part.voiceName,
    role: 'satb',
    selectable: true,
  }));

  for (const part of parsed.parts) {
    part.notes.forEach((n, i) => {
      if (!(n.startBeat >= winStart - EPS && n.startBeat < winEnd - EPS)) return;
      const midi = n.midi + transpose;
      if (n.lyric) sawLyric = true;
      events.push({
        id: `mx:${part.voiceKey}:${i}`,
        partId: part.voiceKey,
        kind: 'note',
        startSec: (n.startBeat - winStart) * spb,
        endSec: (n.startBeat - winStart + n.durBeat) * spb,
        target: {
          hz: hzFromMidi(midi),
          pitch: { type: 'midi', midi, a4Hz: DEFAULT_A4_HZ },
        },
        lyric: n.lyric || null,
        anchors: {
          measure: n.measure,
          startBeat: n.startBeat,
          durationBeats: n.durBeat,
          notatedMidi: n.midi,
        },
      });
    });
  }

  // Sections stay measure-anchored (the app loops in measures, not seconds;
  // sections.js needs >= 2 entries to activate). No seconds are attached: a
  // section outside the exported window has no time in this document.
  const sectionIndex = Array.isArray(sections) && sections.length >= 2
    ? sections.map((s, i) => ({
        id: `sec:${i}`,
        title: s.title ?? null,
        anchors: {
          fromMeasure: s.measure,
          toMeasure: (sections[i + 1]?.measure ?? to + 1) - 1,
        },
      }))
    : [];

  return {
    contract: CONTRACT_NAME,
    contractVersion: CONTRACT_VERSION,
    adapter: {
      name: FROM_MUSICXML_ADAPTER,
      version: FROM_MUSICXML_ADAPTER_VERSION,
      options: { bpm, transposeSemitones: transpose, fromMeasure: from, toMeasure: to },
    },
    score: { id: scoreId, title, notation: 'musicxml-satb', sourceRef },
    capabilities: {
      microtonal: false,
      ison: false,
      tuningChanges: false,
      tempoChanges: false,
      explicitRests: false,
      sections: sectionIndex.length >= 2,
      phrases: false,
      checkpoints: false,
      multiPart: parsed.parts.length > 1,
      lyrics: sawLyric,
    },
    parts,
    timeline: {
      units: 'seconds',
      totalSec: (winEnd - winStart) * spb,
      events,
      tempo: [{ atSec: 0, bpm }],
      sections: sectionIndex,
      ison: [],
      tuningChanges: [],
      checkpoints: [],
      phrases: [],
    },
    diagnostics: [],
  };
}
