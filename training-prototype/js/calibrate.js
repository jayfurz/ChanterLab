/* calibrate.js — timing calibration wizard (sing-to-the-beat).
 *
 * Measures the per-device "Voice response" latency (L_in) so a note sung on the
 * beat you HEAR scores on that note. It plays a short run of evenly-spaced tones,
 * you sing each one, and it finds the time-shift that best lines your sung pitch
 * up with the tones — that shift is the full loop (output + your reaction +
 * detection). Subtracting the output-latency estimate (getDisplayLatency, L_out)
 * leaves L_in, which we persist via setResponseLatencyMs + TrainingScope.setInputLatency.
 *
 * Why subtracting L_out is safe: scoring uses the SUM of the two comps
 * (Transport.seconds − L_out − L_in). We set L_in = measuredOffset − L_out, so the
 * sum is exactly measuredOffset — the split between the two knobs can't change the
 * score. (It only affects the visual split; the lane keeps L_out.)
 *
 * Self-contained clock: tones are scheduled in the audio-context clock and sung
 * samples are stamped with the same clock via a TEMPORARY pitch-sink — so this
 * never touches Tone.Transport or the playState machinery. main.js hands us a
 * callback to reinstate the normal scoring sink when we're done.
 */
import { el, setStatus } from './state.js';
import { stop, getDisplayLatency, setResponseLatencyMs } from './transport.js';

let restoreScoringSink = () => {};   // set by initCalibrate (reinstalls main.js's sink)
let requestMic = () => {};           // set by initCalibrate (turns the mic on)
let refreshTimingUI = () => {};      // set by initCalibrate (main.js updateTimingUI)

let open = false;
let running = false;
let calibSynth = null;
let calibBuffer = [];
let calibTargets = [];
let runTimer = 0;

// Sequence params. A fifth-ish comfortable pitch per voice (octave is irrelevant
// — the scorer folds octaves, so sing it wherever is comfortable). ~10 tones at
// ~85 BPM with a 1s lead-in.
const SEQ_N = 10;
const SEQ_BEAT = 0.70;      // s between tone onsets
const SEQ_DUR = 0.45;       // s each tone sounds
const SEQ_LEAD = 1.1;       // s before the first tone (get ready)
const CENTS_TOL = 60;       // ± window counted as "on the tone"
const MIN_MATCHED_NOTES = 5; // fewer detected note-onsets than this ⇒ "didn't hear enough"

function pitchForVoice() {
  const v = (el.voiceChip && el.voiceChip.textContent || 'S').trim().charAt(0).toUpperCase();
  return ({ S: 67, A: 62, T: 55, B: 50 })[v] || 57;   // G4 / D4 / G3 / D2-ish; fallback A3
}
const midiToFreq = (m) => 440 * Math.pow(2, (m - 69) / 12);
function centsFolded(sungMidi, targetMidi) {
  const k = Math.round((sungMidi - targetMidi) / 12);
  return (sungMidi - 12 * k - targetMidi) * 100;
}

// Measure the per-note ONSET offset: for each tone, when did the singer ARRIVE
// on pitch relative to the beat? Onset-based (not window-fill) so it's immune to
// how long they sustain and to the wide note window — a fill-count metric
// plateaus across a range of lags and biases toward the plateau edge. The median
// across notes is the full loop offset (output + reaction + detection). Pure —
// also the headless unit-test entry (window.__calibrate.measureOffset).
export function measureOffsetSec(samples, targets, centsTol = CENTS_TOL) {
  const ss = samples.filter((s) => isFinite(s.tSec) && isFinite(s.midi)).sort((a, b) => a.tSec - b.tSec);
  const onsets = [];
  for (const tg of targets) {
    const lo = tg.startSec - 0.05;
    const hi = tg.startSec + 0.45;   // search up to +450ms past the beat (covers the loop)
    for (let i = 0; i < ss.length; i++) {
      const s = ss[i];
      if (s.tSec < lo) continue;
      if (s.tSec >= hi) break;
      if (Math.abs(centsFolded(s.midi, tg.midi)) > centsTol) continue;
      // Require a short in-tune sustain after it, so a lone noisy frame isn't
      // mistaken for the note's onset.
      let sustain = 0;
      for (let j = i + 1; j < ss.length && ss[j].tSec < s.tSec + 0.12; j++) {
        if (Math.abs(centsFolded(ss[j].midi, tg.midi)) <= centsTol) sustain++;
      }
      if (sustain >= 2) { onsets.push(s.tSec - tg.startSec); break; }
    }
  }
  if (!onsets.length) return { deltaSec: 0, matched: 0, total: targets.length };
  onsets.sort((a, b) => a - b);
  return { deltaSec: onsets[Math.floor(onsets.length / 2)], matched: onsets.length, total: targets.length };
}

