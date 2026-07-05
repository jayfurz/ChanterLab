/* recording.js — in-app practice recording (issue #67).
 *
 * WHY THIS EXISTS: screen-recording a practice session for content fails
 * structurally. Headphones on → the capture gets loud music and a faint voice;
 * headphones off → almost no music reaches the mic. The fix is to MIX the
 * accompaniment and the mic together INSIDE WebAudio and record THAT, so the
 * clip is a clean, balanced blend regardless of how the singer is monitoring.
 *
 * GRAPH — all native Web Audio nodes on Tone's rawContext (the SAME context
 * scope.js's mic source and Tone's master both live in; main.js hands scope
 * `Tone.getContext().rawContext` in micStart, so this is verified, not assumed):
 *
 *   transport master (Tone.Limiter, tapped AFTER the limiter) --> musicGain --\
 *                                                                              >--> recDest --> MediaRecorder
 *   TrainingScope mic source (also feeds scope's analyser, untouched) --> micGain --/
 *
 *   - The music leg is tapped AFTER the limiter, so what you record is exactly
 *     what you hear (issue #65's brickwall stays in the recorded path).
 *   - The mic leg goes to micGain ONLY — never to the speakers (no monitor
 *     loop / feedback) and never onto any Tone gain. We only FAN OUT scope's
 *     existing source node, so the scoring / pitch tap is completely unaffected.
 *   - musicGain / micGain are the persisted "Voice / Music" balance; they scale
 *     ONLY the recording mix, never what the singer hears.
 *
 * The graph is built lazily on the first Record and then retained, so a plain
 * load / CI run that never records adds zero nodes and never constructs a
 * MediaRecorder. transport.buildAudio() disposes+recreates `master` on every
 * piece load and instrument switch; we re-tap the new master through the hook
 * it fires (setOnMasterRebuilt), which is what keeps a recording alive across a
 * mid-session instrument toggle.
 */
import { el, setStatus, REC_BALANCE_KEY, REC_HINT_KEY } from './state.js';
import { masterBus, setOnMasterRebuilt } from './transport.js';
import { currentPieceId } from './loader.js';

// MediaRecorder container/codec preference. Opus-in-WebM first (Chrome, Firefox,
// Android); audio/mp4 (AAC) for Safari, which supports neither WebM nor Opus;
// bare audio/webm as a last resort. First supported wins.
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'];

let ctx = null;            // native AudioContext (Tone's rawContext)
let recDest = null;        // MediaStreamAudioDestinationNode we record from
let musicGain = null;      // accompaniment leg of the recording mix
let micGain = null;        // mic leg of the recording mix
let tappedMaster = null;   // the master node currently feeding musicGain
let tappedMicSrc = null;   // the mic source node currently feeding micGain

let recorder = null;
let chunks = [];
let recording = false;
let startedAt = 0;
let tick = 0;              // elapsed-timer interval id
let chosenMime = '';

let balance = 0.5;         // 0 = all music, 1 = all voice; 0.5 = both at unity
let lastClip = null;       // { url, size, type, name } — kept downloadable until the NEXT record

/* ---------- capability / helpers ------------------------------------- */

function micOn() {
  return !!(window.TrainingScope && window.TrainingScope.isMicOn && window.TrainingScope.isMicOn());
}
function recorderSupported() {
  return typeof window.MediaRecorder === 'function';
}
function pickMime() {
  if (!recorderSupported() || !MediaRecorder.isTypeSupported) return '';
  for (const m of MIME_CANDIDATES) { if (MediaRecorder.isTypeSupported(m)) return m; }
  return '';   // nothing matched — let the browser pick its own default
}
function extForMime(m) { return /mp4|mpeg|aac|m4a/i.test(m || '') ? 'mp4' : 'webm'; }
function humanSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// balance -> the two leg gains. Center (0.5) keeps BOTH legs at unity; each
// extreme fully mutes the OPPOSITE leg. So balance=0 captures music only and
// balance=1 captures voice only — which is exactly how the verification proves
// both paths independently feed the mix (mute one, RMS drops to the other).
function musicLeg() { return Math.min(1, 2 * (1 - balance)); }
function micLeg() { return Math.min(1, 2 * balance); }

function rampGain(param, value) {
  if (!ctx) { param.value = value; return; }
  const t = ctx.currentTime;
  try {
    param.cancelScheduledValues(t);
    param.setValueAtTime(param.value, t);
    param.linearRampToValueAtTime(value, t + 0.03);   // click-free AND reaches exact 0
  } catch (e) { param.value = value; }
}
function applyBalance() {
  if (musicGain) rampGain(musicGain.gain, musicLeg());
  if (micGain) rampGain(micGain.gain, micLeg());
}

function loadBalance() {
  try {
    const v = parseFloat(localStorage.getItem(REC_BALANCE_KEY));
    if (isFinite(v) && v >= 0 && v <= 1) balance = v;
  } catch (e) { /* storage disabled — default 0.5 */ }
}
function saveBalance() {
  try { localStorage.setItem(REC_BALANCE_KEY, String(balance)); } catch (e) { /* non-fatal */ }
}

