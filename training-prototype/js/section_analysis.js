/* SectionCheckAnalysis — pure, dependency-free score-informed salience
 * analysis for the post-hoc ensemble "Section check" (issue #90).
 *
 * A direct JS port of the #84 spike's detector (docs/design/MULTIPITCH-SPIKE.md
 * §2.2): the app KNOWS the score, so multiparty analysis collapses to per-part
 * presence + intonation verification. For every analysis frame and every part
 * with an expected pitch, harmonic salience is measured at k·F0 (k = 1..6)
 * inside ±70-cent search bands; bands where another part's plausibly-strong
 * harmonic lands are CONTESTED and excluded (that is what makes unisons /
 * octaves / twelfths honest abstentions instead of wrong verdicts).
 *
 * Loaded in the browser (attaches window.SectionCheckAnalysis) AND importable
 * in node (module.exports) so the unit tests drive the exact same code the app
 * runs — the same dual-mode pattern as scoring.js. No DOM, no audio API, no
 * Tone — just arithmetic over PCM samples + expected-note timelines.
 *
 * INPUTS (all times are CLIP seconds — the caller owns the transport→clip
 * alignment; see js/section_check.js and `mapTransportToClip` below):
 *   samples:     Float32Array (or number[]) mono PCM
 *   sampleRate:  Hz
 *   parts:       [{ key, name, notes:[{ midi, startSec, endSec, measure }] }]
 *                notes non-overlapping within a part, sorted or not (sorted here)
 *
 * OUTPUTS
 *   analyzeTake(...) -> { parts:[{ key, name, notes:[{ midi, measure, startSec,
 *     endSec, result:'ok'|'flat'|'sharp'|'missing'|'abstain', cents, presenceDb,
 *     framesMeasured, framesMasked }] }], framesAnalyzed, sampleRate }
 *   aggregateSections(analysis, sections) -> per-piece-section × per-part
 *     verdict rows ('in-tune' | 'flat' | 'sharp' | 'not-heard' |
 *     'not-attributable' | 'no-notes') plus an overall (whole-take) row set.
 *
 * PER-NOTE CLASSIFICATION (spike §2.2 step 6, thresholds in DEFAULTS):
 *   abstain  — <2 usable frames, or >50% of the note's frames fully masked
 *   missing  — median presence < 5 dB over the local floor, AND the median
 *              frame measured ≥2 free bands (you cannot prove absence from one)
 *   flat/sharp — |median cents| > 15 (the spike's "off-pitch", split by sign)
 *   ok       — heard, and not provably off
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.SectionCheckAnalysis = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DEFAULTS = {
    // framing (spike: 4096-sample Hann @48k = 85 ms, hop 1024 ≈ 47 Hz, rFFT
    // zero-padded to 8192 for interpolation headroom)
    winSize: 4096,
    hopSize: 1024,
    fftSize: 8192,
    // harmonic search
    maxHarmonic: 6,        // k = 1..6 of the expected F0
    bandCents: 70,         // search band = k·F0 × 2^(±70/1200)
    skirtBins: 2,          // collision skirt margin, in ANALYSIS-WINDOW bins
                           // (sr/winSize — the Hann mainlobe scale, so a peak
                           // just outside the band still counts as contested)
    smearCents: 25,        // extra collision margin for the INTERFERER's own
                           // pitch wander (vibrato ±20c + jitter — the spike's
                           // voice model itself wanders this much): a harmonic
                           // that can WANDER into the band contests it. Errs
                           // toward abstention, never toward a wrong verdict.
    interfererMaxMult: 4,  // interferer harmonic index jj ≤ 4k is "plausibly strong"
    floorCents: 300,       // local floor = median |FFT| within ±300 cents
    // note-edge gates (reverb smear / attack transients — spike: 90/60 ms).
    // These also absorb the small unmodeled capture latencies of the post-hoc
    // path (mic input buffering, room time-of-flight) — see section_check.js.
    edgeGateStartSec: 0.09,
    edgeGateEndSec: 0.06,
    // per-band intonation gating (spike §2.2 step 5)
    bandGateDb: 6,         // a band's cents vote needs >6 dB over the floor
    strongWithinDb: 30,    // ... and within 30 dB of the strongest usable harmonic
    clusterCents: 12,      // votes must agree within ±12c of their median
    loneHarmMax: 3,        // a LONE vote is only trusted from k ≤ 3 ...
    loneHarmDb: 15,        // ... at > 15 dB over the floor
    // per-note classification
    presenceMissingDb: 5,  // median presence below this ⇒ candidate "missing"
    minBandsForMissing: 2, // a missing verdict needs ≥2 measured bands
    presenceVoteDb: 10,    // intonation verdicts need at least this much
                           // presence — the [missing..vote) gray zone abstains
                           // (too weak to accuse, too strong to declare absent)
    minCentsFrac: 0.4,     // ... and a cents consensus on ≥ this fraction of
                           // measured frames (random noise votes agree rarely)
    offPitchCents: 15,     // |median cents| beyond this ⇒ flat / sharp
    maskedAbstainFrac: 0.5,// a note >50%-masked is an abstention
    minFramesPerNote: 2,
    // section aggregation
    notHeardFrac: 0.5,     // ≥ this fraction of scored notes missing ⇒ "not heard"
    lowConfidenceNotes: 3, // fewer scored notes than this ⇒ low-confidence flag
  };

  function opt(opts, key) {
    return (opts && opts[key] != null) ? opts[key] : DEFAULTS[key];
  }
  function config(opts) {
    var cfg = {};
    for (var k in DEFAULTS) cfg[k] = opt(opts, k);
    return cfg;
  }

  var midiToFreq = function (m) { return 440 * Math.pow(2, (m - 69) / 12); };

  function median(arr) {
    if (!arr.length) return null;
    var a = arr.slice().sort(function (x, y) { return x - y; });
    var mid = a.length >> 1;
    return (a.length % 2) ? a[mid] : (a[mid - 1] + a[mid]) / 2;
  }

  /* ---------- FFT (iterative radix-2, cached tables) -------------------- */

  var fftCache = {};
  function fftTables(n) {
    var t = fftCache[n];
    if (t) return t;
    var levels = 0;
    while ((1 << levels) < n) levels++;
    if ((1 << levels) !== n) throw new Error('fft size must be a power of 2');
    var rev = new Uint32Array(n);
    for (var i = 0; i < n; i++) {
      var x = i, r = 0;
      for (var j = 0; j < levels; j++) { r = (r << 1) | (x & 1); x >>= 1; }
      rev[i] = r;
    }
    var cos = new Float64Array(n / 2), sin = new Float64Array(n / 2);
    for (i = 0; i < n / 2; i++) {
      cos[i] = Math.cos(-2 * Math.PI * i / n);
      sin[i] = Math.sin(-2 * Math.PI * i / n);
    }
    t = { rev: rev, cos: cos, sin: sin };
    fftCache[n] = t;
    return t;
  }

  function fftInPlace(re, im) {
    var n = re.length;
    var t = fftTables(n);
    var rev = t.rev, cos = t.cos, sin = t.sin;
    for (var i = 0; i < n; i++) {
      var j = rev[i];
      if (j > i) {
        var tr = re[i]; re[i] = re[j]; re[j] = tr;
        var ti = im[i]; im[i] = im[j]; im[j] = ti;
      }
    }
    for (var size = 2; size <= n; size <<= 1) {
      var half = size >> 1, step = n / size;
      for (var base = 0; base < n; base += size) {
        for (var k = 0, tw = 0; k < half; k++, tw += step) {
          var l = base + k, r = base + k + half;
          var wr = cos[tw], wi = sin[tw];
          var xr = re[r] * wr - im[r] * wi;
          var xi = re[r] * wi + im[r] * wr;
          re[r] = re[l] - xr; im[r] = im[l] - xi;
          re[l] += xr; im[l] += xi;
        }
      }
    }
  }

  var hannCache = {};
  function hann(n) {
    var w = hannCache[n];
    if (w) return w;
    w = new Float64Array(n);
    for (var i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1));
    hannCache[n] = w;
    return w;
  }

  /* ---------- per-frame, per-part salience measurement ------------------- */

  var LN10_20 = 20 / Math.LN10;   // ln → dB
  var EPS = 1e-12;

  // Measure one part's harmonic salience in one magnitude spectrum.
  //   mag: Float64Array of |FFT| for bins 0..nfft/2
  //   f0:  the part's expected fundamental (Hz)
  //   others: expected F0s of the OTHER simultaneously-active parts (Hz)
  // Returns { masked:true } when every band is contested, else
  // { masked:false, presenceDb, nBands, cents|null }.
  function measurePart(mag, nfft, sampleRate, f0, others, cfg) {
    var binHz = sampleRate / nfft;
    var ratio = Math.pow(2, cfg.bandCents / 1200);
    var floorRatio = Math.pow(2, cfg.floorCents / 1200);
    // Skirt in ANALYSIS-WINDOW bins (sr/winSize), NOT padded-FFT bins: the
    // window's mainlobe half-width is 2 window-bins, so an interferer peak up
    // to that far outside the band still floods it and must contest it.
    var skirt = cfg.skirtBins * (sampleRate / cfg.winSize);
    var nyquist = sampleRate / 2;
    var free = [];

    for (var k = 1; k <= cfg.maxHarmonic; k++) {
      var fc = k * f0;
      var lo = fc / ratio, hi = fc * ratio;
      if (hi >= nyquist) break;

      // Collision mask (spike §2.2 step 2): contested if another part's
      // plausibly-strong harmonic (nearest-integer test, jj ≤ 4k) lands within
      // the band + a skirt (window mainlobe + the interferer's own plausible
      // pitch wander). Contested bands are excluded from ALL per-part math —
      // that honesty is the whole trick.
      var contested = false;
      for (var q = 0; q < others.length; q++) {
        var jj = Math.round(fc / others[q]);
        if (jj < 1 || jj > cfg.interfererMaxMult * k) continue;
        var fi = jj * others[q];
        var smear = fi * (Math.pow(2, cfg.smearCents / 1200) - 1);
        if (fi >= lo - skirt - smear && fi <= hi + skirt + smear) { contested = true; break; }
      }
      if (contested) continue;

      var b0 = Math.max(1, Math.ceil(lo / binHz));
      var b1 = Math.min(mag.length - 2, Math.floor(hi / binHz));
      if (b1 < b0) continue;

      // Peak bin + parabolic interpolation on log-magnitude → (freq, dB).
      var pb = b0;
      for (var b = b0; b <= b1; b++) if (mag[b] > mag[pb]) pb = b;
      // The measurement must be an INTERIOR local maximum: an argmax sitting
      // on the band boundary is the skirt of energy whose true peak lies
      // OUTSIDE the band (e.g. a neighbor part's vibrato-smeared harmonic
      // just past the collision skirt) — measuring it would misattribute that
      // energy to this part. Skip the band for this frame instead.
      if (pb === b0 || pb === b1) continue;
      var l1 = Math.log(mag[pb - 1] + EPS);
      var l2 = Math.log(mag[pb] + EPS);
      var l3 = Math.log(mag[pb + 1] + EPS);
      var den = l1 - 2 * l2 + l3;
      var d = den ? 0.5 * (l1 - l3) / den : 0;
      if (!(d > -1 && d < 1)) d = 0;
      var freq = (pb + d) * binHz;
      var peakDb = LN10_20 * (l2 - 0.25 * (l1 - l3) * d);

      // Local floor = median |FFT| within ±300 cents of the band center.
      var f0b = Math.max(1, Math.ceil((fc / floorRatio) / binHz));
      var f1b = Math.min(mag.length - 1, Math.floor((fc * floorRatio) / binHz));
      var floorVals = [];
      for (b = f0b; b <= f1b; b++) floorVals.push(mag[b]);
      var floorMag = median(floorVals);
      if (floorMag == null) continue;
      var floorDb = LN10_20 * Math.log(floorMag + EPS);
      var dbOver = peakDb - floorDb;

      free.push({
        k: k,
        dbOver: dbOver,
        peakDb: peakDb,
        cents: 1200 * Math.log2(freq / fc),
      });
    }

    if (!free.length) return { masked: true };

    // Presence = mean of the top-3 per-band dB-over-floor (timbres owe you no
    // particular harmonic — spike §2.2 step 4).
    var overs = free.map(function (x) { return x.dbOver; }).sort(function (a, b) { return b - a; });
    var nTop = Math.min(3, overs.length);
    var presence = 0;
    for (var i = 0; i < nTop; i++) presence += overs[i];
    presence /= nTop;

    // Intonation (spike §2.2 step 5): candidate votes gated >6 dB over floor
    // and within 30 dB of the strongest usable harmonic; votes must AGREE
    // (cluster within ±12c of their median); a lone vote is only trusted from
    // a solid low harmonic. Estimate = weighted mean, weight = k × dB (higher
    // harmonics carry more Hz per cent).
    var maxPeakDb = -Infinity;
    for (i = 0; i < free.length; i++) if (free[i].peakDb > maxPeakDb) maxPeakDb = free[i].peakDb;
    var cand = free.filter(function (x) {
      return x.dbOver > cfg.bandGateDb && (maxPeakDb - x.peakDb) <= cfg.strongWithinDb;
    });
    var cents = null;
    var loneOk = function (x) { return x.k <= cfg.loneHarmMax && x.dbOver > cfg.loneHarmDb; };
    if (cand.length >= 2) {
      var med = median(cand.map(function (x) { return x.cents; }));
      var kept = cand.filter(function (x) { return Math.abs(x.cents - med) <= cfg.clusterCents; });
      if (kept.length >= 2) {
        var wsum = 0, csum = 0;
        for (i = 0; i < kept.length; i++) {
          var w = kept[i].k * Math.max(0, kept[i].dbOver);
          wsum += w; csum += w * kept[i].cents;
        }
        if (wsum > 0) cents = csum / wsum;
      } else if (kept.length === 1 && loneOk(kept[0])) {
        cents = kept[0].cents;
      }
    } else if (cand.length === 1 && loneOk(cand[0])) {
      cents = cand[0].cents;
    }

    return { masked: false, presenceDb: presence, nBands: free.length, cents: cents };
  }

  /* ---------- take analysis (framewise driver) --------------------------- */

  // Incremental analyzer so the browser can yield to the UI between chunks
  // (createAnalyzer + step(n)); analyzeTake() below is the synchronous
  // convenience wrapper the unit tests use. Same code path either way.
  function createAnalyzer(samples, sampleRate, parts, opts) {
    var cfg = config(opts);
    var winSize = cfg.winSize, hop = cfg.hopSize, nfft = cfg.fftSize;
    if (nfft < winSize) nfft = winSize;
    var win = hann(winSize);
    var re = new Float64Array(nfft);
    var im = new Float64Array(nfft);
    var mag = new Float64Array((nfft >> 1) + 1);

    // Normalize + sort each part's notes; attach per-note accumulators.
    var state = (parts || []).map(function (p) {
      var notes = (p.notes || []).map(function (n) {
        return {
          midi: n.midi,
          measure: n.measure != null ? n.measure : null,
          startSec: n.startSec,
          endSec: n.endSec,
          gs: n.startSec + cfg.edgeGateStartSec,
          ge: n.endSec - cfg.edgeGateEndSec,
          f0: midiToFreq(n.midi),
          framesMasked: 0,
          presences: [],
          nBands: [],
          cents: [],
        };
      }).sort(function (a, b) { return a.startSec - b.startSec; });
      return { key: p.key, name: p.name, notes: notes, ptr: 0 };
    });

    var nFrames = Math.max(0, Math.floor((samples.length - winSize) / hop) + 1);
    var frame = 0;
    var framesAnalyzed = 0;
    var activeNotes = new Array(state.length);
    var activeF0s = new Array(state.length);

    function activeNoteAt(part, tc) {
      // notes are sorted and non-overlapping within a part; advance the pointer
      // past notes whose gated window has closed, then test the current one.
      var notes = part.notes;
      while (part.ptr < notes.length && notes[part.ptr].ge <= tc) part.ptr++;
      var n = notes[part.ptr];
      return (n && n.gs <= tc && tc < n.ge) ? n : null;
    }

    function step(maxFrames) {
      var end = Math.min(nFrames, frame + (maxFrames || nFrames));
      for (; frame < end; frame++) {
        var start = frame * hop;
        var tc = (start + winSize / 2) / sampleRate;

        var anyActive = false;
        for (var pi = 0; pi < state.length; pi++) {
          var note = activeNoteAt(state[pi], tc);
          activeNotes[pi] = note;
          activeF0s[pi] = note ? note.f0 : 0;
          if (note) anyActive = true;
        }
        if (!anyActive) continue;   // expected silence everywhere — skip the FFT

        // windowed frame → zero-padded rFFT → magnitude
        var i;
        for (i = 0; i < winSize; i++) { re[i] = samples[start + i] * win[i]; im[i] = 0; }
        for (i = winSize; i < nfft; i++) { re[i] = 0; im[i] = 0; }
        fftInPlace(re, im);
        for (i = 0; i < mag.length; i++) mag[i] = Math.sqrt(re[i] * re[i] + im[i] * im[i]);
        framesAnalyzed++;

        for (pi = 0; pi < state.length; pi++) {
          var n = activeNotes[pi];
          if (!n) continue;
          var others = [];
          for (var qi = 0; qi < state.length; qi++) {
            if (qi !== pi && activeF0s[qi] > 0) others.push(activeF0s[qi]);
          }
          var m = measurePart(mag, nfft, sampleRate, n.f0, others, cfg);
          if (m.masked) {
            n.framesMasked++;
          } else {
            n.presences.push(m.presenceDb);
            n.nBands.push(m.nBands);
            if (m.cents != null) n.cents.push(m.cents);
          }
        }
      }
      return frame >= nFrames;
    }

    function classify(n) {
      var measured = n.presences.length;
      var total = measured + n.framesMasked;
      var out = {
        midi: n.midi,
        measure: n.measure,
        startSec: n.startSec,
        endSec: n.endSec,
        framesMeasured: measured,
        framesMasked: n.framesMasked,
        presenceDb: measured ? Math.round(median(n.presences) * 10) / 10 : null,
        cents: n.cents.length ? Math.round(median(n.cents) * 10) / 10 : null,
        result: 'abstain',
      };
      if (total < cfg.minFramesPerNote || measured === 0 ||
          n.framesMasked / total > cfg.maskedAbstainFrac) {
        return out;   // abstain — masked or too short to say anything
      }
      if (out.presenceDb < cfg.presenceMissingDb) {
        // Proving absence needs ≥2 free measured bands (spike §2.2 step 4);
        // with fewer, degrade to abstain — never a hard accusation.
        out.result = (median(n.nBands) >= cfg.minBandsForMissing) ? 'missing' : 'abstain';
        return out;
      }
      if (out.presenceDb < cfg.presenceVoteDb) {
        // Gray zone: enough energy that "missing" would be unfair, not enough
        // that an intonation verdict would mean anything (an empty band's
        // peak-over-floor statistic alone sits near the missing gate). The
        // spike's failure discipline is: degrade to NO verdict, never a wrong
        // one — so abstain.
        return out;
      }
      // Intonation verdicts additionally need the per-frame cents consensus to
      // have actually formed on a solid fraction of frames — random noise
      // votes agree only sporadically, a sung note votes nearly every frame.
      var centsFrac = measured ? (n.cents.length / measured) : 0;
      if (out.cents != null && centsFrac >= cfg.minCentsFrac &&
          Math.abs(out.cents) > cfg.offPitchCents) {
        out.result = out.cents < 0 ? 'flat' : 'sharp';
        return out;
      }
      out.result = 'ok';
      return out;
    }

    function finish() {
      return {
        parts: state.map(function (p) {
          return { key: p.key, name: p.name, notes: p.notes.map(classify) };
        }),
        framesAnalyzed: framesAnalyzed,
        framesTotal: nFrames,
        sampleRate: sampleRate,
      };
    }

    return { step: step, finish: finish, totalFrames: nFrames };
  }

  function analyzeTake(samples, sampleRate, parts, opts) {
    var a = createAnalyzer(samples, sampleRate, parts, opts);
    a.step();          // all frames
    return a.finish();
  }

  /* ---------- section aggregation ---------------------------------------- */

  // Verdict for one part over one set of note results (spike session verdict:
  // the per-part median over the notes; "not heard" and "not attributable"
  // framed softly per §3.3's product framing).
  function partVerdict(notes, cfg) {
    var counts = { ok: 0, flat: 0, sharp: 0, missing: 0, abstain: 0 };
    var centsVals = [];
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      counts[n.result] += 1;
      if (n.result !== 'missing' && n.result !== 'abstain' && n.cents != null) {
        centsVals.push(n.cents);
      }
    }
    var scored = counts.ok + counts.flat + counts.sharp + counts.missing;
    var cents = centsVals.length ? Math.round(median(centsVals)) : null;
    var verdict;
    if (!notes.length) verdict = 'no-notes';
    else if (scored === 0) verdict = 'not-attributable';
    else if (counts.missing / scored >= cfg.notHeardFrac) verdict = 'not-heard';
    else if (cents != null && cents < -cfg.offPitchCents) verdict = 'flat';
    else if (cents != null && cents > cfg.offPitchCents) verdict = 'sharp';
    else verdict = 'in-tune';
    return {
      verdict: verdict,
      cents: cents,
      counts: counts,
      scored: scored,
      total: notes.length,
      lowConfidence: verdict !== 'no-notes' && scored > 0 && scored < cfg.lowConfidenceNotes,
    };
  }

  // sections: [{ title, fromMeasure, toMeasure }] in printed-measure numbers
  // (inclusive). Empty/absent ⇒ one "Whole take" section. Notes without a
  // measure land in every section that spans them by time?—no: they are only
  // counted in the overall row (there is nothing to group them under; mirrors
  // worstSpots' handling of measureless targets).
  function aggregateSections(analysis, sections, opts) {
    var cfg = config(opts);
    var parts = (analysis && analysis.parts) || [];
    var secs = (sections && sections.length) ? sections.map(function (s) {
      return {
        title: String(s.title),
        fromMeasure: s.fromMeasure != null ? s.fromMeasure : -Infinity,
        toMeasure: s.toMeasure != null ? s.toMeasure : Infinity,
      };
    }) : [{ title: 'Whole take', fromMeasure: -Infinity, toMeasure: Infinity }];

    var out = secs.map(function (s) {
      return {
        title: s.title,
        fromMeasure: isFinite(s.fromMeasure) ? s.fromMeasure : null,
        toMeasure: isFinite(s.toMeasure) ? s.toMeasure : null,
        parts: parts.map(function (p) {
          var notes = p.notes.filter(function (n) {
            return n.measure != null && n.measure >= s.fromMeasure && n.measure <= s.toMeasure;
          });
          var v = partVerdict(notes, cfg);
          v.key = p.key; v.name = p.name;
          return v;
        }),
      };
    });

    var overall = parts.map(function (p) {
      var v = partVerdict(p.notes, cfg);
      v.key = p.key; v.name = p.name;
      return v;
    });

    return { sections: out, overall: overall };
  }

  /* ---------- transport→clip alignment ----------------------------------- */

  // Build the linear map from transport-schedule seconds to recording-clip
  // seconds from a single anchor captured while the take was rolling:
  //   anchor = { clipSec:      recording elapsed at the anchor instant,
  //              transportSec: Tone.Transport.seconds at the SAME instant,
  //              latencySec:   schedule→audible offset (getDisplayLatency()) }
  // clip(T) = anchor.clipSec + (T − anchor.transportSec) + anchor.latencySec.
  //
  // WHY latencySec is L_out ONLY (the deliberate asymmetry vs live scoring):
  // live scoring back-dates each SAMPLE by L_out + L_in — the SUM is what the
  // calibration wizard actually measured (schedule→audible→sung→DETECTED).
  // Post-hoc there is no detector chain: the clip's sample times are exact, so
  // the L_in leg (detector window + one-euro group delay + the reactive-singer
  // allowance calibration folds in) must NOT be re-applied. What remains of the
  // capture path (mic input buffering, room time-of-flight) is a few tens of ms
  // and is absorbed by the 90/60 ms note-edge gates + per-note medians.
  function mapTransportToClip(anchor) {
    var clipSec = Number(anchor && anchor.clipSec) || 0;
    var transportSec = Number(anchor && anchor.transportSec) || 0;
    var latencySec = Number(anchor && anchor.latencySec) || 0;
    return function (tSec) { return clipSec + (tSec - transportSec) + latencySec; };
  }

  return {
    analyzeTake: analyzeTake,
    createAnalyzer: createAnalyzer,
    aggregateSections: aggregateSections,
    mapTransportToClip: mapTransportToClip,
    midiToFreq: midiToFreq,
    DEFAULTS: DEFAULTS,
    // exposed for focused unit tests
    _internals: {
      fftInPlace: fftInPlace,
      measurePart: measurePart,
      median: median,
      hann: hann,
    },
  };
}));