/* ---------- modal shell (mirrors the library overlay pattern) ---------- */
function render(step, data) {
  const title = el.calibTitle, body = el.calibBody, actions = el.calibActions;
  if (!title || !body || !actions) return;
  actions.innerHTML = '';
  const btn = (label, cls, fn) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'btn ' + (cls || ''); b.textContent = label;
    b.addEventListener('click', fn); actions.appendChild(b); return b;
  };
  if (step === 'nomic') {
    title.textContent = 'Turn on your mic';
    body.innerHTML = '<p>Calibration needs to hear you. Turn on the microphone, then start.</p>';
    btn('🎤 Turn on mic', 'primary', async () => { await requestMic(); render(TrainingScope.isMicOn() ? 'intro' : 'nomic'); });
    btn('Cancel', '', closeCalibrate);
  } else if (step === 'intro') {
    title.textContent = 'Calibrate timing';
    body.innerHTML =
      '<p>Put your <b>headphones</b> on. I’ll play a steady note ten times — ' +
      '<b>sing it back on each beat</b> (any octave that’s comfortable).</p>' +
      '<p class="calib-sub">I’ll measure how your singing lines up and set your ' +
      '“Voice response” automatically.</p>';
    btn('▶ Start', 'primary', startMeasure);
    btn('Cancel', '', closeCalibrate);
  } else if (step === 'run') {
    title.textContent = 'Listening…';
    body.innerHTML =
      '<p class="calib-run">🎤 Sing the note on every beat…</p>' +
      '<div class="calib-progress"><div id="calibBar" class="calib-bar"></div></div>' +
      '<p class="calib-sub" id="calibReadout"></p>';
    // no actions except cancel
    btn('Cancel', '', () => { abortRun(); closeCalibrate(); });
  } else if (step === 'result') {
    title.textContent = 'Done — measured ' + data.ms + ' ms';
    body.innerHTML =
      '<p>Your singing now lines up with the beat. Voice response set to <b>' + data.ms + ' ms</b>.</p>' +
      '<p class="calib-sub">Matched ' + data.matched + ' of ' + SEQ_N + ' notes. ' +
      'Sing a fast passage to check — re-run anytime.</p>';
    btn('Use it', 'primary', () => { applyResult(data.ms); closeCalibrate(); });
    btn('Try again', '', () => render('intro'));
  } else if (step === 'toofew') {
    title.textContent = 'Didn’t hear enough';
    body.innerHTML =
      '<p>I only caught ' + data.matched + ' sung frames — not enough to measure.</p>' +
      '<p class="calib-sub">Check the mic is on and sing out on each note, then try again.</p>';
    btn('Try again', 'primary', () => render('intro'));
    btn('Cancel', '', closeCalibrate);
  }
}

export function openCalibrate() {
  if (!el.calibrateOverlay) return;
  stop();   // silence any playback so the mic hears only the calibration tones
  open = true;
  el.calibrateOverlay.hidden = false;
  document.body.classList.add('calib-lock');
  render((window.TrainingScope && TrainingScope.isMicOn()) ? 'intro' : 'nomic');
}

export function closeCalibrate() {
  if (!open) return;
  abortRun();
  open = false;
  el.calibrateOverlay.hidden = true;
  document.body.classList.remove('calib-lock');
}

