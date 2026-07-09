/* transport.js — audio synths/mix, playback scheduling, the follow cursor,
 * and the Play/Pause/Stop + transport-overlay state machine.
 */
import { el, setStatus, GOLD, VOICE_DEFS, INSTRUMENT_KEY, VOLUME_KEY } from './state.js';
import { parsed, clampMeasure, measureBeatRange, isMonophonic } from './model.js';
import { osmd, osmdSteps, ensureRenderWindow, flushDeferredRender } from './loader.js';
import { selectedVoice, melodyMuted, buildScopeLane, toggleChipMute } from './voices.js';
import { beginScoringSession, scoreLapAndRoll, finalizeScoringOnStop, scoreSummaryShown } from './scoring-ui.js';
import { currentSections, setActiveSection, sectionIndexForMeasure } from './sections.js';

let instruments = [];      // per part: Tone.PolySynth (synth mode) or Tone.Sampler (voices mode)
export let gains = [];     // Tone.Gain per part — instrument-agnostic; mute/mix logic
                           // (applyMix, hearMine, mono melody toggle) only ever touches
                           // these, never `instruments` directly (issue #66 requirement)
let master = null;         // Tone.Limiter master bus — the only node between the
                           // summed voices and the speakers (issue #65)
let masterVolume = null;   // Tone.Gain(0..1.25) sitting BEFORE the limiter — the
                           // in-app master volume (issue #74 F5); see buildAudio.
let masterAnalyser = null; // observe-only native AnalyserNode fanned off `master`
                           // (issue #74 discriminator): lets the diagnostics read
                           // whether the GRAPH is producing samples while the
                           // SPEAKER is silent — the one bit that separates a
                           // route/session-level silence from a scheduling one.
let builtMode = null;      // which mode `instruments` was actually built in ('synth'|'voices'),
                           // so startPlayback can tell a stale build from the live setting
let onMasterRebuilt = null;// recording tap re-hook (issue #67), set at runtime by
                           // js/recording.js — see setOnMasterRebuilt / buildAudio
let scheduledIds = [];
let cursorWindow = [];     // absolute osmdSteps indices inside the current loop window
export let playState = 'stopped';
export let userHoldUntil = 0;
let lastFollowScroll = 0;  // throttles the per-note follow-scroll (issue #65)
const FOLLOW_SCROLL_MS = 140;

  /* ---------- Instrument: Synth / Voices (issue #66) -------------------- *
   * "Voices" is a per-part Tone.Sampler playing an offline-synthesized choir
   * "ah" pad (see training-prototype/samples/README.md for full provenance —
   * generated, not recorded/downloaded: no CC0 vocal sample set could be
   * found, so this is original audio with zero licensing risk). It feeds the
   * SAME Gain(0.25)->Limiter(-1) chain as the synth (buildAudio below), so
   * every mix/mute/limiter behavior tuned by issue #65 carries over unchanged.
   *
   * Samples are fetched ONCE (Tone.ToneAudioBuffers, shared across however
   * many parts the current piece has) and only ever on an explicit switch to
   * Voices or the first Play while Voices is the active setting — never on
   * app boot, so a fresh load / CI run stays at zero extra network requests
   * as long as nobody touches the toggle (default is 'synth' — see
   * loadInstrumentMode).
   */
export let instrumentMode = 'synth';   // 'synth' | 'voices' — persisted via INSTRUMENT_KEY
let voiceBuffers = null;               // Tone.ToneAudioBuffers once loaded; shared by all parts' Samplers
let voiceLoadPromise = null;           // in-flight (or settled) load — de-dupes concurrent triggers
let voiceLoadFailed = false;           // sticky for this session: don't refetch a known-bad load

const VOICE_SAMPLE_BASE = 'samples/voices/';
  // MIDI note -> filename. Every 4 semitones, E2..~G#5 — Tone.Sampler pitch-
  // shifts to fill the gaps (see samples/generate-voices.mjs for why this
  // spacing/range was chosen).
const VOICE_SAMPLE_NOTES = { 40: 'ah_040.ogg', 44: 'ah_044.ogg', 48: 'ah_048.ogg', 52: 'ah_052.ogg',
  56: 'ah_056.ogg', 60: 'ah_060.ogg', 64: 'ah_064.ogg', 68: 'ah_068.ogg', 72: 'ah_072.ogg',
  76: 'ah_076.ogg', 80: 'ah_080.ogg' };

  // Read the persisted preference at boot WITHOUT fetching anything — the
  // toggle can restore to "Voices" from a prior session while the audio
  // graph itself stays on synth until a real trigger (switch or Play) loads
  // the samples (see buildAudio's builtMode reconciliation in startPlayback).
export function loadInstrumentMode() {
    try {
      const v = localStorage.getItem(INSTRUMENT_KEY);
      if (v === 'voices' || v === 'synth') instrumentMode = v;
    } catch (e) { /* storage disabled — default (synth) stands */ }
  }

  // Effective mode: 'voices' only once the samples are actually usable.
  function effectiveMode() {
    return (instrumentMode === 'voices' && voiceBuffers && !voiceLoadFailed) ? 'voices' : 'synth';
  }

  // Sync the Sound seg-control's active button to instrumentMode (mirrors
  // scoring-ui.js's updateStrictnessUI pattern). Called after loadInstrumentMode
  // at boot and after every switchInstrumentMode (incl. an on-failure fallback).
export function updateInstrumentUI() {
    if (!el.instrumentPicker) return;
    [...el.instrumentPicker.children].forEach((b) =>
      b.classList.toggle('active', b.dataset.instrument === instrumentMode));
  }

  // Lazy, idempotent sample load. Resolves with the shared Tone.ToneAudioBuffers;
  // rejects (once) on failure, after which it stays failed for this session
  // (instrumentMode itself is NOT force-reset here — callers decide whether a
  // failure should fall back for just this call or for the whole session; see
  // switchInstrumentMode, which does revert the live setting on failure).
export function ensureVoiceSamplesLoaded() {
    if (voiceBuffers) return Promise.resolve(voiceBuffers);
    if (voiceLoadFailed) return Promise.reject(new Error('voice samples previously failed to load'));
    if (voiceLoadPromise) return voiceLoadPromise;
    setStatus('Loading voices…');
    voiceLoadPromise = new Promise((resolve, reject) => {
      const buffers = new Tone.ToneAudioBuffers({
        urls: VOICE_SAMPLE_NOTES,
        baseUrl: VOICE_SAMPLE_BASE,
        onload: () => resolve(buffers),
        onerror: (e) => reject(e instanceof Error ? e : new Error(String(e))),
      });
    }).then((buffers) => { voiceBuffers = buffers; voiceLoadFailed = false; return buffers; })
      .catch((e) => { voiceLoadFailed = true; voiceLoadPromise = null; throw e; });
    return voiceLoadPromise;
  }

  // Build the `urls` map Tone.Sampler wants, pointing at the ALREADY-loaded
  // buffers (not URL strings) so constructing one Sampler per part never
  // re-fetches — only the single Tone.ToneAudioBuffers load above ever hits
  // the network, regardless of how many parts the piece has.
  function voiceUrlsFromBuffers() {
    const urls = {};
    Object.keys(VOICE_SAMPLE_NOTES).forEach((midi) => {
      if (voiceBuffers.has(midi)) urls[midi] = voiceBuffers.get(midi);
    });
    return urls;
  }

  // Top-level "switch the Sound setting" entry point (main.js's instrument
  // picker calls this). Persists the choice, lazy-loads samples if needed
  // (falling back to synth + a status message on failure — never silently
  // stuck on a broken Voices selection), and — if a piece is already
  // loaded — rebuilds the live audio graph now so the switch actually takes
  // effect this session (mirrors the existing bpm/loopOn stop+rebuild
  // pattern in main.js rather than trying to hot-swap instruments under a
  // running Tone.Transport).
