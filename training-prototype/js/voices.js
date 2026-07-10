/* voices.js — SATB voice picker, monophonic Playing/Muted toggle, verse
 * toggle, the transport voice chip, and the singscope lane feed. Owns
 * selectedVoice / activeVerse / melodyMuted.
 */
import { el, setStatus, VOICE_DEFS } from './state.js';
import { parsed, isMonophonic, applyVerseLyrics, clampMeasure, measureBeatRange } from './model.js';
import { applyVoiceColors } from './loader.js';
import { applyMix, statusForPlaying, playState } from './transport.js';

export let selectedVoice = 'S';
export let activeVerse = 1;       // 1-based lyric verse currently in n.lyric
export let melodyMuted = false;   // single-voice mute flag (audible on load)

export function buildVoicePicker() {
    el.voicePicker.innerHTML = '';
    const present = parsed.parts.map((p) => p.voiceKey);
    // ensure the selected voice actually exists (recolors gold if it changed) —
    // for a 1-voice piece this pins selectedVoice to the sole part so scoring
    // targets + gold coloring track it even when it isn't Soprano.
    if (!present.includes(selectedVoice) && present.length) selectVoice(present[0]);

    if (isMonophonic()) { buildMelodyToggle(); updateVoiceChip(); return; }

    VOICE_DEFS.filter((v) => present.includes(v.key)).forEach((v) => {
      const b = document.createElement('button');
      b.className = 'vbtn' + (v.key === selectedVoice ? ' active' : '');
      b.textContent = v.label;
      b.title = `Practise ${v.name} (muted in playback, gold in score)`;
      b.setAttribute('role', 'tab');
      b.addEventListener('click', () => selectVoice(v.key));
      el.voicePicker.appendChild(b);
    });
    updateVoiceChip();
  }

  // 2-segment Playing/Muted control shown in place of the voice picker for
  // single-voice pieces. Reuses the .seg/.segbtn styles.
  function buildMelodyToggle() {
    el.voicePicker.innerHTML = '';
    const seg = document.createElement('div');
    seg.className = 'seg';
    seg.setAttribute('role', 'tablist');
    seg.setAttribute('aria-label', 'Melody playback');
    [['🔊 Playing', false], ['🔇 Muted', true]].forEach(([label, muted]) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'segbtn' + (muted === melodyMuted ? ' active' : '');
      b.textContent = label;
      b.title = muted ? 'Mute the melody so you sing it yourself'
                      : 'Play the melody so you can follow (or sing) along';
      b.setAttribute('role', 'tab');
      b.addEventListener('click', () => setMelodyMuted(muted));
      seg.appendChild(b);
    });
    el.voicePicker.appendChild(seg);
  }

  function setMelodyMuted(muted) {
    melodyMuted = !!muted;
    if (el.voicePicker) {
      const segs = el.voicePicker.querySelectorAll('.segbtn');
      if (segs[0]) segs[0].classList.toggle('active', !melodyMuted);
      if (segs[1]) segs[1].classList.toggle('active', melodyMuted);
    }
    applyMix();
    updateVoiceChip();
    if (playState === 'playing') setStatus(statusForPlaying());
  }

  function selectVoice(key) {
    selectedVoice = key;
    [...el.voicePicker.children].forEach((b) =>
      b.classList.toggle('active', b.textContent === (VOICE_DEFS.find((v) => v.key === key)?.label)));
    applyVoiceColors();
    applyMix();
    buildScopeLane();
    updateVoiceChip();
  }

export function updateVoiceChip() {
    if (isMonophonic()) {
      // 1-voice piece: the sole line is the melody. Show 🔇 only when muted.
      el.voiceChip.textContent = (melodyMuted ? '🔇 ' : '') + 'Melody';
      el.voiceChip.title = melodyMuted
        ? 'Melody muted — tap to hear it'
        : 'Melody playing — tap to mute it (you sing it)';
      return;
    }
    const def = VOICE_DEFS.find((v) => v.key === selectedVoice);
    const base = def ? `${def.label} · ${def.name}` : selectedVoice;
    // Persistent mute affordance: the selected voice is muted in the mix unless
    // "Also play my part" is checked — prefix 🔇 so the chip advertises it.
    const muted = !el.hearMine.checked;
    el.voiceChip.textContent = (muted ? '🔇 ' : '') + base;
    // One-tap mute (#61): the chip's tap toggles whether your part is audible.
    el.voiceChip.title = muted
      ? 'Your part is muted — tap to hear it'
      : 'Your part is playing — tap to mute it (you sing it)';
  }

  /* ---------- One-tap mute (#61) ---------------------------------------- *
   * The mini-row voice chip toggles whether YOUR part is audible. The
   * "Also play my part" checkbox (#hearMine) stays the single source of truth
   * for multi-voice pieces, so chip + checkbox can never desync; monophonic
   * pieces flip the melody-mute flag. Wired to the chip click by
   * transport.initOverlay (replacing the old chip→expand binding). */