/* ---------- audio graph ---------------------------------------------- */

function ensureGraph() {
  if (recDest) return true;
  if (typeof Tone === 'undefined' || !Tone.getContext) return false;
  ctx = Tone.getContext().rawContext;
  if (!ctx || typeof ctx.createMediaStreamDestination !== 'function') return false;
  recDest = ctx.createMediaStreamDestination();
  musicGain = ctx.createGain();
  micGain = ctx.createGain();
  musicGain.gain.value = musicLeg();
  micGain.gain.value = micLeg();
  musicGain.connect(recDest);
  micGain.connect(recDest);
  retapMaster(masterBus());
  retapMic();
  return true;
}

// (Re)connect the post-limiter master output into musicGain. Called on graph
// build AND from transport.buildAudio()'s rebuild hook (which hands us a brand
// new master node after disposing the old one).
function retapMaster(masterNode) {
  if (!musicGain) return;
  if (tappedMaster && tappedMaster !== masterNode) {
    try { tappedMaster.disconnect(musicGain); } catch (e) { /* already disposed */ }
  }
  tappedMaster = masterNode || null;
  if (!tappedMaster) return;
  // Tone node -> native gain: Tone 14's connect() takes native AudioNode
  // destinations directly. Fallback to the standalone Tone.connect just in case.
  try { tappedMaster.connect(musicGain); }
  catch (e) {
    try { if (Tone.connect) Tone.connect(tappedMaster, musicGain); }
    catch (e2) { /* leave music leg silent rather than throw into buildAudio */ }
  }
}

// (Re)connect the live mic source node into micGain — or drop it when the mic
// is off. We only FAN OUT scope.js's source node; its analyser feed (scoring /
// pitch) is never touched. Safe anytime; no-op before the graph exists.
export function retapMic() {
  if (!micGain) return;
  const src = (window.TrainingScope && window.TrainingScope.getMicSourceNode)
    ? window.TrainingScope.getMicSourceNode() : null;
  if (src === tappedMicSrc) return;
  if (tappedMicSrc) { try { tappedMicSrc.disconnect(micGain); } catch (e) { /* fine */ } }
  tappedMicSrc = src || null;
  if (tappedMicSrc) { try { tappedMicSrc.connect(micGain); } catch (e) { tappedMicSrc = null; } }
}

// Called by main.js whenever the mic turns on/off or re-acquires its stream
// (headphones-mode switch): re-tap the (possibly new) source and refresh the UI.
export function onMicChange() { retapMic(); updateUI(); }

/* ---------- UI ------------------------------------------------------- */

