/* to_scoring.js — bridge: timed-score document -> ChanterScoring inputs.
 *
 * ChanterScoring (training-prototype/scoring.js) is pure float arithmetic:
 * targets are { midi, startSec, endSec, lyric?, measure? }, samples fold to
 * the octave nearest the target before the cents error is measured. Nothing
 * in it assumes integer MIDI — so Byzantine microtonal targets score through
 * the EXISTING engine once expressed as float MIDI, which is exactly what
 * this bridge does:
 *
 *   - midi-typed pitches pass through natively (bit-identical to what
 *     scoring-ui.js buildScoreTargets produces today);
 *   - moria-typed pitches become float MIDI from the target's absolute hz
 *     (69 + 12*log2(hz/440)), preserving 72-EDO precision;
 *   - for microtonal documents the tolerance is derived from the Byzantine
 *     practice default (score_practice.js DEFAULT_TOLERANCE_MORIA = 4) via
 *     1 moria = 1200/72 cents, i.e. 4 moria = 66.67 cents. Both engines
 *     fold octaves (centsToTarget / nearestOctaveMoriaDelta), so the scoring
 *     models line up.
 *
 * This is a consumer-side proof for ONEAPP-02, not a consumer change: no app
 * code imports this yet.
 */

import {
  DEFAULT_A4_HZ,
  MORIA_PER_OCTAVE,
  validateTimedScore,
} from './timed_score.js';

export const TO_SCORING_ADAPTER = 'timed-score-to-chanter-scoring';
export const TO_SCORING_ADAPTER_VERSION = '1.0.0';

// score_practice.js DEFAULT_TOLERANCE_MORIA — the shipping Byzantine band.
export const DEFAULT_TOLERANCE_MORIA = 4;
export const CENTS_PER_MORIA = 1200 / MORIA_PER_OCTAVE;

export function midiFromHz(hz, a4Hz = DEFAULT_A4_HZ) {
  return 69 + 12 * Math.log2(hz / a4Hz);
}

export function scoringInputsFromTimedScore(doc, options = {}) {
  const { partId = null, toleranceMoria = DEFAULT_TOLERANCE_MORIA } = options;

  const result = validateTimedScore(doc);
  if (!result.ok) {
    throw new Error(`scoringInputsFromTimedScore: invalid document — ${result.errors[0]}`);
  }
  const part = partId ?? doc.parts.find((p) => p.selectable)?.id;
  if (!doc.parts.some((p) => p.id === part)) {
    throw new Error(`scoringInputsFromTimedScore: unknown part "${part}"`);
  }
  if (!Number.isFinite(toleranceMoria) || toleranceMoria <= 0) {
    throw new Error('scoringInputsFromTimedScore: toleranceMoria must be positive');
  }

  const targets = doc.timeline.events
    .filter((e) => e.partId === part && e.kind === 'note')
    .map((e) => ({
      midi: e.target.pitch.type === 'midi' ? e.target.pitch.midi : midiFromHz(e.target.hz),
      startSec: e.startSec,
      endSec: e.endSec,
      lyric: e.lyric ?? null,
      ...(Number.isFinite(e.anchors?.measure) ? { measure: e.anchors.measure } : {}),
    }));

  // Non-microtonal documents keep the app's presets untouched; microtonal
  // ones carry the moria-derived band so the strictness semantics transfer.
  const opts = doc.capabilities.microtonal
    ? { centsTol: toleranceMoria * CENTS_PER_MORIA }
    : {};

  return { targets, opts, partId: part };
}
