/* section_check.js — post-hoc ensemble "Section check" (issue #90, MVP slice
 * of the #84 multipitch spike's GO verdict).
 *
 * After an ensemble take is recorded with the in-app recorder (issue #67, Rec
 * mix at full Voice so the music leg is 0), this module decodes the clip and
 * runs the score-informed salience pass (js/section_analysis.js — the JS port
 * of the spike detector) offline against the loaded piece's notes + bpm, then
 * renders a per-piece-section × per-part report: in tune / flat ~N¢ /
 * sharp ~N¢ / not heard / can't attribute. No worklet changes, no real-time
 * work; a plain-JS pass analyzes a 3-minute take in a few seconds.
 *
 * ── TIMING CONTRACT (how the take is aligned with the score timeline) ──
 *
 * Live scoring aligns SAMPLES to the schedule domain: the scope's time source
 * subtracts L_out (getDisplayLatency: output latency + the per-device nudge)
 * from Tone.Transport.seconds, and scope.js back-dates each voiced sample by
 * L_in (the calibrated "voice response": mic buffer + detector window +
 * one-euro group delay, plus whatever reactive-singer offset the wizard's
 * sing-back measured). Only the SUM L_out + L_in reaches the scorer — that is
 * the calibration invariant js/calibrate.js documents.
 *
 * Post-hoc we go the other way: NOTE windows are mapped into the clip's
 * capture domain. While the take is rolling we capture one anchor —
 * (recording elapsed, Tone.Transport.seconds, getDisplayLatency()) read in the
 * same tick — and map clip(T) = anchorClip + (T − anchorTransport) + L_out.
 * L_out belongs in the map (the choir sings to the AUDIBLE beat, which lags
 * the schedule by L_out on the very device that is recording). L_in does NOT:
 * its detector-chain legs simply don't exist offline (frame times in the
 * decoded clip are exact), so re-applying the live calibration would shift
 * the take by latency it never incurred. The capture legs that do remain
 * (mic input buffering ~10-40 ms, room time-of-flight ~3 ms/m) are absorbed
 * by the analyzer's 90/60 ms note-edge gates and per-note medians. See
 * mapTransportToClip in js/section_analysis.js.
 *
 * Loop takes: the anchor pins ONE lap's linear map; if the loop wraps, later
 * laps land in clip time where no note window is expected, so exactly the
 * anchor lap is analyzed (reported in the result header). The golden path —
 * ⏺ Record, ▶ Play, sing the piece once, ⏹ Stop — is exact.
 *
 * Self-contained: wired from index.html's single Section-check block (a row +
 * this module's script tag); ZERO changes to js/main.js, js/transport.js,
 * scope.js or scoring.js. All shared modules are imported read-only.
 */
import { el, setStatus } from './state.js';
import { parsed, clampMeasure, measureBeatRange } from './model.js';
import { playState, getDisplayLatency } from './transport.js';
import { recordingState } from './recording.js';
import { currentSections } from './sections.js';
import { currentPieceId } from './loader.js';
import './section_analysis.js';   // UMD — attaches window.SectionCheckAnalysis

const A = () => window.SectionCheckAnalysis;

let take = null;          // context captured while the current/last recording rolled
let lastResult = null;    // last { analysis, report, meta } (test hook)
let running = false;
let pollTimer = 0;
let wasRecording = false;

/* ---------- take-context capture (the anchor) ------------------------- */

function safeRecState() {
  try { return recordingState(); } catch (e) { return null; }
}
function transportSecondsSafe() {
  try {
    const s = Tone.Transport.seconds;
    return (typeof s === 'number' && isFinite(s)) ? s : null;
  } catch (e) { return null; }
}

