/* from_chant.js — adapter: compiled chant score -> timed-score document.
 *
 * Input is the chant engine's compiled timeline (web/score/compiler.js
 * compileChantScore / compileChantScript output): notes and rests with
 * startMs/durationMs, absolute moria relative to Reference Ni, plus the ison,
 * pthora, tempo, checkpoint, and phrase lanes.
 *
 * Pitch resolution follows the shipping consumer exactly
 * (web/score/score_practice.js createScorePracticeState):
 * moria = targetMoria ?? effectiveMoria ?? moria, so a tuning-retuned score
 * (tuning_context.js retuneCompiledScoreWithGrid) adapts with engine-accurate
 * pitches and an un-retuned one falls back to symbolic moria. Hz derivation is
 * the engine's single tuning formula (src/tuning/grid.rs moria_to_hz):
 * refNiHz * 2^(moria/72). Moria are carried through UNROUNDED — MIDI cannot
 * represent them and is never used here.
 *
 * Notation-specific data (glyph display, lyric melisma structure, scale/genus
 * context, movement) rides along per event in notationData, which consumers
 * must treat as opaque.
 */

import {
  CONTRACT_NAME,
  CONTRACT_VERSION,
  DEFAULT_REF_NI_HZ,
  hzFromMoria,
} from './timed_score.js';

export const FROM_CHANT_ADAPTER = 'byzantine-compiled-chant';
export const FROM_CHANT_ADAPTER_VERSION = '1.0.0';

const MELODY_PART_ID = 'mel';

function noteMoria(note) {
  // Same precedence as createScorePracticeState (score_practice.js).
  return note.targetMoria ?? note.effectiveMoria ?? note.moria;
}

export function timedScoreFromCompiledChant(compiled, options = {}) {
  const {
    scoreId,
    refNiHz = DEFAULT_REF_NI_HZ,
    includeRests = true,
    sourceRef = null,
  } = options;

  if (!compiled || !Array.isArray(compiled.notes)) throw new Error('timedScoreFromCompiledChant: compiled chant score required');
  if (typeof scoreId !== 'string' || !scoreId) throw new Error('timedScoreFromCompiledChant: scoreId required');
  if (!Number.isFinite(refNiHz) || refNiHz <= 0) throw new Error('timedScoreFromCompiledChant: positive refNiHz required');

  let sawLyric = false;
  const noteEvents = compiled.notes.map((n, i) => {
    const moria = noteMoria(n);
    const lyric = n.lyric?.kind === 'start' ? (n.lyric.text ?? null) : null;
    if (lyric) sawLyric = true;
    return {
      id: `ch:note:${i}`,
      partId: MELODY_PART_ID,
      kind: 'note',
      startSec: n.startMs / 1000,
      endSec: (n.startMs + n.durationMs) / 1000,
      target: {
        hz: hzFromMoria(moria, refNiHz),
        pitch: {
          type: 'moria',
          moria,
          refNiHz,
          degree: n.degree,
          register: n.register,
          accidentalMoria: n.accidental?.moria ?? 0,
        },
      },
      lyric,
      anchors: {
        sourceEventIndex: n.sourceEventIndex,
        durationBeats: n.durationBeats,
      },
      notationData: {
        display: n.display ?? null,
        lyric: n.lyric ?? null,
        scale: n.scale ?? null,
        movement: n.movement ?? null,
        accidental: n.accidental ?? null,
      },
    };
  });

  const restEvents = includeRests
    ? (compiled.rests ?? []).map((r, i) => ({
        id: `ch:rest:${i}`,
        partId: MELODY_PART_ID,
        kind: 'rest',
        startSec: r.startMs / 1000,
        endSec: (r.startMs + r.durationMs) / 1000,
        target: null,
        lyric: null,
        anchors: {
          sourceEventIndex: r.sourceEventIndex,
          durationBeats: r.durationBeats,
        },
      }))
    : [];

  const events = [...noteEvents, ...restEvents].sort(
    (a, b) => a.startSec - b.startSec || (a.kind === 'rest' ? 1 : 0) - (b.kind === 'rest' ? 1 : 0),
  );

  const ison = (compiled.isonEvents ?? []).map((e) => ({
    atSec: e.atMs / 1000,
    hz: Number.isFinite(e.moria) ? hzFromMoria(e.moria, refNiHz) : null,
    pitch: Number.isFinite(e.moria)
      ? { type: 'moria', moria: e.moria, refNiHz, degree: e.degree, register: e.register ?? null, accidentalMoria: 0 }
      : null,
    degree: e.degree ?? null,
    kind: e.kind ?? null,
  }));

  // Mirror createScorePracticeState: a non-default initial tuning is the first
  // tuning change, so a consumer replaying tuningChanges reconstructs the same
  // grid state the score-practice view uses.
  const initialTuning = compiled.initialTuning && (compiled.initialTuning.source || compiled.initialTuning.scale !== 'diatonic')
    ? [{ atSec: 0, kind: 'initial', detail: compiled.initialTuning }]
    : [];
  const tuningChanges = [
    ...initialTuning,
    ...(compiled.pthoraEvents ?? []).map((e) => ({ atSec: e.atMs / 1000, kind: 'pthora', detail: e })),
  ];

  const tempo = (compiled.tempoChanges ?? []).map((t) => ({ atSec: t.atMs / 1000, bpm: t.workingBpm }));
  const checkpoints = (compiled.checkpoints ?? []).map((c) => ({
    atSec: c.atMs / 1000,
    degree: c.degree,
    actualDegree: c.actualDegree,
    matches: c.matches,
  }));
  const phrases = (compiled.phraseBreaks ?? []).map((p) => ({ atSec: p.atMs / 1000 }));

  return {
    contract: CONTRACT_NAME,
    contractVersion: CONTRACT_VERSION,
    adapter: {
      name: FROM_CHANT_ADAPTER,
      version: FROM_CHANT_ADAPTER_VERSION,
      options: { refNiHz, includeRests },
    },
    score: {
      id: scoreId,
      title: compiled.score?.title ?? null,
      notation: 'byzantine-chant',
      sourceRef,
    },
    capabilities: {
      microtonal: true,
      ison: ison.length > 0,
      tuningChanges: tuningChanges.length > 0,
      tempoChanges: tempo.length > 1,
      explicitRests: restEvents.length > 0,
      sections: false,
      phrases: phrases.length > 0,
      checkpoints: checkpoints.length > 0,
      multiPart: false,
      lyrics: sawLyric,
    },
    parts: [{ id: MELODY_PART_ID, name: 'Melody', role: 'melody', selectable: true }],
    timeline: {
      units: 'seconds',
      totalSec: (compiled.totalDurationMs ?? 0) / 1000,
      events,
      tempo,
      sections: [],
      ison,
      tuningChanges,
      checkpoints,
      phrases,
    },
    diagnostics: [...(compiled.diagnostics ?? [])],
  };
}
