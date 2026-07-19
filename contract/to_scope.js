/* to_scope.js — bridge: timed-score document -> TrainingScope.setLane inputs.
 *
 * The singscope's gold lane (training-prototype/scope.js setLane) consumes
 * { start, end, midi, lyric } note objects — the selected voice as the gold
 * trace, every other voice faint — plus the window length in seconds, and
 * derives its y-range from the midi values (floats included). This bridge
 * produces exactly the shape voices.js buildScopeLane hands it today:
 * midi-typed pitches pass through natively, moria-typed pitches become the
 * same float MIDI the scoring bridge uses, so the lane a singer sees and the
 * band they are scored against stay one system.
 *
 * Like to_scoring.js this is ONEAPP-02 de-risking, not a consumer change:
 * no app code imports it yet.
 */

import { validateTimedScore } from './timed_score.js';
import { midiFromHz } from './to_scoring.js';

export const TO_SCOPE_ADAPTER = 'timed-score-to-scope-lane';
export const TO_SCOPE_ADAPTER_VERSION = '1.0.0';

function laneNote(e) {
  return {
    start: e.startSec,
    end: e.endSec,
    midi: e.target.pitch.type === 'midi' ? e.target.pitch.midi : midiFromHz(e.target.hz),
    lyric: e.lyric ?? null,
  };
}

export function scopeLaneFromTimedScore(doc, options = {}) {
  const { partId = null } = options;

  const result = validateTimedScore(doc);
  if (!result.ok) {
    throw new Error(`scopeLaneFromTimedScore: invalid document — ${result.errors[0]}`);
  }
  const part = partId ?? doc.parts.find((p) => p.selectable)?.id;
  if (!doc.parts.some((p) => p.id === part)) {
    throw new Error(`scopeLaneFromTimedScore: unknown part "${part}"`);
  }

  const notes = doc.timeline.events.filter((e) => e.kind === 'note');
  return {
    selected: notes.filter((e) => e.partId === part).map(laneNote),
    others: notes.filter((e) => e.partId !== part).map(laneNote),
    windowSec: doc.timeline.totalSec,
    partId: part,
  };
}