// Snapshot everything the analysis needs at the moment the anchor is taken,
// so stopping playback, editing the loop, or switching pieces afterwards can
// never corrupt the take's frame of reference. Note timing uses EXACTLY
// scheduleAll's math (start = (startBeat − winStart)·spb, dur clamped to
// ≥50 ms and shortened ×0.95) — the same recipe the spike validated against.
function captureTakeContext(recSt) {
  if (!parsed) return null;
  const transportSec = transportSecondsSafe();
  if (transportSec == null) return null;
  const bpm = Number(el.bpm.value);
  const spb = 60 / bpm;
  const from = clampMeasure(Number(el.loopFrom.value));
  const to = clampMeasure(Number(el.loopTo.value));
  const { start: winStart, end: winEnd } = measureBeatRange(from, to);
  const timelines = parsed.parts.map((p) => ({
    key: p.voiceKey,
    name: p.voiceName,
    notes: p.notes
      .filter((n) => n.startBeat >= winStart - 1e-6 && n.startBeat < winEnd - 1e-6)
      .map((n) => {
        const startSec = (n.startBeat - winStart) * spb;
        return {
          midi: n.midi,
          measure: n.measure,
          startSec,
          endSec: startSec + Math.max(0.05, n.durBeat * spb * 0.95),
        };
      }),
  }));
  // Piece sections (manifest or XML-scanned; sections.js exposes the resolved
  // list) clipped to the loop window; < 2 sections ⇒ aggregate as one block.
  const secs = [];
  if (currentSections.length >= 2) {
    for (let i = 0; i < currentSections.length; i++) {
      const s = currentSections[i];
      const next = currentSections[i + 1];
      const sFrom = Math.max(from, Math.round(s.measure) || 1);
      const sTo = Math.min(to, next ? Math.round(next.measure) - 1 : to);
      if (sTo >= sFrom) secs.push({ title: s.title, fromMeasure: sFrom, toMeasure: sTo });
    }
  }
  return {
    pieceId: currentPieceId,
    bpm, from, to,
    loopOn: !!(el.loopOn && el.loopOn.checked),
    totalSec: (winEnd - winStart) * spb,
    timelines,
    sections: secs,
    micOn: !!recSt.micOn,
    musicLeg: recSt.musicGain,   // recording-mix music leg at anchor time (0 = ensemble mode)
    anchor: {
      clipSec: recSt.elapsedMs / 1000,
      transportSec,
      latencySec: getDisplayLatency(),
    },
  };
}

// Lightweight poll (4 Hz): arm a fresh take context on the first tick where a
// recording AND playback are both live. A NEW recording clears the previous
// context (mirrors recording.js's clip lifecycle). No transport/recording
// module is modified — both expose the needed state read-only.
function pollTick() {
  const st = safeRecState();
  if (!st) return;
  if (st.recording && !wasRecording) take = null;   // fresh recording, fresh anchor
  wasRecording = st.recording;
  if (st.recording && !take && playState === 'playing') {
    take = captureTakeContext(st);
    if (take) localStatus('Take anchored — analyze after you stop.');
  }
}

/* ---------- decode + run ---------------------------------------------- */

function decodeAudio(ctx, arrayBuffer) {
  return new Promise((resolve, reject) => {
    try {
      const p = ctx.decodeAudioData(arrayBuffer, resolve, reject);
      if (p && typeof p.then === 'function') p.then(resolve, reject);
    } catch (e) { reject(e); }
  });
}

function downmixMono(audioBuf) {
  const n = audioBuf.length;
  const ch = audioBuf.numberOfChannels;
  if (ch === 1) return audioBuf.getChannelData(0);
  const out = new Float32Array(n);
  for (let c = 0; c < ch; c++) {
    const data = audioBuf.getChannelData(c);
    for (let i = 0; i < n; i++) out[i] += data[i] / ch;
  }
  return out;
}

