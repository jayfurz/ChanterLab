/* scope-verdicts.js — per-note verdict tints on the singscope lane (issue #60
 * phase 2: the SCOPE half of "per-note coloring on the score/scope"; the
 * notation half shipped as #79). Rides the SAME "Show on score" toggle and
 * lifecycle as the notehead overlay: loader.js owns the on/off flag and fires
 * 'chanterlab:scorecoloring' on every apply / clear / voice / verse / piece
 * transition, and this module mirrors that state onto the scope by writing or
 * removing a `tint` color on the lane's note objects (scope.js draws
 * `n.tint || GOLD`). Canvas-only: no OSMD involved, no load(), no re-render —
 * the scope's own rAF loop picks the tints up on the next frame.
 *
 * MAPPING IS BY INDEX, the same contract loader.applyScoreColoring uses:
 * buildScopeLane's selected-voice lane (voices.js) and buildScoreTargets'
 * targets (scoring-ui.js) are the SAME parsed note stream through the SAME
 * loop-window filter, so lane[i] ↔ details[i]. An exact count match plus a
 * per-note midi check is required — if the lane was rebuilt over a different
 * window (loop edits after scoring, worst-spot jumps), we keep the plain gold
 * lane rather than mis-tint. Rests never appear in either stream (parsed
 * excludes them), so cursor rest-timestep off-by-ones can't bite here.
 */
import { scoreColoringActive, VERDICT_TINTS } from './loader.js';
import { lastScoreResult } from './scoring-ui.js';

let lastInfo = { on: false, applied: false, painted: 0, targets: 0 };

function laneNotes() {
  const scope = window.TrainingScope;
  return (scope && typeof scope.getLane === 'function') ? scope.getLane() : null;
}

function clearTints() {
  const lane = laneNotes();
  if (lane) lane.forEach((n) => { if (n.tint) delete n.tint; });
  lastInfo = { on: false, applied: false, painted: 0, targets: 0 };
}

function applyTints(details) {
  const lane = laneNotes();
  const targets = details.length;
  lastInfo = { on: true, applied: false, painted: 0, targets };
  if (!lane || lane.length !== targets) return;          // lane ≠ scored window — keep gold
  for (let i = 0; i < targets; i++) {
    if (lane[i].midi !== details[i].midi) return;        // drifted — keep gold
  }
  let painted = 0;
  for (let i = 0; i < targets; i++) {
    const tint = VERDICT_TINTS[details[i].result];
    if (tint) { lane[i].tint = tint; painted++; }
    else if (lane[i].tint) delete lane[i].tint;
  }
  lastInfo = { on: true, applied: true, painted, targets };
}

// Mirror loader's coloring flag onto the scope lane. Called on every
// 'chanterlab:scorecoloring' event, and re-called by main.js after lane
// rebuilds that DON'T clear the overlay (bpm / loop-input edits) so a
// same-window rebuild gets its tints back.
export function syncScopeVerdicts() {
  const details = lastScoreResult && lastScoreResult.details;
  if (scoreColoringActive() && details && details.length) applyTints(details);
  else clearTints();
  return lastInfo;
}

// Snapshot for the __training.scopeVerdicts() hook: on/applied flags, painted
// vs targets counts, and each lane note's current tint (null = plain gold) so
// a test can assert exactly which bars carry a verdict color.
export function scopeVerdictsInfo() {
  const lane = laneNotes() || [];
  return Object.assign({}, lastInfo, { tints: lane.map((n) => n.tint || null) });
}

export function initScopeVerdicts() {
  document.addEventListener('chanterlab:scorecoloring', syncScopeVerdicts);
}
