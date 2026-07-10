/* scoring-ui.js — per-lap scoring session (Scoring v1, issue #55): pitch-tap
 * targets, the pure-scorer wiring, strictness presets, the post-lap report
 * strip, and per-lap history. Owns the scoring-session state; transport.js
 * drives the lifecycle through beginScoringSession / scoreLapAndRoll /
 * finalizeScoringOnStop.
 */
import { el, setStatus, STRICTNESS_KEY, PRACTICE_HISTORY_KEY } from './state.js';
import { parsed, clampMeasure, measureBeatRange } from './model.js';
import { selectedVoice, activeVerse, buildScopeLane } from './voices.js';
import {
  currentPieceId, ensureRenderWindow, requestRender,
  applyScoreColoring, clearScoreColoring, scoreColoringActive, VERDICT_TINTS,
} from './loader.js';
import { playState, stop, parkCursorAtWindowStart } from './transport.js';

export let practiceSamples = [];   // {tSec,midi} voiced pitch stream for the CURRENT lap
let scoringArmed = false;
export let lastScoreResult = null;
export let sessionLaps = [];
let currentLapNum = 1;
let bestLapHitPct = -1;
export let scoreSummaryShown = false;
export let scoringStrictness = 'relaxed';
let reportDismissed = false;

  /* ---------- Per-note scoring (Scoring v1, issue #55) ------------------ */

  // The selected voice's target notes for the current loop window, in transport
  // seconds. SAME beat×tempo math as buildScopeLane/scheduleAll, so a target's
  // [startSec,endSec] lines up exactly with the sung samples' Transport.seconds.
  // `measure` (printed measure number) rides along so scoreNotes()'s details[]
  // can say "m 12" — the report strip's worst-spots grouping (see worstSpots).
export function buildScoreTargets() {
    if (!parsed) return [];
    const spb = 60 / Number(el.bpm.value);
    const from = clampMeasure(Number(el.loopFrom.value));
    const to = clampMeasure(Number(el.loopTo.value));
    const { start: winStart, end: winEnd } = measureBeatRange(from, to);
    const sel = parsed.parts.find((p) => p.voiceKey === selectedVoice);
    if (!sel) return [];
    return sel.notes
      .filter((n) => n.startBeat >= winStart - 1e-6 && n.startBeat < winEnd - 1e-6)
      .map((n) => ({
        midi: n.midi,
        startSec: (n.startBeat - winStart) * spb,
        endSec: (n.startBeat - winStart + n.durBeat) * spb,
        lyric: n.lyric || null,
        measure: n.measure,
      }));
  }

  // Strictness preset (issue #55): two named presets, persisted so a singer's
  // choice survives reload. `currentScoreOpts()` feeds straight into
  // scoreNotes()'s opts param — this is the ONLY place strictness plugs in.
export function loadStrictness() {
    try {
      const v = localStorage.getItem(STRICTNESS_KEY);
      if (v === 'strict' || v === 'relaxed') scoringStrictness = v;
    } catch (e) { /* storage disabled — default (relaxed) stands */ }
  }
  function currentScoreOpts() {
    const presets = window.ChanterScoring && window.ChanterScoring.PRESETS;
    return (presets && presets[scoringStrictness]) || null;
  }
export function setStrictness(s) {
    scoringStrictness = (s === 'strict') ? 'strict' : 'relaxed';
    try { localStorage.setItem(STRICTNESS_KEY, scoringStrictness); } catch (e) { /* non-fatal */ }
    updateStrictnessUI();
  }