async function runSectionCheck() {
  if (running) return null;
  const btn = document.getElementById('secCheckBtn');
  const st = safeRecState();
  if (!st) { localStatus('Recorder unavailable.'); return null; }
  if (st.recording) { localStatus('Stop the recording first.'); return null; }
  if (!st.hasClip || !st.clipUrl) {
    localStatus('Record a take first: ⏺ Record, ▶ Play, sing, ⏹ Stop.');
    return null;
  }
  if (!take) {
    localStatus('No anchor — record WHILE the piece plays so the take lines up with the score.');
    return null;
  }
  if (!take.micOn) {
    localStatus('That take was recorded with the mic off — there are no voices in it to check.');
    return null;
  }
  running = true;
  if (btn) btn.disabled = true;
  try {
    localStatus('Decoding the take…');
    await new Promise((r) => setTimeout(r, 30));   // let the status paint
    const resp = await fetch(st.clipUrl);
    const bytes = await resp.arrayBuffer();
    const ctx = Tone.getContext().rawContext;
    const audioBuf = await decodeAudio(ctx, bytes);
    const mono = downmixMono(audioBuf);
    const clipDur = audioBuf.duration;

    // Map every expected note window into clip time and keep the recorded ones.
    const toClip = A().mapTransportToClip(take.anchor);
    let skipped = 0, kept = 0;
    const parts = take.timelines.map((p) => ({
      key: p.key,
      name: p.name,
      notes: p.notes
        .map((n) => ({
          midi: n.midi, measure: n.measure,
          startSec: toClip(n.startSec), endSec: toClip(n.endSec),
        }))
        .filter((n) => {
          const inClip = n.endSec > 0.05 && n.startSec < clipDur - 0.05;
          if (inClip) kept++; else skipped++;
          return inClip;
        }),
    }));
    if (!kept) {
      localStatus('The recording does not overlap the piece timeline — record while it plays.');
      return null;
    }

    // Chunked analysis so the UI stays alive on long takes.
    const analyzer = A().createAnalyzer(mono, audioBuf.sampleRate, parts);
    const CHUNK = 400;
    let done = false, doneFrames = 0;
    while (!done) {
      done = analyzer.step(CHUNK);
      doneFrames += CHUNK;
      const pct = Math.min(100, Math.round(100 * doneFrames / Math.max(1, analyzer.totalFrames)));
      localStatus(`Analyzing… ${pct}%`);
      await new Promise((r) => setTimeout(r, 0));
    }
    const analysis = analyzer.finish();
    const report = A().aggregateSections(analysis, take.sections);
    lastResult = {
      analysis, report,
      meta: {
        pieceId: take.pieceId, bpm: take.bpm, from: take.from, to: take.to,
        loopOn: take.loopOn, musicLeg: take.musicLeg,
        clipDurSec: Math.round(clipDur * 10) / 10,
        notesInClip: kept, notesSkipped: skipped,
        anchor: take.anchor,
      },
    };
    renderReport(lastResult);
    localStatus('');
    setStatus(`Section check: analyzed ${kept} notes over ${Math.round(clipDur)}s of the take.`);
    return lastResult;
  } catch (e) {
    localStatus('Section check failed: ' + ((e && e.message) || e));
    return null;
  } finally {
    running = false;
    if (btn) btn.disabled = false;
  }
}

/* ---------- report rendering ------------------------------------------ */

function localStatus(msg) {
  const s = document.getElementById('secCheckStatus');
  if (s) s.textContent = msg || '';
}

const VERDICT_COLOR = {
  'in-tune': '#8fd694',
  flat: '#ffcc66',
  sharp: '#ffcc66',
  'not-heard': '#ff9d9d',
  'not-attributable': '#9aa0a6',
  'no-notes': '#9aa0a6',
};

function verdictText(v) {
  const n = v.cents != null ? Math.abs(v.cents) : null;
  switch (v.verdict) {
    case 'in-tune': return '✓ in tune' + (v.cents != null ? ` (${v.cents > 0 ? '+' : ''}${v.cents}¢)` : '');
    case 'flat': return `♭ flat ~${n}¢`;
    case 'sharp': return `♯ sharp ~${n}¢`;
    case 'not-heard': return 'not heard';
    case 'not-attributable': return '— can’t attribute';
    default: return '·';
  }
}
function verdictTitle(v) {
  const c = v.counts;
  return `${v.scored} of ${v.total} notes attributable · ` +
    `${c.ok} ok, ${c.flat} flat, ${c.sharp} sharp, ${c.missing} not heard, ${c.abstain} masked`;
}

function cellFor(v) {
  const td = document.createElement('td');
  td.style.cssText = 'padding:4px 8px;border-top:1px solid rgba(255,255,255,0.08);white-space:nowrap;';
  td.style.color = VERDICT_COLOR[v.verdict] || '#9aa0a6';
  td.textContent = verdictText(v) + (v.lowConfidence ? ' *' : '');
  td.title = verdictTitle(v);
  return td;
}