export async function switchInstrumentMode(mode) {
    if (mode !== 'synth' && mode !== 'voices') return;
    instrumentMode = mode;
    try { localStorage.setItem(INSTRUMENT_KEY, mode); } catch (e) { /* non-fatal */ }
    updateInstrumentUI();

    if (mode === 'voices') {
      try {
        await ensureVoiceSamplesLoaded();
        setStatus('Voices loaded.');
      } catch (e) {
        instrumentMode = 'synth';   // fall back for THIS session; leave the stored
                                    // preference alone (may just be a transient blip)
        updateInstrumentUI();
        setStatus('Voices unavailable — using synth instead. (' + (e && e.message ? e.message : 'load failed') + ')');
      }
    }

    if (parsed) {
      const wasPlaying = playState === 'playing';
      if (playState !== 'stopped') stop();
      buildAudio();
      applyMix();
      if (wasPlaying) await startPlayback();
    }
  }

  /* ---------- Audio (Tone.js) ----------------------------------------- */

  // Current Tone AudioContext state ('running' | 'suspended' | 'closed' | …).
  // Exposed for headless tests via window.__training.audioContextState()
  // (issue #63) — a post-Play assertion that doesn't rely on actually
  // hearing sound (CI has no audio device).
export function audioContextState() {
    return (typeof Tone !== 'undefined' && Tone.getContext) ? Tone.getContext().state : 'unknown';
  }

  // Richer AudioContext snapshot for the iOS audio diagnostics (issue #74).
  // baseLatency/outputLatency live on the raw BaseAudioContext (not the Tone
  // wrapper) and aren't reported by every engine, so they're guarded. Read-only:
  // the diagnostics overlay (main.js) is the sole consumer and it never mutates
  // anything here.
export function audioContextInfo() {
    if (typeof Tone === 'undefined' || !Tone.getContext) return null;
    const c = Tone.getContext();
    const raw = c.rawContext || c;
    return {
      sampleRate: raw.sampleRate,
      state: raw.state,
      baseLatency: (typeof raw.baseLatency === 'number') ? raw.baseLatency : null,
      outputLatency: (typeof raw.outputLatency === 'number') ? raw.outputLatency : null,
      lookAhead: (typeof c.lookAhead === 'number') ? c.lookAhead : null,
    };
  }

  // Output-latency compensation for the singscope (owner field report: the
  // scope's target lane / playhead visually LEADS the audible audio). Sound
  // scheduled at context time T becomes audible at roughly T + baseLatency +
  // outputLatency, but Tone.Transport.seconds is in the SCHEDULE domain — so
  // any display that consumes it raw runs early by exactly this much. (The 0.2s
  // lookAhead is NOT part of this: events are scheduled at correct context
  // times; lookAhead only moves when the JS callback fires, not when sound
  // plays.)  display time = transport time - getDisplayLatency().
  //
  // iOS follow-up: Safari almost never exposes outputLatency (reports 0), yet
  // its real DAC/speaker path is ~0.1-0.2s — so base-only compensation still
  // left the lane visibly early on iPhone. When the platform reports nothing on
  // iOS we fall back to a central estimate; a device that DOES report a real
  // outputLatency uses that instead. On top of the auto estimate sits a
  // persisted per-device manual nudge (setScopeSyncMs / ?scopelag=MS) so the
  // owner can dial the last few tens of ms by eye — the auto figure can't know
  // Bluetooth/AirPlay hops.
  //
  // Robust by construction: each auto field counts only if finite & positive,
  // an implausible total (>=2s — garbage after a route flip) collapses to 0,
  // and a negative total (over-aggressive negative nudge) clamps to 0. The
  // result is ALWAYS finite >= 0, never NaN.
  const IOS_OUTPUT_LATENCY_FALLBACK = 0.12;   // s; applied only when iOS reports none

  let _scopeSyncMs = null;                     // manual nudge, ms; lazy from storage
  function scopeSyncSec() {
    if (_scopeSyncMs === null) {
      let v = NaN;
      try { v = parseFloat(localStorage.getItem('chanterlab.scopeSyncMs')); } catch (e) { /* no storage */ }
      // Default 220ms on every device — owner field-tuned on iPhone speaker+mic
      // AND desktop (speaker/Bluetooth output latency is commonly 150–250ms).
      // A wired low-latency setup can pull the "Playback sync" slider down; a
      // stored value always wins over this default.
      _scopeSyncMs = isFinite(v) ? v : 220;
    }
    return _scopeSyncMs / 1000;
  }
  // Persisted per-device scope nudge (ms). POSITIVE pushes the target lane
  // LATER (the fix for "scope runs early"); negative pulls it earlier. Survives
  // reload. Returns the value stored.
export function setScopeSyncMs(ms) {
    const v = (typeof ms === 'number' && isFinite(ms)) ? ms : 0;
    _scopeSyncMs = v;
    try { localStorage.setItem('chanterlab.scopeSyncMs', String(v)); } catch (e) { /* no storage */ }
    return v;
  }
export function getScopeSyncMs() { return Math.round(scopeSyncSec() * 1000); }

  // L_in — voice/detection response latency (ms), the second half of the timing
  // model. The sung TRACE and the SCORING sample stamp are back-dated by this
  // (applied inside scope.js via TrainingScope.setInputLatency), so a note sung
  // on the audible beat lands on that note; the gold LANE is untouched (it keeps
  // L_out via getDisplayLatency). Persisted per device; set by the "Voice
  // response" slider or the calibration wizard. Default ~80ms covers the
  // analysis + one-euro group delay; larger = treat the sung sample as earlier.
  const RESPONSE_LATENCY_DEFAULT_MS = 65;   // owner field-tuned (iPhone speaker+mic)
  let _responseMs = null;                      // lazy from storage
  function responseLatencySec() {
    if (_responseMs === null) {
      let v = NaN;
      try { v = parseFloat(localStorage.getItem('chanterlab.responseMs')); } catch (e) { /* no storage */ }
      _responseMs = isFinite(v) ? v : RESPONSE_LATENCY_DEFAULT_MS;
    }
    return _responseMs / 1000;
  }
export function setResponseLatencyMs(ms) {
    const v = (typeof ms === 'number' && isFinite(ms)) ? Math.max(0, Math.min(400, ms)) : RESPONSE_LATENCY_DEFAULT_MS;
    _responseMs = v;
    try { localStorage.setItem('chanterlab.responseMs', String(v)); } catch (e) { /* no storage */ }
    return v;
  }
export function getResponseLatencyMs() { return Math.round(responseLatencySec() * 1000); }
export function getResponseLatencySec() { return responseLatencySec(); }

export function getDisplayLatency() {
    let auto = 0;
    try {
      const c = (typeof Tone !== 'undefined' && Tone.getContext) ? Tone.getContext() : null;
      const raw = c && (c.rawContext || c);
      if (raw) {
        const base = (typeof raw.baseLatency === 'number' && isFinite(raw.baseLatency) && raw.baseLatency > 0) ? raw.baseLatency : 0;
        let out = (typeof raw.outputLatency === 'number' && isFinite(raw.outputLatency) && raw.outputLatency > 0) ? raw.outputLatency : 0;
        if (out === 0 && IS_IOS) out = IOS_OUTPUT_LATENCY_FALLBACK;
        auto = base + out;
      }
    } catch (e) { auto = 0; }
    let total = auto + scopeSyncSec();
    if (!isFinite(total) || total < 0) total = 0;
    return total < 2 ? total : 0;
  }

  // iOS route-flip mitigation (issue #74). getUserMedia flips the AVAudioSession
  // to play-and-record, which on iOS can reroute output (headphones→speaker) and
  // move the hardware sample rate (e.g. 48k speaker → 24k on AirPods); an audio
  // graph created under the OLD session then resamples badly and crackles
  // (WebKit #154538: "the output unit will request fewer samples when moving from
  // a higher sample rate to a lower one, and the Web Audio engine chokes").
  // Rebuilding the playback graph while the session is ALREADY in play-and-record
  // ("born under the mic") side-steps that. SILENT + idempotent — the exact same
  // dispose+recreate an instrument switch already does (buildAudio + applyMix) —
  // and deliberately a NO-OP while playing (a rebuild would cut the sound) or
  // before any piece is loaded. Zero behavior change off iOS: desktop sessions
  // never flip, so this just recreates an identical graph, inaudibly, while
  // stopped. main.js calls it on mic on/off and on devicechange.