function fmt(ms) {
  const s = Math.floor(ms / 1000);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
function updateTimer() {
  if (el.recTime) el.recTime.textContent = fmt(recording ? (performance.now() - startedAt) : 0);
}
function updateUI() {
  if (el.recBtn) {
    el.recBtn.classList.toggle('recording', recording);
    el.recBtn.textContent = recording ? '⏹ Stop recording'
      : (micOn() ? '⏺ Record' : '⏺ Record (music only)');
    el.recBtn.disabled = !recorderSupported();
    el.recBtn.setAttribute('aria-pressed', String(recording));
    if (!recorderSupported()) el.recBtn.title = 'Recording isn’t supported in this browser.';
  }
  if (el.recTime) el.recTime.hidden = !recording;
  // Balance only has meaning with a mic present (voice vs music); a music-only
  // capture has nothing to balance.
  if (el.recBalRow) el.recBalRow.hidden = !micOn();
  if (el.recSave) {
    if (lastClip && !recording) {
      el.recSave.hidden = false;
      el.recSave.href = lastClip.url;
      el.recSave.download = lastClip.name;
      el.recSave.textContent = '⬇ Save recording · ' + humanSize(lastClip.size);
      el.recSave.title = lastClip.name;
    } else {
      el.recSave.hidden = true;
    }
  }
}

// One-time "headphones give the cleanest recording" hint — only when recording
// WITH the mic on (the message is about the mic hearing only you). Persisted.
function maybeShowHint() {
  if (!el.recHint || !micOn()) return;
  let seen = false;
  try { seen = localStorage.getItem(REC_HINT_KEY) === '1'; } catch (e) { /* ignore */ }
  if (seen) return;
  el.recHint.hidden = false;
  try { localStorage.setItem(REC_HINT_KEY, '1'); } catch (e) { /* non-fatal */ }
}

/* ---------- clip lifecycle ------------------------------------------- */

function revokeClip() {
  if (lastClip && lastClip.url) { try { URL.revokeObjectURL(lastClip.url); } catch (e) { /* ignore */ } }
  lastClip = null;
}

function finalizeClip() {
  const type = chosenMime || (chunks[0] && chunks[0].type) || 'audio/webm';
  const blob = new Blob(chunks, { type });
  chunks = [];
  if (!blob.size) { setStatus('Recording produced no audio.'); updateUI(); return; }
  const url = URL.createObjectURL(blob);
  const date = new Date().toISOString().slice(0, 10);
  const pid = String(currentPieceId || 'session').replace(/[^\w.-]+/g, '_');
  const name = `chanterlab-${pid}-${date}.${extForMime(type)}`;
  lastClip = { url, size: blob.size, type, name };
  updateUI();
  setStatus(`Recording saved (${humanSize(blob.size)}) — tap “Save recording” to download.`);
}

/* ---------- start / stop --------------------------------------------- */

export async function startRecording() {
  if (recording) return true;
  if (!recorderSupported()) { setStatus('Recording isn’t supported in this browser.'); return false; }
  // Recording is a user gesture (button click) OR a test hook — either way,
  // make sure the audio context is running so the mix actually produces audio.
  try { if (typeof Tone !== 'undefined' && Tone.start) await Tone.start(); } catch (e) { /* continue */ }
  if (!ensureGraph()) { setStatus('Recording unavailable — audio engine not ready.'); return false; }
  // Re-tap in case master (piece load / instrument switch) or mic (on/off,
  // headphones switch) changed while we were idle.
  retapMaster(masterBus());
  retapMic();
  applyBalance();

  // A NEW recording discards the previous clip — but it stayed downloadable
  // right up to this moment (revoke only now).
  revokeClip();

  chosenMime = pickMime();
  chunks = [];
  try {
    recorder = chosenMime
      ? new MediaRecorder(recDest.stream, { mimeType: chosenMime })
      : new MediaRecorder(recDest.stream);
  } catch (e) {
    setStatus('Could not start recording: ' + (e && e.message ? e.message : e));
    return false;
  }
  chosenMime = recorder.mimeType || chosenMime;   // the type actually negotiated
  recorder.ondataavailable = (ev) => { if (ev.data && ev.data.size) chunks.push(ev.data); };
  recorder.onstop = finalizeClip;
  recorder.onerror = (ev) => { setStatus('Recording error.'); console.warn('MediaRecorder error', ev); };
  recorder.start(1000);   // 1s timeslices — resilient over a long session
  recording = true;
  startedAt = performance.now();
  clearInterval(tick);
  tick = setInterval(updateTimer, 250);
  updateTimer();
  updateUI();
  maybeShowHint();
  setStatus(micOn()
    ? 'Recording — the music and your mic are being mixed into the clip.'
    : 'Recording the accompaniment (mic off — music-only capture).');
  return true;
}

export function stopRecording() {
  if (!recording) return false;
  recording = false;
  clearInterval(tick); tick = 0;
  if (el.recHint) el.recHint.hidden = true;
  try { if (recorder && recorder.state !== 'inactive') recorder.stop(); }
  catch (e) { console.warn('stop recorder', e); }   // onstop -> finalizeClip produces the Blob
  updateUI();
  return true;
}

export function toggleRecording() {
  return recording ? stopRecording() : startRecording();
}

// Piece switch while recording: stop cleanly, file preserved. loader.js calls
// this BEFORE its stop()/loadScore()/buildAudio() so the clip's data is frozen
// (recorder.stop) before the new piece's buildAudio disposes the tapped master.
export function onRecordingPieceSwitch() {
  if (!recording) return false;
  stopRecording();
  setStatus('Recording stopped — switching pieces. Your clip is saved below.');
  return true;
}

/* ---------- balance / init / introspection --------------------------- */

export function setBalance(v) {
  const n = Number(v);
  if (!isFinite(n)) return;
  balance = Math.max(0, Math.min(1, n));
  if (el.recBalance && Math.round(balance * 100) !== Number(el.recBalance.value)) {
    el.recBalance.value = String(Math.round(balance * 100));
  }
  saveBalance();
  applyBalance();
}

export function initRecording() {
  loadBalance();
  // Register the master-rebuild re-tap at RUNTIME (not an eval-time top-level
  // call) so the loader↔transport↔recording import cycle never touches a
  // half-initialised binding.
  setOnMasterRebuilt((m) => retapMaster(m));
  if (el.recBalance) {
    el.recBalance.value = String(Math.round(balance * 100));
    el.recBalance.addEventListener('input', () => setBalance(Number(el.recBalance.value) / 100));
  }
  if (el.recBtn) el.recBtn.addEventListener('click', toggleRecording);
  updateUI();
}

// Test/dev hook state (window.__training.recording()). musicGain/micGain report
// the TARGET leg gains (deterministic; the nodes ramp to these in 30ms).
export function recordingState() {
  return {
    supported: recorderSupported(),
    recording,
    micOn: micOn(),
    elapsedMs: recording ? (performance.now() - startedAt) : 0,
    mimeType: chosenMime || pickMime(),
    balance,
    musicGain: musicLeg(),
    micGain: micLeg(),
    hasClip: !!lastClip,
    clipUrl: lastClip ? lastClip.url : null,
    clipSize: lastClip ? lastClip.size : 0,
    clipType: lastClip ? lastClip.type : null,
    clipName: lastClip ? lastClip.name : null,
    mimeSupport: MIME_CANDIDATES.map((t) => ({
      type: t,
      supported: (recorderSupported() && MediaRecorder.isTypeSupported)
        ? MediaRecorder.isTypeSupported(t) : false,
    })),
  };
}