function abortRun() {
  running = false;
  if (runTimer) { clearTimeout(runTimer); runTimer = 0; }
  restoreScoringSink();               // give scoring its sink back
}

/* ---------- the measurement run ---------- */
function ensureSynth() {
  if (calibSynth) return calibSynth;
  calibSynth = new Tone.Synth({
    oscillator: { type: 'triangle' },
    envelope: { attack: 0.01, decay: 0.1, sustain: 0.7, release: 0.15 },
  }).toDestination();
  calibSynth.volume.value = -6;
  return calibSynth;
}

async function startMeasure() {
  if (!(window.TrainingScope && TrainingScope.isMicOn())) { render('nomic'); return; }
  try { await Tone.start(); } catch (e) { /* context already running */ }
  render('run');
  running = true;
  calibBuffer = [];
  calibTargets = [];

  const ac = Tone.getContext();
  const synth = ensureSynth();
  const midi = pitchForVoice();
  const freq = midiToFreq(midi);
  const start = ac.currentTime + SEQ_LEAD;   // first tone onset (context clock)

  // Temporary sink: stamp every voiced sample in the SAME context clock, relative
  // to the first tone. (main.js's scoring sink is restored in abortRun/finish.)
  TrainingScope.setPitchSink((s) => {
    if (!running || s.midi == null || !isFinite(s.midi)) return;
    calibBuffer.push({ tSec: ac.currentTime - start, midi: s.midi });
  });

  for (let k = 0; k < SEQ_N; k++) {
    const tk = start + k * SEQ_BEAT;
    synth.triggerAttackRelease(freq, SEQ_DUR, tk);
    calibTargets.push({ startSec: k * SEQ_BEAT, endSec: k * SEQ_BEAT + SEQ_DUR, midi });
  }

  // Live progress bar over the run; finish shortly after the last tone decays.
  const total = SEQ_LEAD + SEQ_N * SEQ_BEAT + 0.6;
  const t0 = ac.currentTime;
  const tick = () => {
    if (!running) return;
    const frac = Math.max(0, Math.min(1, (ac.currentTime - t0) / total));
    const bar = document.getElementById('calibBar');
    if (bar) bar.style.width = Math.round(frac * 100) + '%';
    const ro = document.getElementById('calibReadout');
    if (ro && el.scopeReadout) ro.textContent = el.scopeReadout.textContent || '';
    if (frac < 1) runTimer = setTimeout(tick, 100);
    else finishMeasure();
  };
  runTimer = setTimeout(tick, 100);
}

function finishMeasure() {
  running = false;
  restoreScoringSink();
  const { deltaSec, matched } = measureOffsetSec(calibBuffer, calibTargets);
  if (matched < MIN_MATCHED_NOTES) { render('toofew', { matched }); return; }
  // L_in = full loop − L_out estimate, clamped to the slider's range.
  const ms = Math.max(0, Math.min(400, Math.round((deltaSec - getDisplayLatency()) * 1000)));
  render('result', { ms, matched });
}

function applyResult(ms) {
  setResponseLatencyMs(ms);
  if (window.TrainingScope && TrainingScope.setInputLatency) TrainingScope.setInputLatency(ms / 1000);
  refreshTimingUI();
  setStatus('Timing calibrated — voice response ' + ms + ' ms.');
}

/* ---------- init / wiring ---------- */
export function initCalibrate(opts) {
  opts = opts || {};
  restoreScoringSink = typeof opts.restoreScoringSink === 'function' ? opts.restoreScoringSink : restoreScoringSink;
  requestMic = typeof opts.requestMic === 'function' ? opts.requestMic : requestMic;
  refreshTimingUI = typeof opts.refreshTimingUI === 'function' ? opts.refreshTimingUI : refreshTimingUI;
  if (!el.calibrateOverlay) return;
  if (el.calibClose) el.calibClose.addEventListener('click', closeCalibrate);
  // scrim tap + Esc close (mirrors library.js)
  el.calibrateOverlay.addEventListener('click', (e) => { if (e.target === el.calibrateOverlay) closeCalibrate(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); closeCalibrate(); } });
}