export function rebuildAudioForMic(reason) {
    const sampleRate = (typeof Tone !== 'undefined' && Tone.getContext)
      ? Tone.getContext().rawContext.sampleRate : null;
    if (!parsed || playState !== 'stopped') {
      return { rebuilt: false, reason, playState, sampleRate };
    }
    buildAudio();
    applyMix();
    return { rebuilt: true, reason, playState, sampleRate };
  }

  /* ---------- iOS Audio Session API management (issue #74 follow-up, F1) --*
   * Safari ≥16.4 exposes navigator.audioSession.type (W3C Audio Session API,
   * Safari-only — no Chrome/Firefox, per BCD). Setting it invokes WebKit's
   * AudioSession::setCategoryOverride, which SHORT-CIRCUITS the whole
   * capture/playback category state machine analyzed in
   * docs/design/IOS-AUDIO-SESSION-ANALYSIS.md — including the sticky
   * PlayAndRecord-while-audio-plays branch that otherwise keeps the call-mode
   * session (📞 icon, call-volume floor) alive after the mic is turned off.
   * Feature-detected + try/catch: a complete no-op on every other engine
   * (Chrome/Firefox/older Safari), so desktop and headless CI stay
   * byte-identical. Callers (main.js) are responsible for sequencing —
   * 'play-and-record' BEFORE getUserMedia, 'playback' only AFTER the mic
   * tracks are actually stopped — because the spec's element-update steps end
   * the microphone track when the type is not play-and-record/auto (§6.3 of
   * the draft): this module never calls setAudioSessionType itself, so it
   * can't race that invariant.
   */
export function audioSessionSupported() {
    try { return typeof navigator !== 'undefined' && 'audioSession' in navigator; }
    catch (e) { return false; }
  }

  // type: 'playback' | 'play-and-record' | 'auto'. Never throws; returns a
  // small result object the caller (main.js) logs to the #74 diagnostics ring.