export function updateStrictnessUI() {
    if (!el.strictnessPicker) return;
    [...el.strictnessPicker.children].forEach((b) =>
      b.classList.toggle('active', b.dataset.strictness === scoringStrictness));
  }

  // Score the CURRENT LAP's accumulated samples (practiceSamples) against the
  // loop's target notes, record it as lap `currentLapNum`, roll the running
  // best, paint the status line + report strip, and append one per-lap
  // history entry. Called from TWO places: onLapWrap() (a completed lap,
  // mid-session) and stop() (the session's final/only lap, possibly partial).
  // Samples-first check keeps this genuinely zero-cost with the mic off (no
  // buildScoreTargets() call at all when there is nothing to score).
  function scoreCurrentLap() {
    if (!window.ChanterScoring) return false;
    const samples = practiceSamples;
    if (!samples.length) return false;
    const targets = buildScoreTargets();
    if (!targets.length) return false;

    const opts = currentScoreOpts();
    const result = window.ChanterScoring.scoreNotes(targets, samples, opts);
    const lap = currentLapNum;
    if (result.hitPct > bestLapHitPct) bestLapHitPct = result.hitPct;
    const entry = Object.assign({ lap: lap, best: bestLapHitPct }, result);
    sessionLaps.push(entry);
    // lastScore() exposes the latest lap WITH the running laps[] alongside —
    // a shallow copy (not the live `entry`) so a caller mutating what
    // lastScore() returned can't corrupt sessionLaps' own bookkeeping copy.
    lastScoreResult = Object.assign({}, entry, { laps: sessionLaps });

    // Loop sessions get the compact "Lap N: X% · best Y%" line (the report
    // strip carries the detail); a single non-loop play-through keeps the
    // original spike wording verbatim — no regression there (issue #55 verify d).
    setStatus(el.loopOn.checked
      ? `Lap ${lap}: ${result.hitPct}% · best ${bestLapHitPct}%`
      : window.ChanterScoring.summaryLine(result));
    try {
      // eslint-disable-next-line no-console
      console.table(result.details.map((d) => ({
        '#': d.index, midi: d.midi, lyric: d.lyric, m: d.measure,
        start: +d.startSec.toFixed(2), end: +d.endSec.toFixed(2),
        result: d.result, coverage: d.coverage, 'mean¢': d.meanCents, samples: d.samples,
      })));
    } catch (e) { /* console.table absent — ignore */ }

    appendPracticeHistory({
      ts: Date.now(),
      pieceId: currentPieceId,
      voice: selectedVoice,
      loopFrom: clampMeasure(Number(el.loopFrom.value)),
      loopTo: clampMeasure(Number(el.loopTo.value)),
      verse: activeVerse,
      lap: lap,
      strictness: scoringStrictness,
      totals: {
        notes: result.notes, hit: result.hit, flat: result.flat,
        sharp: result.sharp, missed: result.missed, hitPct: result.hitPct,
      },
    });

    showReport(entry);
    return true;
  }

  function appendPracticeHistory(entry) {
    try {
      const raw = localStorage.getItem(PRACTICE_HISTORY_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      const list = Array.isArray(arr) ? arr : [];
      list.push(entry);
      // cap at ~200 entries (drop oldest)
      while (list.length > 200) list.shift();
      localStorage.setItem(PRACTICE_HISTORY_KEY, JSON.stringify(list));
    } catch (e) { /* storage disabled/full — non-fatal */ }
  }

  /* ---------- Lightweight post-lap report strip (issue #55) ------------- *
   * A small, dismissible, non-modal strip (NOT the rich per-note-coloring
   * panel — that's deferred to #60 after modularization): the lap's totals +
   * up to 3 "worst spots" (measures with the most non-hit notes). Tapping a
   * spot loops that measure's neighborhood, reusing the same loop-input +
   * render/park machinery jumpToSection already relies on.
   */

  /* ---------- Per-note score coloring toggle (issue #79) -------------- *
   * The "Show on score" chip in the report head paints this lap's scored
   * noteheads by verdict onto the notation (loader.applyScoreColoring), then a
   * single requestRender(). Per-report: reset OFF for every fresh report, cleared
   * on the next Play / voice / verse / piece switch (all of which restore the
   * gold/dim baseline — see loader). The chip re-syncs from loader's flag via the
   * 'chanterlab:scorecoloring' event, so switches made elsewhere update it too. */
  const colorToggleEl = document.getElementById('scoreColorToggle');
  const colorKeyEl = document.getElementById('scoreColorKey');

  // Build the little verdict legend once, straight from loader's VERDICT_TINTS
  // (single source of truth for the four colors).
  function buildColorKey() {
    if (!colorKeyEl || colorKeyEl.childElementCount) return;
    [['hit', 'Hit'], ['flat', 'Flat'], ['sharp', 'Sharp'], ['missed', 'Missed']].forEach(([k, label]) => {
      const item = document.createElement('span');
      item.className = 'ck-item';
      const dot = document.createElement('span');
      dot.className = 'ck-dot';
      dot.style.background = VERDICT_TINTS[k];
      const t = document.createElement('span');
      t.className = 'ck-lbl';
      t.textContent = label;
      item.append(dot, t);
      colorKeyEl.appendChild(item);
    });
  }

  // Reflect loader's coloring flag on the chip + legend (called on every toggle
  // and on the change event).
  function syncColoringChip() {
    if (!colorToggleEl) return;
    const on = scoreColoringActive();
    colorToggleEl.classList.toggle('on', on);
    colorToggleEl.setAttribute('aria-pressed', on ? 'true' : 'false');
    colorToggleEl.textContent = on ? '🎨 On score' : '🎨 Show on score';
    if (colorKeyEl) colorKeyEl.hidden = !on;
  }

  // Chip tap: paint / clear the latest lap's verdicts on the score.
  export function toggleScoreColoring() {
    const details = lastScoreResult && lastScoreResult.details;
    if (!details || !details.length) return scoreColoringActive();
    if (scoreColoringActive()) {
      clearScoreColoring();          // restore gold/dim baseline + render
    } else {
      applyScoreColoring(details);   // overlay verdict tints on the model…
      requestRender();               // …then one render (deferred if mid-playback)
    }
    syncColoringChip();
    return scoreColoringActive();
  }

  function showReport(entry) {
    if (reportDismissed || !el.scoreReport) return;
    // Calm Surface (#73/§4): the report floats at the transport's doorstep.
    const spots = (window.ChanterScoring && window.ChanterScoring.worstSpots)
      ? window.ChanterScoring.worstSpots(entry, 3) : [];
    if (el.scoreReportTotals) {
      // Looping sessions append the running best (§4); a single play-through omits
      // it (there is no "best" to compare a lone lap against).
      const best = (el.loopOn && el.loopOn.checked && entry.best >= 0)
        ? ` · best ${entry.best}%` : '';
      el.scoreReportTotals.textContent =
        `Lap ${entry.lap}: ${entry.hit} hit · ${entry.flat} flat · ${entry.sharp} sharp · ` +
        `${entry.missed} missed of ${entry.notes} (${entry.hitPct}%)${best}`;
    }
    if (el.scoreReportSpots) {
      el.scoreReportSpots.innerHTML = '';
      if (!spots.length) {
        const p = document.createElement('div');
        p.className = 'spot-row spot-empty';
        p.textContent = 'Clean lap — no rough spots.';
        el.scoreReportSpots.appendChild(p);
      } else {
        spots.forEach((s) => {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'spot-row';
          b.title = `Loop measure ${s.measure} to drill this spot`;
          const bits = [];
          if (s.missed) bits.push(`${s.missed} missed`);
          if (s.flat) bits.push(`${s.flat} flat`);
          if (s.sharp) bits.push(`${s.sharp} sharp`);
          const m = document.createElement('span');
          m.className = 'spot-m'; m.textContent = 'm ' + s.measure;
          const d = document.createElement('span');
          d.className = 'spot-detail'; d.textContent = bits.join(' · ');
          b.append(m, d);
          b.addEventListener('click', () => loopWorstSpot(s.measure));
          el.scoreReportSpots.appendChild(b);
        });
      }
    }
    // Per-note coloring (issue #79): each report is a fresh, OFF-by-default
    // overlay. Restore the baseline if a previous report left tints painted,
    // then show the chip only when this lap actually scored notes.
    if (scoreColoringActive()) clearScoreColoring();
    buildColorKey();
    if (colorToggleEl) colorToggleEl.hidden = !(entry && entry.details && entry.details.length);
    syncColoringChip();
    el.scoreReport.hidden = false;
  }

  function hideReport() {
    if (el.scoreReport) el.scoreReport.hidden = true;
  }

  // Set the loop to a ±1-measure neighborhood around a worst-spot measure and
  // park the cursor there (stopping playback first if needed) so the singer
  // can immediately re-Play just that spot. Mirrors jumpToSection's pattern.
  function loopWorstSpot(measure) {
    if (!parsed) return;
    const from = clampMeasure(measure - 1);
    const to = clampMeasure(measure + 1);
    if (playState !== 'stopped') stop();
    ensureRenderWindow(from, to);
    el.loopFrom.value = from;
    el.loopTo.value = to;
    el.loopOn.checked = true;
    buildScopeLane();
    parkCursorAtWindowStart();
    hideReport();
  }

/* ---------- Scoring-session lifecycle (called by transport.js) --------- */
// Start a fresh sample buffer + lap session and arm the score for this
// play→end/stop cycle (was inline in startPlayback).
export function beginScoringSession() {
  practiceSamples = [];
  sessionLaps = [];
  currentLapNum = 1;
  bestLapHitPct = -1;
  scoringArmed = true;
  scoreSummaryShown = false;
  reportDismissed = false;
  hideReport();
  // Next Play restores normal coloring (issue #79): drop any verdict overlay
  // left on from the previous lap's report. clearScoreColoring is a no-op (no
  // wasted render) when nothing was painted — the common mic-off path. Runs
  // while still 'stopped' (startPlayback sets 'playing' after this), so the
  // baseline repaints immediately; the chip re-syncs via the change event.
  clearScoreColoring();
  syncColoringChip();
}

// Score the finished lap (if armed) and roll the sample buffer to the next lap.
export function scoreLapAndRoll() {
  if (scoringArmed) scoreCurrentLap();
  practiceSamples = [];
  currentLapNum += 1;
}

// Score the final/partial lap once per armed cycle (called by stop). Returns
// whether a summary was produced (so stop keeps it on the status line).
export function finalizeScoringOnStop() {
  let scored = false;
  if (scoringArmed) { scoringArmed = false; scored = scoreCurrentLap(); }
  if (scored) scoreSummaryShown = true;
  return scored;
}

// Dismiss the report strip (X button); sticks until the next Play.
export function dismissReport() { reportDismissed = true; hideReport(); }

// Wire the "Show on score" chip and keep it synced with loader's coloring flag
// (fires on toggles here AND on clears triggered by voice/verse/piece switches).
if (colorToggleEl) colorToggleEl.addEventListener('click', toggleScoreColoring);
document.addEventListener('chanterlab:scorecoloring', syncColoringChip);