export function toggleChipMute() {
    if (isMonophonic()) { setMelodyMuted(!melodyMuted); return; }
    if (!el.hearMine) return;
    el.hearMine.checked = !el.hearMine.checked;
    applyMix();
    updateVoiceChip();
    if (playState === 'playing') setStatus(statusForPlaying());
  }

  /* ---------- Verse toggle ---------------------------------------------- *
   * Multi-verse pieces (Sunday vs. weekday antiphon texts etc.) carry a
   * second (or later) lyric line on the same notes. The toggle is built fresh
   * per piece — hidden entirely (zero DOM, zero overhead) for the ~2/3 of the
   * library that only ever has one verse.
   */

export function buildVersePicker() {
    if (!el.verseRow || !el.versePicker) return;
    const max = (parsed && parsed.maxVerse) || 1;
    el.versePicker.innerHTML = '';
    if (max < 2) { el.verseRow.hidden = true; return; }
    el.verseRow.hidden = false;
    for (let v = 1; v <= max; v++) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'segbtn' + (v === activeVerse ? ' active' : '');
      b.textContent = 'Verse ' + v;
      b.title = `Show verse ${v}'s lyrics on the singscope`;
      b.setAttribute('role', 'tab');
      b.addEventListener('click', () => setVerse(v));
      el.versePicker.appendChild(b);
    }
  }

  // Switch the ACTIVE verse: re-derive n.lyric for every note (with cross-part
  // borrowing re-run for the new verse — see applyVerseLyrics) and rebuild the
  // scope lane. Data-only (same as the bpm/loop-range handlers, which already
  // call buildScopeLane unconditionally during playback) — OSMD is untouched
  // (the staff already shows both verses stacked) and playback scheduling is
  // untouched, so this is safe to call whether stopped, playing, or paused.
export function setVerse(v) {
    if (!parsed) return;
    const max = parsed.maxVerse || 1;
    v = Math.max(1, Math.min(Math.round(v) || 1, max));
    if (v === activeVerse) return;
    activeVerse = v;
    applyVerseLyrics(activeVerse);
    buildScopeLane();
    if (el.versePicker) {
      [...el.versePicker.children].forEach((b, i) => b.classList.toggle('active', i + 1 === v));
    }
  }

  /* ---------- Singscope lane ------------------------------------------- */

  // Feed the singscope the selected voice's target notes (gold lane), the
  // other voices (faint context), and the loop window length — in seconds
  // relative to transport time 0 (which is the loop-window start).
export function buildScopeLane() {
    if (!parsed || !window.TrainingScope) return;
    const spb = 60 / Number(el.bpm.value);
    const from = clampMeasure(Number(el.loopFrom.value));
    const to = clampMeasure(Number(el.loopTo.value));
    const { start: winStart, end: winEnd } = measureBeatRange(from, to);
    const mk = (p) => p.notes
      .filter((n) => n.startBeat >= winStart - 1e-6 && n.startBeat < winEnd - 1e-6)
      .map((n) => ({
        start: (n.startBeat - winStart) * spb,
        end: (n.startBeat - winStart + n.durBeat) * spb,
        midi: n.midi,
        lyric: n.lyric || null,
      }));
    const sel = parsed.parts.find((p) => p.voiceKey === selectedVoice);
    TrainingScope.setLane(
      sel ? mk(sel) : [],
      parsed.parts.filter((p) => p !== sel).flatMap(mk),
      (winEnd - winStart) * spb,
    );
  }

// Per-load reset of voice/verse state (called by loader.loadScore).
export function resetVoiceStateForLoad() { activeVerse = 1; melodyMuted = false; }