function renderReport(res) {
  const box = document.getElementById('secCheckReport');
  if (!box) return;
  box.innerHTML = '';
  box.hidden = false;
  box.style.cssText = 'margin:6px 0 2px;padding:8px;border:1px solid rgba(255,255,255,0.12);' +
    'border-radius:8px;background:rgba(255,255,255,0.03);font-size:12px;overflow-x:auto;';

  const head = document.createElement('div');
  head.style.cssText = 'color:#9aa0a6;margin-bottom:6px;';
  const caveats = [];
  if (res.meta.loopOn) caveats.push('loop was on — first pass analyzed');
  if (res.meta.musicLeg > 0.01) caveats.push('rec mix included the accompaniment — set Rec mix to full 🎤 Voice for an honest check');
  if (res.meta.notesSkipped) caveats.push(`${res.meta.notesSkipped} notes fell outside the recording`);
  head.textContent = `Section check — m${res.meta.from}–${res.meta.to} @ ${res.meta.bpm} bpm, ` +
    `${res.meta.clipDurSec}s take, ${res.meta.notesInClip} notes` +
    (caveats.length ? ` · ⚠ ${caveats.join(' · ')}` : '');
  box.appendChild(head);

  const table = document.createElement('table');
  table.style.cssText = 'border-collapse:collapse;min-width:100%;';
  const parts = res.report.overall;
  const thRow = document.createElement('tr');
  const th0 = document.createElement('th');
  th0.style.cssText = 'text-align:left;padding:4px 8px;color:#9aa0a6;font-weight:normal;';
  th0.textContent = 'Section';
  thRow.appendChild(th0);
  parts.forEach((p) => {
    const th = document.createElement('th');
    th.style.cssText = 'text-align:left;padding:4px 8px;color:#d4af37;';
    th.textContent = p.name || p.key;
    thRow.appendChild(th);
  });
  table.appendChild(thRow);

  const addRow = (label, verdicts, bold) => {
    const tr = document.createElement('tr');
    const td0 = document.createElement('td');
    td0.style.cssText = 'padding:4px 8px;border-top:1px solid rgba(255,255,255,0.08);color:#e8eaed;' +
      (bold ? 'font-weight:600;' : '');
    td0.textContent = label;
    tr.appendChild(td0);
    verdicts.forEach((v) => tr.appendChild(cellFor(v)));
    table.appendChild(tr);
  };

  addRow('Whole take', res.report.overall, true);
  if (res.report.sections.length > 1 ||
      (res.report.sections.length === 1 && res.report.sections[0].title !== 'Whole take')) {
    res.report.sections.forEach((s) => {
      addRow(`${s.title}${s.fromMeasure != null ? ` (m${s.fromMeasure}–${s.toMeasure})` : ''}`, s.parts, false);
    });
  }
  box.appendChild(table);

  const foot = document.createElement('div');
  foot.style.cssText = 'color:#9aa0a6;margin-top:6px;';
  foot.textContent = '* few attributable notes here — low confidence. ' +
    '“Can’t attribute” = this part’s pitches were masked by unison/octave overlaps (physics, not a fault).';
  box.appendChild(foot);
}

/* ---------- init / test hook ------------------------------------------ */

export function initSectionCheck() {
  const btn = document.getElementById('secCheckBtn');
  if (!btn) return false;                 // wiring block absent — stay dormant
  btn.addEventListener('click', () => { runSectionCheck(); });
  if (!pollTimer) pollTimer = setInterval(pollTick, 250);

  // Headless-test / console hook (same spirit as window.__training):
  window.__sectionCheck = {
    hasTake: () => !!take,
    take: () => (take ? JSON.parse(JSON.stringify(take)) : null),
    run: () => runSectionCheck(),
    last: () => lastResult,
    // pure-core pass-throughs so a headless probe can drive the analysis
    // against synthetic PCM without a mic or a real recording:
    analyzeTake: (samples, sr, parts, opts) => A().analyzeTake(samples, sr, parts, opts),
    aggregateSections: (analysis, sections, opts) => A().aggregateSections(analysis, sections, opts),
    mapTransportToClip: (anchor) => A().mapTransportToClip(anchor),
  };
  return true;
}

// Self-init: this module is loaded by index.html's Section-check wiring block
// (a separate <script type="module">), AFTER the DOM exists. Shared app
// modules resolve to the same instances main.js uses (same URLs, one module
// registry), so nothing initializes twice.
initSectionCheck();
