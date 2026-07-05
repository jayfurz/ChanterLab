/* ChanterScoring — pure, dependency-free per-note hit detection.
 * Graduated from the #49 spike to Scoring v1 for issue #55 (per-lap scoring +
 * a worst-spots helper + strictness presets); the core note-scoring model is
 * unchanged from the spike.
 *
 * Loaded in the browser (attaches window.ChanterScoring) AND importable in node
 * (module.exports) so the unit tests can drive the exact same code the app runs.
 * No DOM, no audio, no Tone — just arithmetic over target notes + pitch samples.
 *
 *   scoreNotes(targets, pitchSamples, opts) -> { notes, hit, flat, sharp, missed,
 *                                                hitPct, details:[...] }
 *   worstSpots(result, limit) -> the `limit` (default 3) measures with the most
 *                                non-hit notes, sorted worst-first — for the
 *                                lightweight post-lap report (issue #55).
 *   PRESETS.relaxed / PRESETS.strict — opts objects for the strictness toggle.
 *
 * INPUTS
 *   targets:      [{ midi, startSec, endSec, lyric?, measure? }]  — the loop's
 *                 selected-voice notes, derived from beat×tempo exactly as
 *                 playback schedules them. `measure` (printed measure number)
 *                 is optional — passed through to details[].measure so a
 *                 caller can group results by measure (see worstSpots); scoring
 *                 itself never reads it.
 *   pitchSamples: [{ tSec, midi }]  — the singer's VOICED pitch estimates in
 *                 transport seconds (unvoiced frames simply produce no sample).
 *                 `midi` is the raw sung pitch (float); octave folding happens here.
 *
 * SCORING MODEL (see per-rule notes below)
 *   - octave-tolerant: each sample is folded to the octave nearest its target
 *     before the cents error is measured, so a singer an octave off still hits.
 *   - a note is HIT when >= minCoverage of its VOICED time is within ±centsTol.
 *   - FLAT / SHARP when covered-but-out, split by which side holds more voiced time.
 *   - MISSED when too little voiced audio landed in the note at all.
 *
 * THE DROPOUT / COVERAGE DECISION (the load-bearing call for this spike)
 *   Coverage's denominator is VOICED time, not the note's clock duration. Each
 *   voiced sample represents the forward slice of time until the next sample,
 *   capped at `maxGap` (default 50 ms ≈ 3 frames). A gap larger than maxGap is a
 *   detector DROPOUT: the sample before it is credited only one nominal frame, so
 *   the dropout's time is excluded from BOTH numerator and denominator. Net effect:
 *   we grade how in-tune the audio we actually heard was, and pitch-tracker
 *   dropouts neither help nor hurt the coverage ratio. A separate absolute floor
 *   (`minVoicedSec`) is the ONLY place total silence counts against the singer —
 *   that is what turns a note MISSED.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.ChanterScoring = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DEFAULTS = {
    centsTol: 50,       // ± tolerance, in cents, for "in tune"
    minCoverage: 0.5,   // fraction of voiced time in-tune required for a HIT
    attackGrace: 0.10,  // seconds of note-start ignored (attack transient)
    maxGap: 0.05,       // sample gaps wider than this are dropouts (excluded)
    frameNominal: 0.016,// slice a lone / pre-dropout / final sample represents (~1 frame @60fps)
    minVoicedSec: 0.05, // absolute voiced-time floor below which a note is MISSED
    graceFrac: 0.4,     // grace never eats more than this fraction of a (short) note
  };

  function opt(opts, key) {
    return (opts && opts[key] != null) ? opts[key] : DEFAULTS[key];
  }

  // Fold a sung midi to the octave nearest `target`, then return signed cents.
  function centsToTarget(sungMidi, targetMidi) {
    var k = Math.round((sungMidi - targetMidi) / 12);
    return (sungMidi - 12 * k - targetMidi) * 100;
  }

  function scoreOne(target, samples, cfg) {
    var startSec = target.startSec;
    var endSec = target.endSec;
    var dur = Math.max(0, endSec - startSec);

    // Attack grace: skip the note's first `attackGrace` seconds, but never more
    // than graceFrac of the note — so a 120 ms note is still (mostly) scored.
    var grace = Math.min(cfg.attackGrace, dur * cfg.graceFrac);
    var scoredStart = startSec + grace;
    var scoredEnd = endSec;
    var scoredDur = Math.max(0, scoredEnd - scoredStart);

    // Voiced samples inside the scored window, in time order, octave-folded.
    var win = [];
    for (var i = 0; i < samples.length; i++) {
      var s = samples[i];
      var t = (s.tSec != null ? s.tSec : s.t);
      var m = s.midi;
      if (t == null || !isFinite(t) || !isFinite(m) || m <= 0) continue;
      if (t < scoredStart || t >= scoredEnd) continue;
      win.push({ t: t, cents: centsToTarget(m, target.midi) });
    }
    win.sort(function (a, b) { return a.t - b.t; });

    // Forward-slice integration (see DROPOUT decision in the file header).
    var voiced = 0, inTune = 0, flat = 0, sharp = 0, centsWeighted = 0;
    for (var j = 0; j < win.length; j++) {
      var gap = (j < win.length - 1) ? (win[j + 1].t - win[j].t) : Infinity;
      var slice = (gap <= cfg.maxGap) ? gap : cfg.frameNominal; // dropout/last → 1 nominal frame
      if (win[j].t + slice > scoredEnd) slice = Math.max(0, scoredEnd - win[j].t);
      var c = win[j].cents;
      voiced += slice;
      centsWeighted += slice * c;
      if (Math.abs(c) <= cfg.centsTol) inTune += slice;
      else if (c < 0) flat += slice;
      else sharp += slice;
    }

    // MISSED gate: an absolute voiced-time floor, relaxed for ultra-short notes
    // so a single frame can still register an attempt.
    var missedFloor = Math.min(cfg.minVoicedSec, Math.max(cfg.frameNominal, scoredDur * 0.5));
    var result, coverage;
    if (win.length === 0 || voiced < missedFloor) {
      result = 'missed';
      coverage = 0;
    } else {
      coverage = inTune / voiced;
      if (coverage >= cfg.minCoverage) result = 'hit';
      else result = (flat >= sharp) ? 'flat' : 'sharp';
    }

    return {
      midi: target.midi,
      lyric: target.lyric != null ? target.lyric : null,
      measure: target.measure != null ? target.measure : null,
      startSec: startSec,
      endSec: endSec,
      result: result,
      coverage: Math.round(coverage * 100) / 100,
      voicedSec: Math.round(voiced * 1000) / 1000,
      scoredSec: Math.round(scoredDur * 1000) / 1000,
      samples: win.length,
      meanCents: win.length ? Math.round(centsWeighted / (voiced || 1)) : null,
    };
  }

  function scoreNotes(targets, pitchSamples, opts) {
    var cfg = {
      centsTol: opt(opts, 'centsTol'),
      minCoverage: opt(opts, 'minCoverage'),
      attackGrace: opt(opts, 'attackGrace'),
      maxGap: opt(opts, 'maxGap'),
      frameNominal: opt(opts, 'frameNominal'),
      minVoicedSec: opt(opts, 'minVoicedSec'),
      graceFrac: opt(opts, 'graceFrac'),
    };
    var tg = Array.isArray(targets) ? targets : [];
    var sp = Array.isArray(pitchSamples) ? pitchSamples : [];

    var details = [];
    var tot = { hit: 0, flat: 0, sharp: 0, missed: 0 };
    for (var i = 0; i < tg.length; i++) {
      var d = scoreOne(tg[i], sp, cfg);
      d.index = i;
      details.push(d);
      tot[d.result] += 1;
    }
    var notes = tg.length;
    return {
      notes: notes,
      hit: tot.hit,
      flat: tot.flat,
      sharp: tot.sharp,
      missed: tot.missed,
      hitPct: notes ? Math.round((tot.hit / notes) * 100) : 0,
      details: details,
    };
  }

  // "Scored 24 notes: 18 hit · 3 flat · 1 sharp · 2 missed (75%)"
  function summaryLine(r) {
    if (!r || !r.notes) return 'No target notes in this loop to score.';
    return 'Scored ' + r.notes + ' notes: ' +
      r.hit + ' hit · ' + r.flat + ' flat · ' + r.sharp + ' sharp · ' +
      r.missed + ' missed (' + r.hitPct + '%)';
  }

  // Strictness presets (issue #55). `relaxed` is deliberately an empty object
  // — scoreNotes()'s own opt() fallback already resolves every key to
  // DEFAULTS when absent, so `{}` and "the historical no-opts call" score
  // identically (no behavior change for existing callers/history rows).
  var PRESETS = {
    relaxed: {},
    strict: { centsTol: 35, minCoverage: 0.75 },
  };

  // Group a scored result's non-hit notes by measure and return the `limit`
  // worst (most non-hit notes first, ties broken by ascending measure) — the
  // "worst spots" the post-lap report points a singer at. Notes without a
  // `measure` (targets that omitted it) are skipped: there is nothing to
  // group them under. Pure function of `result.details`; safe to call with
  // any scoreNotes() output, including opts variants.
  function worstSpots(result, limit) {
    limit = limit == null ? 3 : limit;
    var details = (result && Array.isArray(result.details)) ? result.details : [];
    var byMeasure = {};
    var order = [];
    for (var i = 0; i < details.length; i++) {
      var d = details[i];
      if (d.measure == null || d.result === 'hit') continue;
      var key = d.measure;
      if (!byMeasure[key]) {
        byMeasure[key] = { measure: key, bad: 0, flat: 0, sharp: 0, missed: 0 };
        order.push(key);
      }
      byMeasure[key].bad += 1;
      byMeasure[key][d.result] += 1;
    }
    var spots = order.map(function (k) { return byMeasure[k]; });
    spots.sort(function (a, b) { return b.bad - a.bad || a.measure - b.measure; });
    return spots.slice(0, limit);
  }

  return {
    scoreNotes: scoreNotes,
    summaryLine: summaryLine,
    worstSpots: worstSpots,
    centsToTarget: centsToTarget,
    DEFAULTS: DEFAULTS,
    PRESETS: PRESETS,
  };
}));
