#!/usr/bin/env node
/* generate-voices.mjs — offline formant-synthesis generator for the "Voices"
 * sampled instrument (GitHub issue #66).
 *
 * WHY GENERATED INSTEAD OF DOWNLOADED (see samples/README.md for the full
 * writeup): the issue's priority order asks for CC0/public-domain samples
 * first. VSCO-2 Community Edition and VCSL (both CC0, both actually
 * downloaded and inspected — see README "Sources checked") cover orchestral
 * instruments and a pipe organ, but neither includes human-voice/choir
 * samples at all. No other CC0 multi-note vocal "ah" set was found that's
 * fetchable-and-verifiable in the time available. Per the issue's own
 * instruction — "REJECT anything with unclear licensing — when in doubt,
 * generate" — this script renders our own "ah"-vowel pad instead: zero
 * external assets, zero rights risk, exact provenance = this file.
 *
 * METHOD: additive harmonic synthesis (a bright, bandlimited near-sawtooth
 * source — like a glottal pulse train) passed through a static formant
 * filter bank (4 resonance peaks tuned to the vowel "ah" /ɑ/), plus a
 * slow-fading-in vibrato, gentle pitch jitter/amplitude shimmer, and a
 * touch of onset breathiness. One shared "ah" timbre is used across the
 * whole S/A/T/B range (see README for why a single set beats splitting into
 * two — budget + the additive model already thins naturally at high f0).
 *
 * OUTPUT: NOTES.length mono 44.1kHz WAVs at samples/voices/ah_<midi>.wav.
 * These are NOT what ships — they're piped through ffmpeg to Ogg/Opus
 * afterwards (see encode-voices.sh in this directory) to hit the ≤3MB
 * budget; the .wav intermediates are deleted once the .ogg files are
 * verified. Re-run both scripts together any time the note set, duration,
 * or formant tuning changes.
 *
 * Run: node samples/generate-voices.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, 'voices');
fs.mkdirSync(OUT_DIR, { recursive: true });

const SR = 44100;
// Rendered sustain length. Longer than the "~1.5-2.5s" guideline on purpose:
// the vendored Tone.js build's Sampler has no loop-point support (it plays
// the decoded buffer once, at a pitch-shifted rate, and only fades out early
// via triggerRelease) — so the FILE itself must outlast realistic held notes
// or a long note goes silent before its printed duration ends. 3.5s covers
// the app's practical tempo/note-value range (BPM 30-160) comfortably enough
// without blowing the size budget; see README for the known edge case at
// very slow tempo + very long note values.
const DUR = 3.5;
// MIDI notes to render — E2..~G#5 (covers the ~E2-A5 SATB span with Tone.
// Sampler's own pitch-shift filling the ±2-semitone gaps), every 4 semitones.
const NOTES = [40, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80];

// "ah" /ɑ/ formants — generic adult voice, one set shared across the whole
// range (typical textbook estimates for a relaxed open-back vowel).
const FORMANTS = [
  { f: 700, bw: 80, gain: 1.00 },
  { f: 1150, bw: 90, gain: 0.55 },
  { f: 2700, bw: 120, gain: 0.22 },
  { f: 3300, bw: 130, gain: 0.12 },
];

// Resonant-peak magnitude response (sum of the 4 formant peaks), evaluated
// per-harmonic — this is what turns a bright buzzy source into "ah".
function formantGain(freq) {
  let g = 0;
  for (const f of FORMANTS) {
    const q = f.f / f.bw;
    const x = freq / f.f - f.f / freq;
    g += f.gain / Math.sqrt(1 + q * q * x * x);
  }
  return g;
}

function midiToFreq(m) { return 440 * Math.pow(2, (m - 69) / 12); }

function synthNote(midi) {
  const f0 = midiToFreq(midi);
  const n = Math.round(DUR * SR);
  const out = new Float32Array(n);
  const maxHarmonic = Math.min(48, Math.floor(17000 / f0));
  let jitter = 0;
  // Running phase of the FUNDAMENTAL, integrated sample-by-sample. Harmonic h
  // reuses it as phase*h. This is the whole ballgame for a time-varying pitch:
  // an earlier version wrote sin(2π·fInst·h·t) with fInst carrying the vibrato
  // and jitter — but multiplying a *time-varying* instantaneous frequency by
  // absolute time t does NOT give the intended phase. Its derivative is
  // fInst·h + t·fInst'·h, so the spurious t·fInst' term makes the effective
  // frequency error grow without bound as the note sustains (the random-walk
  // jitter's derivative alone smears each harmonic by ±kHz within a second) —
  // the additive tone dissolved into broadband, harsh white noise (issue #71).
  // Integrating phase (phase += 2π·fInst/SR) modulates frequency correctly, so
  // vibrato/jitter stay the few-cent wobble they're meant to be.
  let phase = 0;

  for (let i = 0; i < n; i++) {
    const t = i / SR;

    // Vibrato fades in over ~0.4-1.0s (real singers start straighter), then
    // sits at a modest ~12-cent depth. Slow pitch jitter (a clamped random
    // walk) adds organic imperfection on top.
    const vibDepth = Math.min(1, Math.max(0, (t - 0.4) / 0.6)) * 0.012;
    const vibrato = Math.sin(2 * Math.PI * 5.5 * t) * vibDepth;
    jitter += (Math.random() - 0.5) * 0.0006;
    jitter = Math.max(-0.004, Math.min(0.004, jitter));
    const fInst = f0 * (1 + vibrato + jitter);
    phase += (2 * Math.PI * fInst) / SR;   // integrate the fundamental's phase

    let s = 0;
    for (let h = 1; h <= maxHarmonic; h++) {
      const freq = fInst * h;
      if (freq > 17000) break;
      s += (1 / h) * formantGain(freq) * Math.sin(phase * h);
    }

    // Onset breathiness only: a light noise transient at the attack (reads as
    // breath, gone by ~0.3s), with NO sustained noise floor — the earlier
    // constant +0.008 term left an always-on hiss layered over the sustain.
    const breathEnv = 0.012 * Math.exp(-t * 8);
    s += breathEnv * (Math.random() * 2 - 1);

    // Amplitude envelope: soft 60ms attack, gentle 4.7Hz shimmer through the
    // sustain, exponential tail from 72% of the render so a note that plays
    // to the buffer's natural end (no triggerRelease) still fades musically
    // instead of clipping to silence.
    const attack = Math.min(1, t / 0.06);
    const shimmer = 1 + 0.03 * Math.sin(2 * Math.PI * 4.7 * t);
    const tailStart = DUR * 0.72;
    const release = t > tailStart ? Math.exp(-(t - tailStart) * 1.6) : 1;

    out[i] = s * attack * shimmer * release;
  }

  // Normalize each note to the same peak so the range plays back evenly.
  // Target 0.65, not 1.0: lossy Opus encoding commonly overshoots the source
  // peak by a couple dB on sharp-harmonic material (ringing on transients —
  // see encode-voices.sh's header), and this file is one of several summed
  // further down the app's mix bus (Gain(0.25) + Limiter(-1) — transport.js).
  // 0.65 was picked empirically after an A/B render (see
  // .scratch/issue-66/render-ab.mjs, not committed): a more conservative 0.4
  // target made "Voices" mode sound noticeably quieter than the Synth path
  // at the same 0.25 per-part gain (RMS ~-22dB vs. the synth's ~-12dB —
  // clearly washed-out side by side). 0.65 narrows that gap; the remaining
  // difference is a real, honest tradeoff against keeping individual sample
  // peaks close to 0dBFS post-encode — see encode-voices.sh's astats check.
  let peak = 0;
  for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(out[i]));
  const scale = peak > 0 ? 0.65 / peak : 1;
  for (let i = 0; i < n; i++) out[i] *= scale;
  return out;
}

function writeWav(filePath, samples, sr) {
  const bytesPerSample = 2;
  const dataSize = samples.length * bytesPerSample;
  const buf = Buffer.alloc(44 + dataSize);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + dataSize, 4);
  buf.write('WAVE', 8);
  buf.write('fmt ', 12);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);   // PCM
  buf.writeUInt16LE(1, 22);   // mono
  buf.writeUInt32LE(sr, 24);
  buf.writeUInt32LE(sr * bytesPerSample, 28);
  buf.writeUInt16LE(bytesPerSample, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(dataSize, 40);
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    buf.writeInt16LE(Math.round(v * 32767), 44 + i * 2);
  }
  fs.writeFileSync(filePath, buf);
}

NOTES.forEach((midi) => {
  const samples = synthNote(midi);
  const name = `ah_${String(midi).padStart(3, '0')}`;
  writeWav(path.join(OUT_DIR, name + '.wav'), samples, SR);
  console.log('wrote', name + '.wav', `(f0=${midiToFreq(midi).toFixed(1)}Hz)`);
});