export function setAudioSessionType(type, reason) {
    if (!audioSessionSupported()) return { ok: false, supported: false, type, reason };
    let before = null;
    try { before = navigator.audioSession.type; } catch (e) { /* ignore */ }
    if (before === type) return { ok: true, supported: true, type, reason, before, after: type, changed: false };
    try {
      navigator.audioSession.type = type;
      let after = type;
      try { after = navigator.audioSession.type; } catch (e) { /* ignore */ }
      return { ok: true, supported: true, type, reason, before, after, changed: before !== after };
    } catch (e) {
      return { ok: false, supported: true, type, reason, before, error: (e && e.message) || String(e) };
    }
  }

  /* ---------- iOS "silent unless mic" mitigation (issue #74) ----------- *
   * Plain WebAudio on iOS routes through the ambient/solo-ambient audio-session
   * category, which the hardware mute/silent switch SILENCES — so playback is
   * inaudible with the switch on and no mic, even though Tone.start() reports a
   * 'running' context (#63's unlock genuinely succeeds; audibility is a separate
   * axis). getUserMedia is what flips the session to play-and-record, which
   * IGNORES the mute switch — which is exactly why the owner hears sound only
   * with the mic on. The accepted fix (unmute.js / feross/unmute-ios-audio) is
   * to keep a SILENT looping <audio> HTMLMediaElement playing: a media element
   * forces the app onto the MEDIA channel, so WebAudio is heard through the mute
   * switch WITHOUT needing the mic. iOS-gated by UA (incl. iPadOS, which reports
   * as macOS — disambiguated by maxTouchPoints); the element is never even
   * constructed off iOS, so desktop and the headless CI run stay byte-identical.
   *
   * DEMOTED TO A FALLBACK (issue #74 follow-up, F4): on Safari ≥16.4 — i.e.
   * whenever audioSessionSupported() above is true — F1's explicit
   * navigator.audioSession.type='playback' override does this exact job
   * (immune to the mute switch, no mic needed) WITHOUT the two liabilities
   * this element has: it renders through the MEDIA pipeline (a second, always-
   * unity volume domain alongside the call-volume domain the mic session
   * imposes — the owner's "playing both" report), and holding it playing keeps
   * WebKit's `isPlayingAudio` true forever, which is what stuck the session in
   * PlayAndRecord after mic-off (Obs 2 in the design doc). So on ≥16.4 this
   * element is never even constructed (iosMediaUnlock no-ops immediately);
   * only pre-16.4 iOS still uses it, and even there it's paused for the
   * duration of any live mic track (iosMediaUnlockPauseForMic) and re-engaged
   * on the next gesture once the mic goes off.
   */
  const IS_IOS = (() => {
    try {
      const ua = navigator.userAgent || '';
      if (/iPad|iPhone|iPod/.test(ua)) return true;
      // iPadOS 13+ reports as "Macintosh"; a touch-capable Mac is really an iPad.
      return ua.includes('Macintosh') && (navigator.maxTouchPoints || 0) > 1;
    } catch (e) { return false; }
  })();
  let silentEl = null;              // looping silent HTMLAudioElement (iOS only)
  let silentUnlockEngaged = false;  // has .play() resolved at least once?

  // A runtime-built silent 8-bit mono WAV as a data URI — no network request, no
  // embedded asset, and guaranteed decodable by Safari's HTMLMediaElement. 0.5s
  // is long enough to loop cleanly (very short clips loop unreliably on iOS).
  function silentWavDataUri(seconds = 0.5, rate = 8000) {
    const n = Math.floor(seconds * rate);
    const b = new Uint8Array(44 + n);
    const dv = new DataView(b.buffer);
    const wr = (o, s) => { for (let i = 0; i < s.length; i++) b[o + i] = s.charCodeAt(i); };
    wr(0, 'RIFF'); dv.setUint32(4, 36 + n, true); wr(8, 'WAVE');
    wr(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
    dv.setUint16(22, 1, true); dv.setUint32(24, rate, true); dv.setUint32(28, rate, true);
    dv.setUint16(32, 1, true); dv.setUint16(34, 8, true);
    wr(36, 'data'); dv.setUint32(40, n, true);
    for (let i = 0; i < n; i++) b[44 + i] = 128;   // 8-bit PCM silence = midpoint
    let bin = '';
    for (let i = 0; i < b.length; i++) bin += String.fromCharCode(b[i]);
    return 'data:audio/wav;base64,' + btoa(bin);
  }

  // Engage the media-channel unlock. MUST be called synchronously inside a user
  // gesture (unlockAudio / the mic-off tap both do, before any await). iOS-only,
  // idempotent — play() on an already-playing element is a no-op — and (F4) a
  // complete no-op on Safari ≥16.4, where F1's audioSession override already
  // does this job (silentEl is never even constructed there). Never throws
  // into the play path.
export function iosMediaUnlock() {
    if (!IS_IOS) return;
    if (audioSessionSupported()) return;   // F1 replaces this element's job
    try {
      if (!silentEl) {
        silentEl = new Audio(silentWavDataUri());
        silentEl.loop = true;
        silentEl.preload = 'auto';
        silentEl.volume = 1;                 // the samples themselves are silent
        silentEl.setAttribute('playsinline', '');
        silentEl.setAttribute('webkit-playsinline', '');
        // Belt-and-braces: some iOS builds drop loop on sub-second clips.
        silentEl.addEventListener('ended', () => {
          try { silentEl.currentTime = 0; silentEl.play().catch(() => {}); } catch (e) { /* ignore */ }
        });
      }
      const p = silentEl.play();
      if (p && p.then) p.then(() => { silentUnlockEngaged = true; }).catch(() => { /* may need another gesture */ });
      else silentUnlockEngaged = true;
    } catch (e) { /* never let the unlock break playback */ }
  }

  // Legacy-iOS-only half of F4: PAUSE the media-channel unlock for the
  // duration of a live mic track. Any capture at all already forces the
  // session into PlayAndRecord (the mute switch is ignored regardless — see
  // Obs 3 in the design doc), so the element serves no purpose while the mic
  // is on, and letting it keep playing is precisely what makes
  // `isPlayingAudio` sticky, trapping the session in call mode after mic-off.
  // No-op on ≥16.4 (element never constructed) and off iOS. Call at the start
  // of the mic-ON gesture, before getUserMedia.
export function iosMediaUnlockPauseForMic() {
    if (!IS_IOS || audioSessionSupported()) return;
    if (silentEl && !silentEl.paused) { try { silentEl.pause(); } catch (e) { /* ignore */ } }
  }
export function isIOS() { return IS_IOS; }
  // Diagnostics read-out (issue #74): is the media-channel unlock actually live?
  // 'running but silent' is precisely the state the owner will otherwise report.
  // `strategy` (F4) tells the overlay which mitigation is actually active:
  // 'audioSession-api' (≥16.4, F1 handles it, this element is never touched),
  // 'silent-element' (legacy iOS, this element is the mechanism), or 'none' off iOS.
export function silentUnlockState() {
    const strategy = !IS_IOS ? 'none' : (audioSessionSupported() ? 'audioSession-api' : 'silent-element');
    return {
      ios: IS_IOS,
      strategy,
      engaged: silentUnlockEngaged,
      playing: !!(silentEl && !silentEl.paused),
      readyState: silentEl ? silentEl.readyState : null,
    };
  }

  /* ---------- iOS interruption / background recovery (choir-training) --- *
   * Field report (iPhone Safari): background the tab/app and return, then press
   * Play — it HANGS until a full refresh, after which it works again. iOS
   * suspends or parks the AudioContext in WebKit's non-standard 'interrupted'
   * state on an audio-session interruption; on return the context clock is
   * stalled, so Tone.Transport never advances. Worse, resume() on an
   * 'interrupted' context can never settle (Tonejs/Tone.js#767), so the plain
   * `await Tone.start()` in the Play gesture can hang OUTRIGHT — exactly the
   * reported symptom, and exactly what a fresh context (page refresh) sidesteps.
   *
   * Recovery is folded into the Play gesture (unlockAudio below): resume the RAW
   * context first, BOUNDED by a timeout so a stuck 'interrupted' resume can't
   * hang the gesture; then, if it won't reach 'running' — or we KNOW the context
   * was interrupted / backgrounded since the last successful Play (its clock can
   * be stalled even while state still reads 'running') — recreate it outright
   * (recreateAudioContext, the #74 primitive, which also rebuilds the graph +
   * re-applies the master volume/instrument) and let startPlayback reschedule +
   * start the Transport from scratch. No refresh needed.
   *
   * iOS-GATED end to end: markContextForRecovery no-ops off iOS and unlockAudio
   * keeps its EXACT pre-existing desktop/CI behavior (issue #63), so desktop
   * Chrome/Firefox are byte-for-byte unaffected. A test-only override
   * (setRecoveryTestOverride) opens the robust path on desktop Chromium so the
   * headless probe can exercise the recreate→rebuild→reschedule→start chain — a
   * genuine 'interrupted' state only reproduces on real iOS.
   */
  const RESUME_WAIT_MS = 350;             // per-attempt cap so a stuck resume() can't hang Play
  let contextNeedsRecovery = false;       // iOS: a background/interruption happened since the last Play
  let lastRecoveryReason = null;
  let _lastUnlockRecreated = false;       // did the last unlockAudio() have to recreate the context?
  let _recoveryTestForce = false;         // test-only: take the iOS robust path off iOS
  let onContextRecreated = null;          // main.js re-taps the mic + rebinds listeners after a recover-recreate
  let onRecoveryEvent = null;             // main.js's logAudioEvent bridge (transport can't import main.js)

  // Mark the live context as needing a full recreate on the next Play. main.js
  // calls this from visibilitychange (returned to the foreground), a bfcache
  // pageshow, and the 'statechange' → suspended/interrupted listener. NO-OP off
  // iOS (returns false) so desktop Chrome/Firefox never recreate; the test
  // override opens the path for the headless probe only.
export function markContextForRecovery(reason) {
    if (!IS_IOS && !_recoveryTestForce) return false;
    contextNeedsRecovery = true;
    lastRecoveryReason = reason || 'unknown';
    return true;
  }
  // Recovery-state read-out for the #74 diagnostics overlay + headless tests.
export function contextRecoveryState() {
    return {
      ios: IS_IOS,
      pending: contextNeedsRecovery,
      reason: lastRecoveryReason,
      lastRecreated: _lastUnlockRecreated,
      testForced: _recoveryTestForce,
    };
  }
  // main.js registers a callback invoked (awaited) right after the Play path
  // recreates the context — it re-taps the mic on the fresh context and rebinds
  // the diagnostics statechange listener. Runtime registration (not an import)
  // keeps transport.js free of any dependency on main.js / scope.js.
export function setOnContextRecreated(fn) { onContextRecreated = (typeof fn === 'function') ? fn : null; }
  // main.js registers its logAudioEvent so recovery transitions show up in the
  // on-device #74 overlay ring. No-op until registered (e.g. headless CI).
export function setRecoveryLogger(fn) { onRecoveryEvent = (typeof fn === 'function') ? fn : null; }
  // Test-only: force the iOS resume-or-recreate path on a non-iOS engine so the
  // headless probe can drive the recreate→rebuild→reschedule→start chain.
export function setRecoveryTestOverride(on) { _recoveryTestForce = !!on; return _recoveryTestForce; }

  function recoveryLog(type, data) { if (onRecoveryEvent) { try { onRecoveryEvent(type, data); } catch (e) { /* logging is best-effort */ } } }
  function rawOf(c) { return c ? (c.rawContext || c) : null; }
  function afterMs(ms) { return new Promise((res) => setTimeout(res, ms)); }
  // Resolve true once the raw context reaches 'running', or false after `ms`.
  // Cheap, self-cleaning, never throws.
  function waitForRunning(raw, ms) {
    if (!raw) return Promise.resolve(false);
    if (raw.state === 'running') return Promise.resolve(true);
    return new Promise((resolve) => {
      let done = false, timer = null;
      const finish = (v) => {
        if (done) return; done = true;
        try { raw.removeEventListener('statechange', onState); } catch (e) { /* ignore */ }
        if (timer) clearTimeout(timer);
        resolve(v);
      };
      const onState = () => { if (raw.state === 'running') finish(true); };
      try { raw.addEventListener('statechange', onState); } catch (e) { /* ignore */ }
      timer = setTimeout(() => finish(raw.state === 'running'), ms);
    });
  }

  // Unlock the browser AudioContext SYNCHRONOUSLY within the calling gesture's
  // handler chain (iOS Safari requirement — no detours through setTimeout/rAF
  // before this call). Every audio-starting user-gesture path (Play/Resume —
  // see startPlayback/resume below — and anywhere else audio starts from a
  // tap/click/change) must call this FIRST, before touching the transport.
  // Returns true once the context is actually running; false means the
  // browser's autoplay policy still blocked it (rare, but real on some mobile
  // browsers even after a genuine tap) — callers must NOT pretend to play in
  // that case: no scheduling, no transport start, just prompt a retry tap
  // (issue #63).
  async function unlockAudio() {
    iosMediaUnlock();   // iOS media-channel unlock (issue #74) — no-op off iOS,
                        // synchronous so the <audio>.play() stays in the gesture.
    if (!IS_IOS && !_recoveryTestForce) {
      // Desktop / headless CI — byte-for-byte the pre-existing issue #63 path.
      await Tone.start();
      if (Tone.getContext().state !== 'running') {
        setStatus('Tap again to enable sound.');
        return false;
      }
      return true;
    }
    return await unlockAudioRobust();
  }

  // iOS resume-or-recreate (choir-training background/interruption bug). Bounded
  // so a stuck 'interrupted' resume can't hang the Play gesture; recreates the
  // context outright when resume won't yield 'running', OR an interruption/
  // background was flagged since the last successful Play. Sets
  // _lastUnlockRecreated so resume() can restart cleanly (see resume()) instead
  // of resuming a now-empty transport.
  async function unlockAudioRobust() {
    _lastUnlockRecreated = false;
    let raw = rawOf(Tone.getContext());
    const startState = raw ? raw.state : 'unknown';
    const wasInterrupted = startState === 'interrupted';
    const flagged = contextNeedsRecovery;

    // 1) Normal resume path (enough for a merely 'suspended' context), but NEVER
    //    block the gesture on it — resume() on an 'interrupted' context can hang
    //    forever (Tonejs/Tone.js#767), which is the field-reported "Play hangs".
    try { await Promise.race([Tone.start(), afterMs(RESUME_WAIT_MS)]); } catch (e) { /* fall through */ }
    try { if (raw && raw.resume) await Promise.race([raw.resume(), afterMs(RESUME_WAIT_MS)]); } catch (e) { /* fall through */ }
    let running = await waitForRunning(raw, RESUME_WAIT_MS);

    // 2) Recreate when resume didn't land 'running', or we KNOW the context was
    //    interrupted/backgrounded (its clock can be stalled even while 'running').
    if (!running || wasInterrupted || flagged) {
      recoveryLog('recover:begin', { startState, running, wasInterrupted, flagged, reason: lastRecoveryReason });
      let r = null;
      try { r = await recreateAudioContext(); } catch (e) { r = { ok: false, reason: (e && e.message) || String(e) }; }
      _lastUnlockRecreated = true;
      // main.js re-taps the mic (if it was live) on the fresh context + rebinds
      // the diagnostics statechange listener. Optional/best-effort.
      if (onContextRecreated) { try { await onContextRecreated(r); } catch (e) { /* mic reattach optional */ } }
      raw = rawOf(Tone.getContext());
      running = raw ? (raw.state === 'running' || await waitForRunning(raw, RESUME_WAIT_MS)) : false;
      recoveryLog('recover:done', { ok: !!(r && r.ok), state: raw ? raw.state : 'unknown', running, before: r && r.before, after: r && r.after });
    }

    contextNeedsRecovery = false;
    lastRecoveryReason = null;
    if (!running) { setStatus('Tap again to enable sound.'); return false; }
    return true;
  }

  /* ---------- Master accompaniment volume (issue #74 follow-up, F5) ---- *
   * iOS's call-volume floor (documented ~1/16, never true zero — Unity/Vivox)
   * means the hardware rocker literally CANNOT silence the accompaniment
   * while the mic is on: the canonical VoIP answer is app-side gain, which is
   * exactly what this is. It also directly answers "everything sounds a
   * little low" (design doc §1 Obs 4) by making the conservative 0.25-per-
   * part mix adjustable. Applied to a Tone.Gain sitting BEFORE the limiter
   * (see buildAudio) so boosting can never clip the bus, and re-created fresh
   * at the persisted level on every buildAudio — piece load, instrument
   * switch, AND context recreation (F2) all go through buildAudio, so the
   * level survives every one of them without extra wiring.
   */
export let volumeLevel = 1.0;   // 0..1.25; persisted via VOLUME_KEY

  // Read the persisted level at boot WITHOUT touching the DOM or any live
  // node (mirrors loadInstrumentMode's pattern) — updateVolumeUI/buildAudio
  // apply it once the relevant piece exists.
export function loadVolume() {
    try {
      const v = parseFloat(localStorage.getItem(VOLUME_KEY));
      if (isFinite(v) && v >= 0 && v <= 1.25) volumeLevel = v;
    } catch (e) { /* storage disabled — default (1.0) stands */ }
  }

export function getVolume() { return volumeLevel; }

  // Live-apply + persist. Ramped (not stepped) so mid-drag changes don't
  // click; safe to call before any piece is loaded (masterVolume is null —
  // buildAudio picks up volumeLevel as its initial value once it runs).
export function setVolume(v) {
    const n = Number(v);
    if (!isFinite(n)) return volumeLevel;
    volumeLevel = Math.max(0, Math.min(1.25, n));
    if (masterVolume) masterVolume.gain.rampTo(volumeLevel, 0.05);
    try { localStorage.setItem(VOLUME_KEY, String(volumeLevel)); } catch (e) { /* non-fatal */ }
    updateVolumeUI();
    return volumeLevel;
  }

  // Sync the Sound-pane slider + its % readout to volumeLevel. Called after
  // loadVolume() at boot and from every setVolume() (mirrors
  // updateInstrumentUI's pattern for the Synth/Voices toggle).
export function updateVolumeUI() {
    if (el.volume) el.volume.value = String(Math.round(volumeLevel * 100));
    if (el.volumeOut) el.volumeOut.textContent = Math.round(volumeLevel * 100) + '%';
  }

  // Shared envelope numbers for BOTH instruments — issue #65's pop-fix tuning
  // (8ms attack / 120ms release) applies identically whether a part is a
  // Tone.PolySynth voice or a Tone.Sampler voice, so a Voices note starts/ends
  // exactly as click-free as the synth it replaces.
const ENV_ATTACK = 0.008;
const ENV_RELEASE = 0.12;

export function buildAudio() {
    disposeAudio();
    instruments = [];
    gains = [];
    // Give the scheduler more headroom so a heavy main-thread tick (OSMD cursor
    // stepping over a big SVG — the measured 87ms tasks in issue #65) can't fire
    // note events past-due and glitch. 0.1→0.2s doubles the lookahead budget at
    // the cost of ~100ms of extra output latency (both audio AND the follow
    // cursor shift together, so they stay in sync — imperceptible for follow-
    // along practice). Set here (idempotent) so it's applied before first Play.
    if (typeof Tone !== 'undefined' && Tone.getContext) Tone.getContext().lookAhead = 0.2;
    // Master bus: a brickwall limiter at -1 dBFS is the ONLY node between the
    // summed voices and the speakers. Four unison voices at 0.25 each sum to
    // ~1.0 at their peaks (measured 0.90 on the default 4-part piece, 0.89 with
    // "also hear my part"); real-time phase drift or a hotter piece crosses 1.0
    // and hard-clips at the device — the "popping/crackle" of issue #65. The
    // limiter catches those transients transparently (it doesn't engage until
    // ~-1 dBFS, so normal material is untouched) and guarantees the bus can
    // never clip. It sits on the SYNTH bus only — the scoring/scope path taps
    // the mic (scope.js), never this bus, so scoring is unaffected. Shared by
    // both instrument modes.
    master = new Tone.Limiter(-1).toDestination();
    // Master volume (issue #74 F5): ONE shared Gain, BEFORE the limiter, that
    // every part's Gain(0.25) feeds into instead of `master` directly. Placed
    // pre-limiter so raising it past unity still can't clip the bus (the
    // limiter guarantees that regardless), and re-created here at the
    // persisted volumeLevel so it survives every buildAudio (piece load,
    // instrument switch, F2's context recreation) without extra wiring.
    masterVolume = new Tone.Gain(volumeLevel).connect(master);
    // Graph-output discriminator (issue #74): fan the master into an observe-only
    // AnalyserNode (NOT routed to the destination, so it can't affect what's
    // heard). masterOutputLevel() reads it so the diagnostics can answer "is the
    // graph producing samples right now?" independently of whether anything is
    // audible. Recreated with the graph, so it survives every rebuild.
    try {
      const raw = Tone.getContext().rawContext;
      masterAnalyser = raw.createAnalyser();
      masterAnalyser.fftSize = 1024;
      try { master.connect(masterAnalyser); }
      catch (e) { if (Tone.connect) Tone.connect(master, masterAnalyser); }
    } catch (e) { masterAnalyser = null; }
    builtMode = effectiveMode();
    if (builtMode === 'voices') {
      parsed.parts.forEach(() => {
        const gain = new Tone.Gain(0.25).connect(masterVolume);
        const sampler = new Tone.Sampler({
          urls: voiceUrlsFromBuffers(),
          attack: ENV_ATTACK,
          release: ENV_RELEASE,
        }).connect(gain);
        instruments.push(sampler);
        gains.push(gain);
      });
    } else {
      parsed.parts.forEach(() => {
        const gain = new Tone.Gain(0.25).connect(masterVolume);
        const synth = new Tone.PolySynth(Tone.Synth, {
          oscillator: { type: 'triangle' },
          // Explicit, gentle envelope. The few-ms attack keeps note onsets crisp
          // without a zero-length edge (which would click); the shorter release
          // (was 0.25s) trims the note tail so dense same-pitch chant stops piling
          // overlapping releases into the limiter, keeping headroom. Measured 0
          // discontinuities on the 50%-repeated-pitch worst case (issue #65).
          envelope: { attack: ENV_ATTACK, decay: 0.1, sustain: 0.85, release: ENV_RELEASE },
        }).connect(gain);
        instruments.push(synth);
        gains.push(gain);
      });
    }
    // Recording tap (issue #67): disposeAudio() above just destroyed the OLD
    // `master`, severing any live recording graph's post-limiter tap; hand the
    // brand-new master to whoever registered so it can re-tap. No-op until a
    // recording graph exists (js/recording.js registers this). This is what
    // keeps a recording alive across an instrument switch — buildAudio rebuilds
    // the master, and the mix destination re-attaches to the new one.
    if (onMasterRebuilt) { try { onMasterRebuilt(master); } catch (e) { /* recording graph optional */ } }
  }

  // The master accompaniment bus (the Tone.Limiter whose output is what the
  // singer hears). Exposed so the recording graph can tap it AFTER the limiter
  // — "what you record is what you hear" (issue #67). Null before the first
  // buildAudio (i.e. before any piece is loaded).
export function masterBus() { return master; }

  // Register a callback invoked with the freshly-built master node at the end
  // of every buildAudio() (piece load, instrument switch, first Play). Runtime
  // registration (not an ESM import) keeps transport.js free of any dependency
  // on the recording module and sidesteps the loader↔transport import cycle.
export function setOnMasterRebuilt(fn) { onMasterRebuilt = (typeof fn === 'function') ? fn : null; }

  function disposeAudio() {
    instruments.forEach((s) => s.dispose());
    gains.forEach((g) => g.dispose());
    if (masterAnalyser) { try { masterAnalyser.disconnect(); } catch (e) { /* already gone */ } masterAnalyser = null; }
    if (masterVolume) { try { masterVolume.dispose(); } catch (e) { /* already gone */ } masterVolume = null; }
    if (master) { master.dispose(); master = null; }
    instruments = []; gains = [];
  }

  // Graph-output discriminator read-out (issue #74). RMS/peak of the master
  // (post-limiter) signal — i.e. exactly what's being sent to the speakers. If
  // the owner reports silence while these are NON-zero during playback, the
  // graph IS producing audio and the silence is route/session-level (the fix is
  // to recreate the context — see recreateAudioContext). If they're ~zero during
  // playback, it's a graph/scheduling problem instead. Null before any build.
export function masterOutputLevel() {
    if (!masterAnalyser) return { rms: null, peak: null };
    const buf = new Float32Array(masterAnalyser.fftSize);
    masterAnalyser.getFloatTimeDomainData(buf);
    let acc = 0, peak = 0;
    for (let i = 0; i < buf.length; i++) { const v = buf[i]; acc += v * v; const a = Math.abs(v); if (a > peak) peak = a; }
    return { rms: Math.sqrt(acc / buf.length), peak };
  }

  // "Running but silent" recovery (issue #74). The WebKit silent-context class:
  // an AudioContext reports state='running' yet outputs silence because it was
  // bound to a stale sample-rate/output route at creation; a fresh context is
  // born at the CURRENT hardware rate/route and outputs correctly (this is the
  // documented close-and-recreate workaround, WebKit #154538). Owner-triggered
  // ONLY (a button in the diagnostics overlay) — never auto-run, so it can't
  // false-positive on desktop. Stops playback, swaps Tone onto a brand-new
  // context via Tone.setContext, rebuilds the graph on it, and closes the old
  // one. The mic (if it was on) lived on the OLD context — main.js drops it
  // first and the owner re-enables it. Returns the before/after sample rates.
  // latencyHint: owner field evidence (2026-07-05) — starting an iOS SCREEN
  // RECORDING makes the mic+speaker crackle vanish (recording the mic or not),
  // and it returns the moment recording stops. Screen recording forces larger
  // system IO buffers, so the crackle is most plausibly BUFFER UNDERRUN in the
  // voice-processing (mic+EC) session, not a rate mismatch. A context born
  // with latencyHint 'playback'/'balanced' requests bigger buffers — the same
  // medicine, available from the web. The diagnostics overlay exposes buffer
  // buttons that recreate the context with each hint so the owner can A/B
  // live; outputLatency in the snapshot shows what each hint actually won.
export async function recreateAudioContext(latencyHint) {
    if (typeof Tone === 'undefined' || !Tone.setContext || !Tone.getContext) {
      return { ok: false, reason: 'Tone.setContext unavailable' };
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return { ok: false, reason: 'no AudioContext constructor' };
    const before = Tone.getContext().rawContext.sampleRate;
    try {
      try { stop(); } catch (e) { /* ignore */ }
      const old = Tone.getContext();
      const raw = latencyHint != null ? new AC({ latencyHint }) : new AC();
      if (raw.resume) { try { await raw.resume(); } catch (e) { /* may need a fresh gesture */ } }
      Tone.setContext(raw);
      Tone.getContext().lookAhead = 0.2;       // match buildAudio's scheduler headroom
      if (parsed) { buildAudio(); applyMix(); }
      // Leave the OLD context idle rather than close()-ing it: after buildAudio's
      // disposeAudio the old graph is gone and Tone's clock has moved to the new
      // context, so it pulls no more audio — and closing it races Tone's
      // scheduler ("Cannot resume a closed AudioContext"). A best-effort suspend
      // frees the hardware unit without that race; a few idle contexts across a
      // handful of manual taps stay well under iOS's per-page limit.
      try {
        if (old && old.rawContext && old.rawContext !== raw && old.rawContext.suspend) old.rawContext.suspend().catch(() => {});
      } catch (e) { /* best-effort */ }
      const after = Tone.getContext().rawContext.sampleRate;
      return {
        ok: true, before, after, changed: before !== after, state: raw.state,
        latencyHint: latencyHint != null ? latencyHint : 'default',
        baseLatency: raw.baseLatency, outputLatency: raw.outputLatency,
      };
    } catch (e) {
      return { ok: false, reason: (e && e.message) || String(e), before };
    }
  }

  /* ---------- Offline A/B capture (verification/listening aid, #66) ----- *
   * Test/dev-only utility (mirrors the existing scoreCore/injectSample test
   * hooks in main.js — "harmless in prod"): renders the SAME short passage
   * through the Synth path and the Voices path using Tone.Offline (a
   * non-realtime OfflineAudioContext — computes audio without a real device,
   * so it works headless under Playwright same as everywhere else). Lets a
   * human compare the two without needing a live speaker in CI. The app
   * itself never calls this.
   */
export async function captureOfflineAB(fromMeasure, toMeasure, bpmValue) {
    if (!parsed) throw new Error('no piece loaded');
    const spb = 60 / Number(bpmValue || el.bpm.value);
    const from = clampMeasure(Number(fromMeasure));
    const to = clampMeasure(Number(toMeasure));
    const range = measureBeatRange(from, to);
    const total = (range.end - range.start) * spb;
    const notesByPart = parsed.parts.map((part) => part.notes
      .filter((n) => n.startBeat >= range.start - 1e-6 && n.startBeat < range.end - 1e-6)
      .map((n) => ({
        freq: midiToFreq(n.midi),
        t: (n.startBeat - range.start) * spb,
        dur: Math.max(0.05, n.durBeat * spb * 0.95),
      })));

    const renderSynth = () => Tone.Offline(() => {
      const m = new Tone.Limiter(-1).toDestination();
      notesByPart.forEach((notes) => {
        const g = new Tone.Gain(0.25).connect(m);
        const s = new Tone.PolySynth(Tone.Synth, {
          oscillator: { type: 'triangle' },
          envelope: { attack: ENV_ATTACK, decay: 0.1, sustain: 0.85, release: ENV_RELEASE },
        }).connect(g);
        notes.forEach((n) => s.triggerAttackRelease(n.freq, n.dur, n.t));
      });
    }, total + 0.5);

    const renderVoices = async () => {
      await ensureVoiceSamplesLoaded();
      return Tone.Offline(() => {
        const m = new Tone.Limiter(-1).toDestination();
        notesByPart.forEach((notes) => {
          const g = new Tone.Gain(0.25).connect(m);
          const samp = new Tone.Sampler({
            urls: voiceUrlsFromBuffers(),
            attack: ENV_ATTACK,
            release: ENV_RELEASE,
          }).connect(g);
          notes.forEach((n) => samp.triggerAttackRelease(n.freq, n.dur, n.t));
        });
      }, total + 0.5);
    };

    // base64-encode 16-bit PCM (mono, ch0) — far more compact across the
    // page.evaluate() boundary than a raw JSON array of floats.
    const toBase64Pcm16 = (buf) => {
      const data = buf.getChannelData(0);
      const bytes = new Uint8Array(data.length * 2);
      const view = new DataView(bytes.buffer);
      for (let i = 0; i < data.length; i++) {
        const v = Math.max(-1, Math.min(1, data[i]));
        view.setInt16(i * 2, Math.round(v * 32767), true);
      }
      let binary = '';
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
      }
      return btoa(binary);
    };

    const [synthBuf, voicesBuf] = await Promise.all([renderSynth(), renderVoices()]);
    return {
      sampleRate: synthBuf.sampleRate,
      synthPcm16Base64: toBase64Pcm16(synthBuf),
      voicesPcm16Base64: toBase64Pcm16(voicesBuf),
    };
  }

  // Mute the selected voice unless "also hear my part" is checked.
  // NOTE: this is the ONLY place backing-voice gain changes, and it depends
  // solely on voice selection — never on mic input/level (see Headphones mode
  // in scope.js for the OS-level ducking story).
export function applyMix() {
    const mono = parsed.parts.length === 1;
    parsed.parts.forEach((p, idx) => {
      if (!gains[idx]) return;
      const isSelected = p.voiceKey === selectedVoice;
      // 1-voice piece: the sole line follows melodyMuted (no "your part" mix).
      // Multi-voice: mute only your selected voice unless you opt to hear it.
      const mute = mono ? melodyMuted : (isSelected && !el.hearMine.checked);
      gains[idx].gain.rampTo(mute ? 0 : 0.25, 0.05);
    });
  }

  function midiToFreq(m) { return 440 * Math.pow(2, (m - 69) / 12); }

  function scheduleAll() {
    clearSchedule();
    const spb = 60 / Number(el.bpm.value); // seconds per quarter-note beat
    const from = clampMeasure(Number(el.loopFrom.value));
    const to = clampMeasure(Number(el.loopTo.value));
    const loop = el.loopOn.checked;

    // window in beats: use measures. We approximate measure length from the
    // control's own note onsets (first note beat of each measure).
    const range = measureBeatRange(from, to);
    const winStart = range.start;
    const winEnd = range.end;

    parsed.parts.forEach((part, idx) => {
      part.notes.forEach((n) => {
        if (n.startBeat < winStart - 1e-6 || n.startBeat >= winEnd - 1e-6) return;
        const t = (n.startBeat - winStart) * spb;
        const dur = Math.max(0.05, n.durBeat * spb * 0.95);
        const id = Tone.Transport.schedule((time) => {
          instruments[idx].triggerAttackRelease(midiToFreq(n.midi), dur, time);
        }, t);
        scheduledIds.push(id);
      });
    });

    // cursor timeline = OSMD's own step table clipped to the window. Indices
    // stay ABSOLUTE (= next() calls since cursor.reset()) so stepCursorTo can
    // advance by exactly the right count even when the window starts mid-piece.
    cursorWindow = [];
    osmdSteps.forEach((s, i) => {
      if (s.beat < winStart - 1e-4 || s.beat >= winEnd - 1e-4) return;
      cursorWindow.push(i);
      const t = (s.beat - winStart) * spb;
      const id = Tone.Transport.schedule(() => stepCursorTo(i), t);
      scheduledIds.push(id);
    });

    const total = (winEnd - winStart) * spb;
    if (loop) {
      Tone.Transport.loop = true;
      Tone.Transport.loopStart = 0;
      Tone.Transport.loopEnd = total;
      // LAP-BOUNDARY DETECTION (issue #55): Tone.Transport re-fires every
      // event scheduled inside [loopStart,loopEnd) on each pass — that's
      // already how the pre-#55 spike's resetCursor() call here kept
      // resetting the cursor once per lap, and how the note/cursor-step
      // schedules above keep replaying each lap. So the exact same "just
      // before the wrap" instant is the one boundary signal a lap needs: no
      // separate polling/rAF watcher, just score-and-reset piggybacked onto
      // the schedule that already existed for the cursor reset.
      const id = Tone.Transport.schedule(() => onLapWrap(), total - 1e-3);
      scheduledIds.push(id);
    } else {
      Tone.Transport.loop = false;
      const id = Tone.Transport.schedule(() => stop(), total + 0.3);
      scheduledIds.push(id);
    }
  }

  // Fires ~1ms before the transport wraps back to loopStart (see the comment
  // above). Scores the lap that just finished (no-op if the mic produced no
  // samples this lap — see scoreCurrentLap), rolls the sample buffer over to
  // the next lap, and resets the follow cursor.
  //
  // KNOWN EDGE CASE: this callback runs on Tone's audio-clock schedule, which
  // can fire a few ms ahead of the pitch tracker's rAF-driven sample stream
  // (real mic latency). A straggler sample or two from the very tail of the
  // finishing lap can therefore land in the NEXT lap's buffer instead. In
  // practice this only ever brushes the last note of a lap, whose target
  // pitch is identical lap-to-lap (same passage repeating), so the practical
  // effect is negligible — a deliberate v1 tradeoff, not an oversight.
  function onLapWrap() {
    scoreLapAndRoll();   // score the finished lap + roll the sample buffer (scoring-ui.js)
    resetCursor();
  }

  function clearSchedule() {
    scheduledIds.forEach((id) => Tone.Transport.clear(id));
    scheduledIds = [];
  }

  /* ---------- Cursor -------------------------------------------------- */

  function resetCursor() {
    if (!osmd.cursor) return;
    // Belt-and-braces: some OSMD builds ignore constructor cursorsOptions.
    if (osmd.cursor.CursorOptions) {
      osmd.cursor.CursorOptions.color = GOLD;
      osmd.cursor.CursorOptions.alpha = 0.45;
      osmd.cursor.CursorOptions.follow = false;   // never let OSMD scroll the page
    }
    osmd.cursor.reset();
    osmd.cursor.show();
    if (osmd.cursor.update) osmd.cursor.update();
    cursorStep = 0;
    // when the loop window starts mid-piece, park the cursor on the window's
    // first step instead of the top of the piece
    if (cursorWindow.length && cursorWindow[0] > 0) {
      while (cursorStep < cursorWindow[0]) { osmd.cursor.next(); cursorStep++; }
    }
    updatePos(cursorWindow.length ? osmdSteps[cursorWindow[0]].measure : null);
    lastFollowScroll = 0;   // let the first per-step follow-scroll fire promptly
    scrollCursorIntoView();
  }
export let cursorStep = 0;
  function stepCursorTo(i) {
    if (!osmd.cursor) return;
    if (i < cursorStep) {
      // loop wrapped without an explicit reset — rewind and re-advance
      osmd.cursor.reset(); osmd.cursor.show(); cursorStep = 0;
    }
    while (cursorStep < i) { osmd.cursor.next(); cursorStep++; }
    updatePos(osmdSteps[i] ? osmdSteps[i].measure : null);
    // Throttle the follow-scroll. scrollCursorIntoView reads offsetTop/Height
    // (a forced synchronous reflow over a ~4500-node score SVG that osmd.cursor
    // .next just invalidated) and restarts a smooth-scroll animation. Doing that
    // on every step piles main-thread work into the audio scheduler's tick
    // (issue #65). The cursor glyph and posOut still advance every step; only
    // the score-scroll cadence is capped — the cursor never drifts more than
    // ~140ms (< one note) before the view catches up.
    const now = performance.now();
    if (now - lastFollowScroll >= FOLLOW_SCROLL_MS) { lastFollowScroll = now; scrollCursorIntoView(); }
  }

  function updatePos(measure) {
    if (!el.posOut) return;
    // Just the current measure — the windowed-render pill ("of N") is the sole
    // denominator, and it uses the PRINTED count (updatePos used the SOURCE
    // count, so the two disagreed at split measures).
    el.posOut.textContent = measure ? `m ${measure}` : 'm –';
    // Keep the active-section label in step with the cursor's measure (cheap
    // binary search; no-op for pieces without sections). measure===null (stop)
    // leaves the last active section shown rather than blanking it.
    if (currentSections.length && measure != null) {
      setActiveSection(sectionIndexForMeasure(measure));
    }
  }

  // Keep the follow cursor visible inside the scrollable score container.
  // Etiquette (owner's design):
  //   - only ever scrolls the score CONTAINER — never the page,
  //   - only while PLAYING (paused/stopped = page + score fully free),
  //   - suspends ~3 s after any user touch/scroll on the container,
  //   - vertically prioritizes the SELECTED voice's staff (the cursor element
  //     spans the whole system, so the active staff sits at a fractional
  //     height within it — S top … B bottom).
  // force=true bypasses the playing-state + user-hold guards: a PAUSED jump-to-
  // section needs to scroll the score to the parked cursor even though playback
  // isn't running (the normal path only auto-scrolls while playing).
  function scrollCursorIntoView(force) {
    if (!force) {
      if (playState !== 'playing') return;
      if (performance.now() < userHoldUntil) return;
    }
    const cEl = osmd && osmd.cursor && osmd.cursor.cursorElement;
    const wrap = el.osmd;
    if (!cEl || !wrap) return;

    const vTop = wrap.scrollTop;
    const vBottom = vTop + wrap.clientHeight;
    const sysTop = cEl.offsetTop;
    const sysBottom = sysTop + cEl.offsetHeight;

    if (cEl.offsetHeight <= wrap.clientHeight - 8) {
      // The whole system fits — keep ALL staves (T and B included) in view.
      if (sysTop < vTop || sysBottom > vBottom) {
        const slack = Math.max(6, (wrap.clientHeight - cEl.offsetHeight) * 0.35);
        wrap.scrollTo({ top: Math.max(0, sysTop - slack), behavior: 'smooth' });
      }
    } else {
      // System taller than the viewport — gold-voice priority: center the
      // SELECTED voice's staff (cursor spans the system, staff ≈ fractional).
      const nParts = parsed && parsed.parts.length ? parsed.parts.length : 1;
      const selIdx = parsed ? parsed.parts.findIndex((p) => p.voiceKey === selectedVoice) : -1;
      const frac = selIdx >= 0 ? (selIdx + 0.5) / nParts : 0.5;
      const targetY = sysTop + cEl.offsetHeight * frac;
      const margin = Math.min(30, wrap.clientHeight * 0.12);
      if (targetY < vTop + margin || targetY > vBottom - margin) {
        wrap.scrollTo({ top: Math.max(0, targetY - wrap.clientHeight * 0.5), behavior: 'smooth' });
      }
    }
    const left = cEl.offsetLeft;
    if (left < wrap.scrollLeft + 10 || left > wrap.scrollLeft + wrap.clientWidth - 30) {
      wrap.scrollTo({ left: Math.max(0, left - wrap.clientWidth * 0.3), behavior: 'smooth' });
    }
  }

export function noteUserTouch() { userHoldUntil = performance.now() + 3000; }

  // Park the follow cursor at the loop-window start while PAUSED/STOPPED, then
  // scroll it into view. Mirrors resetCursor's mid-piece parking but without any
  // playback scheduling (cursorWindow isn't built until startPlayback).
export function parkCursorAtWindowStart() {
    if (!osmd || !osmd.cursor) return;
    const cur = osmd.cursor;
    if (cur.CursorOptions) {
      cur.CursorOptions.color = GOLD;
      cur.CursorOptions.alpha = 0.45;
      cur.CursorOptions.follow = false;
    }
    cur.reset();
    cur.show();
    if (cur.update) cur.update();
    cursorStep = 0;
    const from = clampMeasure(Number(el.loopFrom.value));
    const to = clampMeasure(Number(el.loopTo.value));
    const { start: winStart } = measureBeatRange(from, to);
    // first rendered step at/after the window start (the step table is clipped
    // to the rendered window but beats stay absolute)
    let target = 0;
    for (let i = 0; i < osmdSteps.length; i++) {
      if (osmdSteps[i].beat >= winStart - 1e-4) { target = i; break; }
    }
    while (cursorStep < target) { cur.next(); cursorStep++; }
    updatePos(osmdSteps[target] ? osmdSteps[target].measure : from);
    scrollCursorIntoView(true);   // force: we're paused, bypass the playing guard
  }

  /* ---------- Transport ----------------------------------------------- */

  // Single source of truth for the "Playing…" status line, so a mid-play toggle
  // of the melody Playing/Muted seg or the "Also play my part" checkbox can
  // repaint it truthfully (they used to only re-mix, leaving the line lying).
export function statusForPlaying() {
    if (isMonophonic()) {
      return melodyMuted
        ? 'Melody muted — sing it yourself. Follow the gold cursor.'
        : 'Playing the melody — follow along or sing with it.';
    }
    const name = VOICE_DEFS.find((v) => v.key === selectedVoice)?.name;
    return el.hearMine.checked
      ? `Playing — ${name} audible (practising along).`
      : `Playing — ${name} muted (sing it). Follow the gold cursor.`;
  }

export async function playPause() {
    if (playState === 'playing') { pause(); return; }
    if (playState === 'paused') { await resume(); return; }
    await startPlayback();
  }

export async function startPlayback() {
    if (!(await unlockAudio())) return;   // suspended-context guard (issue #63)
    // Defensive lazy-load path (issue #66): covers a persisted 'voices'
    // preference restored at boot (loadInstrumentMode never fetches) — the
    // FIRST Play after that is what actually triggers the sample load, same
    // status-line/fallback behavior as switching the toggle mid-session.
    if (instrumentMode === 'voices' && !voiceBuffers && !voiceLoadFailed) {
      try { await ensureVoiceSamplesLoaded(); setStatus('Voices loaded.'); }
      catch (e) {
        instrumentMode = 'synth';
        updateInstrumentUI();
        setStatus('Voices unavailable — using synth instead. (' + (e && e.message ? e.message : 'load failed') + ')');
      }
    }
    if (!instruments.length || builtMode !== effectiveMode()) buildAudio();
    applyMix();
    // Windowed scores: make sure the loop range is actually rendered before we
    // schedule cursor steps (the cursor iterator is clipped to the render
    // window). No-op for small pieces / already-covered ranges.
    ensureRenderWindow(Number(el.loopFrom.value), Number(el.loopTo.value));
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    buildScopeLane();
    scheduleAll();
    // Scoring v1: start a fresh sample buffer + lap session (owned by scoring-ui.js).
    beginScoringSession();
    playState = 'playing';
    resetCursor();
    Tone.Transport.start('+0.1');
    updatePlayUI();
    setOverlay(false);
    setStatus(statusForPlaying());
  }

  function pause() {
    Tone.Transport.pause();
    playState = 'paused';
    updatePlayUI();
    setOverlay(true);
    setStatus('Paused — scroll freely. ▶ resumes where you left off.');
  }

  async function resume() {
    if (!(await unlockAudio())) return;   // suspended-context guard (issue #63)
    // If the unlock had to recreate the context (iOS interruption recovery), the
    // paused schedule + position died with the old context — restart cleanly
    // from the loop window rather than resuming a wedged, empty transport.
    if (_lastUnlockRecreated) { await startPlayback(); return; }
    playState = 'playing';
    Tone.Transport.start();
    updatePlayUI();
    setOverlay(false);
    setStatus(statusForPlaying());
  }

export function stop() {
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    clearSchedule();
    if (osmd && osmd.cursor) osmd.cursor.hide();
    // Score whatever's left of the current lap (final/partial lap); no-op with
    // the mic off. Owned by scoring-ui.js.
    const scored = finalizeScoringOnStop();
    playState = 'stopped';
    flushDeferredRender();   // apply a render deferred during playback (loader.js)
    updatePos(null);
    updatePlayUI();
    setOverlay(true);
    // Keep a just-produced score summary on the surface across this Stop and any
    // repeated Stops (e.g. a manual Stop after an auto-stop) — only fall back to
    // "Stopped." when no summary is showing. Cleared by the next Play.
    if (!scored && !scoreSummaryShown) setStatus('Stopped.');
  }

export function updatePlayUI() {
    el.play.textContent =
      playState === 'playing' ? '⏸ Pause' :
      playState === 'paused' ? '▶ Resume' : '▶ Play';
  }

  /* ---------- Transport overlay (fixed bottom sheet) -------------------- */

export function setOverlay(expanded) {
    el.transport.classList.toggle('collapsed', !expanded);
    el.expandHandle.setAttribute('aria-expanded', String(expanded));
  }

export function initOverlay() {
    // Calm Surface (#73): the whole handle row is the expand/collapse target
    // (bigger than the bare chevron). Skip taps on the status text — it owns its
    // own triple-tap gesture (audiodebug, #74) — and on the Retry button.
    const toggleFromHandle = (e) => {
      if (e.target.closest('#status') || e.target.closest('#retryStart')) return;
      setOverlay(el.transport.classList.contains('collapsed'));
    };
    if (el.handleRow) el.handleRow.addEventListener('click', toggleFromHandle);
    else el.expandHandle.addEventListener('click', () =>
      setOverlay(el.transport.classList.contains('collapsed')));
    // One-tap mute (#61): the voice chip no longer expands the transport — it
    // toggles whether your part is audible (logic owned by voices.js).
    el.voiceChip.addEventListener('click', toggleChipMute);
    // Tabbed panes (§3): three .segbtn tabs switch the visible pane. Default
    // Practice on every load; no persistence. The ResizeObserver below keeps
    // --transport-h live as the expanded height changes with the active pane.
    if (el.paneStrip) el.paneStrip.addEventListener('click', (e) => {
      const b = e.target.closest('[data-pane]');
      if (!b) return;
      const name = b.dataset.pane;
      [...el.paneStrip.children].forEach((x) => {
        const on = x === b;
        x.classList.toggle('active', on);
        x.setAttribute('aria-selected', String(on));
      });
      [el.panePractice, el.paneSound, el.paneMore].forEach((p) => {
        if (p) p.classList.toggle('active', p.dataset.pane === name);
      });
    });
    // Reserve page bottom padding = live overlay height, so the overlay never
    // covers the singscope's now-line (or any content) at full page scroll.
    const sync = () => document.documentElement.style.setProperty(
      '--transport-h', el.transport.offsetHeight + 'px');
    new ResizeObserver(sync).observe(el.transport);
    sync();
  }

