/* ChanterLab — Choir Training (SATB) prototype
 *
 * Renders an SATB MusicXML score with OpenSheetMusicDisplay, synthesizes each
 * voice with its own Tone.js synth, and lets a singer pick one voice to
 * practise:
 *   - the picked voice is MUTED in the audio mix (you supply it),
 *   - its noteheads are painted GOLD (#d4af37) and the others dimmed gray,
 *   - a follow cursor advances through the score in time with playback,
 *   - tempo is adjustable and a measure range can be looped.
 *
 * Pure client-side. No build step. Libraries are vendored in ./vendor.
 */
(() => {
  'use strict';

  const GOLD = '#d4af37';
  const DIM = '#9aa0a6';
  const VOICE_COLORS = { S: GOLD, A: GOLD, T: GOLD, B: GOLD }; // selected always gold

  // Canonical SATB order + labels; matched to parts by index and by name.
  const VOICE_DEFS = [
    { key: 'S', label: 'S', name: 'Soprano' },
    { key: 'A', label: 'A', name: 'Alto' },
    { key: 'T', label: 'T', name: 'Tenor' },
    { key: 'B', label: 'B', name: 'Bass' },
  ];

  const PIECES = [
    { id: 'control', label: 'Control — hand-made clean SATB', url: 'content/control_satb.musicxml' },
    { id: 'trisagion_v', label: 'Trisagion (antiochian.org, vector extraction)', url: 'content/trisagion_vector.musicxml' },
    { id: 'cherubic_v', label: 'Cherubic Hymn (antiochian.org, vector extraction)', url: 'content/cherubic_vector.musicxml' },
    { id: 'anaphora_v', label: 'Anaphora (antiochian.org, vector extraction)', url: 'content/anaphora_vector.musicxml' },
    { id: 'trisagion', label: 'Trisagion (oemer OMR — kept for comparison)', url: 'content/trisagion_omr.musicxml' },
  ];

  const el = {
    osmd: document.getElementById('osmd'),
    status: document.getElementById('status'),
    piece: document.getElementById('pieceSelect'),
    voicePicker: document.getElementById('voicePicker'),
    bpm: document.getElementById('bpm'),
    bpmOut: document.getElementById('bpmOut'),
    play: document.getElementById('play'),
    stop: document.getElementById('stop'),
    loopFrom: document.getElementById('loopFrom'),
    loopTo: document.getElementById('loopTo'),
    loopOn: document.getElementById('loopOn'),
    hearMine: document.getElementById('hearMine'),
    micBtn: document.getElementById('micBtn'),
    scope: document.getElementById('scope'),
    scopeReadout: document.getElementById('scopeReadout'),
    scopeHint: document.getElementById('scopeHint'),
  };

  let osmd = null;
  let parsed = null;         // { parts: [ {voiceKey, notes:[{midi,startBeat,durBeat,measure}]} ], measureCount }
  let selectedVoice = 'S';
  let synths = [];           // Tone.PolySynth per part
  let gains = [];            // Tone.Gain per part
  let scheduledIds = [];
  let cursorTimeline = [];   // sorted unique onset beats for cursor stepping
  let playing = false;

  const setStatus = (m) => { el.status.textContent = m; };

  /* ---------- MusicXML parsing ---------------------------------------- */

  const STEP_SEMITONE = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };

  // fifths -> which steps are altered by the key signature (+1 sharp / -1 flat)
  function keyAlterMap(fifths) {
    const sharps = ['F', 'C', 'G', 'D', 'A', 'E', 'B'];
    const flats = ['B', 'E', 'A', 'D', 'G', 'C', 'F'];
    const map = {};
    if (fifths > 0) sharps.slice(0, fifths).forEach((s) => (map[s] = 1));
    else if (fifths < 0) flats.slice(0, -fifths).forEach((s) => (map[s] = -1));
    return map;
  }

  function midiOf(step, octave, alter) {
    return 12 * (octave + 1) + STEP_SEMITONE[step] + alter;
  }

  function textOf(node, tag) {
    const n = node.getElementsByTagName(tag)[0];
    return n ? n.textContent.trim() : null;
  }

  function parseMusicXML(xmlText) {
    const doc = new DOMParser().parseFromString(xmlText, 'application/xml');
    if (doc.getElementsByTagName('parsererror').length) throw new Error('XML parse error');

    const partNodes = Array.from(doc.getElementsByTagName('part'));
    const scoreParts = Array.from(doc.getElementsByTagName('score-part'));
    const partNames = {};
    scoreParts.forEach((sp) => {
      partNames[sp.getAttribute('id')] = (textOf(sp, 'part-name') || '').trim();
    });

    let measureCount = 0;
    const parts = partNodes.map((partNode, idx) => {
      const id = partNode.getAttribute('id');
      const name = partNames[id] || `Part ${idx + 1}`;
      // Match to SATB by name, else by index order.
      let voiceDef =
        VOICE_DEFS.find((v) => name.toLowerCase().startsWith(v.name.toLowerCase())) ||
        VOICE_DEFS[idx] || { key: `P${idx}`, label: `${idx + 1}`, name };

      let divisions = 1;
      let fifths = 0;
      let keyMap = {};
      const notes = [];
      let beatCursor = 0; // in quarter notes from start of piece
      const measures = Array.from(partNode.getElementsByTagName('measure'));
      measureCount = Math.max(measureCount, measures.length);

      measures.forEach((measureNode, mIdx) => {
        const measureNumber = parseInt(measureNode.getAttribute('number'), 10) || (mIdx + 1);
        // attributes may reset divisions/key mid-piece
        const attrs = measureNode.getElementsByTagName('attributes');
        for (const a of attrs) {
          const d = textOf(a, 'divisions');
          if (d) divisions = parseInt(d, 10);
          const f = a.getElementsByTagName('fifths')[0];
          if (f) { fifths = parseInt(f.textContent, 10); keyMap = keyAlterMap(fifths); }
        }
        const measureStartBeat = beatCursor;
        const localAlter = {}; // measure-scoped accidental memory: step+octave -> alter

        // iterate children in order to honor <backup>/<forward>/<chord>
        for (const child of Array.from(measureNode.children)) {
          if (child.tagName === 'backup') {
            const dur = parseInt(textOf(child, 'duration') || '0', 10);
            beatCursor -= dur / divisions;
          } else if (child.tagName === 'forward') {
            const dur = parseInt(textOf(child, 'duration') || '0', 10);
            beatCursor += dur / divisions;
          } else if (child.tagName === 'note') {
            const isChord = child.getElementsByTagName('chord').length > 0;
            const isRest = child.getElementsByTagName('rest').length > 0;
            const durEl = textOf(child, 'duration');
            const durBeat = durEl ? parseInt(durEl, 10) / divisions : 0;
            const onset = isChord ? (notes.length ? notes[notes.length - 1].startBeat : beatCursor) : beatCursor;

            if (!isRest) {
              const pitch = child.getElementsByTagName('pitch')[0];
              if (pitch) {
                const step = textOf(pitch, 'step');
                const octave = parseInt(textOf(pitch, 'octave'), 10);
                const alterEl = textOf(pitch, 'alter');
                const key = step + octave;
                let alter;
                if (alterEl !== null) { alter = parseInt(alterEl, 10); localAlter[key] = alter; }
                else if (key in localAlter) alter = localAlter[key];
                else alter = keyMap[step] || 0;
                notes.push({
                  midi: midiOf(step, octave, alter),
                  startBeat: onset,
                  durBeat,
                  measure: measureNumber,
                });
              }
            }
            if (!isChord) beatCursor += durBeat;
          }
        }
        // keep measures contiguous even if a part under-fills (defensive)
        if (beatCursor < measureStartBeat) beatCursor = measureStartBeat;
      });

      return { voiceKey: voiceDef.key, voiceName: voiceDef.name, index: idx, notes };
    });

    return { parts, measureCount };
  }

  /* ---------- OSMD rendering + coloring ------------------------------- */

  // Narrow screens: drop the engraved title/part names (the voice picker and
  // gold coloring carry that) and zoom OSMD out so systems fit the width.
  function isNarrow() { return el.osmd.clientWidth < 560; }

  function applyResponsiveOsmdOptions() {
    const narrow = isNarrow();
    osmd.setOptions({
      drawTitle: !narrow,
      drawSubtitle: !narrow,
      drawComposer: !narrow,
      drawLyricist: false,
      drawPartNames: !narrow,
    });
    osmd.zoom = narrow ? 0.55 : 1.0;
  }

  async function loadScore(url) {
    setStatus('Loading score…');
    const xml = await (await fetch(url)).text();
    parsed = parseMusicXML(xml);

    if (!osmd) {
      osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(el.osmd, {
        autoResize: true,
        backend: 'svg',
        drawTitle: true,
        drawPartNames: true,
        followCursor: true,
        cursorsOptions: [{ type: 0, color: GOLD, alpha: 0.4, follow: true }],
      });
    }
    applyResponsiveOsmdOptions();
    await osmd.load(xml);
    osmd.render();
    buildVoicePicker();
    applyVoiceColors();
    // default loop = whole piece
    el.loopFrom.value = 1;
    el.loopTo.value = parsed.measureCount;
    buildScopeLane();
    setStatus(`Loaded: ${parsed.parts.length} voices, ${parsed.measureCount} measures. Pick a voice and press Play.`);
  }

  // Color the selected voice's noteheads gold, all others dim gray. OSMD keeps
  // these colors across re-renders because we set them on the source notes.
  function applyVoiceColors() {
    const instruments = osmd.Sheet.Instruments;
    instruments.forEach((instr, idx) => {
      const isSelected = matchesSelected(idx, instr.Name);
      const color = isSelected ? GOLD : DIM;
      instr.Voices.forEach((voice) => {
        voice.VoiceEntries.forEach((ve) => {
          ve.Notes.forEach((note) => {
            note.NoteheadColor = color;
            if ('NoteheadColorXml' in note) note.NoteheadColorXml = color;
          });
        });
      });
    });
    osmd.render();
  }

  function matchesSelected(partIndex, instrName) {
    const p = parsed.parts[partIndex];
    if (p) return p.voiceKey === selectedVoice;
    // fallback by name
    const def = VOICE_DEFS.find((v) => v.key === selectedVoice);
    return def && (instrName || '').toLowerCase().startsWith(def.name.toLowerCase());
  }

  function buildVoicePicker() {
    el.voicePicker.innerHTML = '';
    const present = parsed.parts.map((p) => p.voiceKey);
    VOICE_DEFS.filter((v) => present.includes(v.key)).forEach((v) => {
      const b = document.createElement('button');
      b.className = 'vbtn' + (v.key === selectedVoice ? ' active' : '');
      b.textContent = v.label;
      b.title = `Practise ${v.name} (muted in playback, gold in score)`;
      b.setAttribute('role', 'tab');
      b.addEventListener('click', () => selectVoice(v.key));
      el.voicePicker.appendChild(b);
    });
    // ensure selected voice actually exists
    if (!present.includes(selectedVoice) && present.length) selectVoice(present[0]);
  }

  function selectVoice(key) {
    selectedVoice = key;
    [...el.voicePicker.children].forEach((b) =>
      b.classList.toggle('active', b.textContent === (VOICE_DEFS.find((v) => v.key === key)?.label)));
    applyVoiceColors();
    applyMix();
    buildScopeLane();
  }

  /* ---------- Singscope lane ------------------------------------------- */

  // Feed the singscope the selected voice's target notes (gold lane), the
  // other voices (faint context), and the loop window length — in seconds
  // relative to transport time 0 (which is the loop-window start).
  function buildScopeLane() {
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
      }));
    const sel = parsed.parts.find((p) => p.voiceKey === selectedVoice);
    TrainingScope.setLane(
      sel ? mk(sel) : [],
      parsed.parts.filter((p) => p !== sel).flatMap(mk),
      (winEnd - winStart) * spb,
    );
  }

  /* ---------- Audio (Tone.js) ----------------------------------------- */

  function buildAudio() {
    disposeAudio();
    synths = [];
    gains = [];
    parsed.parts.forEach(() => {
      const gain = new Tone.Gain(0.25).toDestination();
      const synth = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: 'triangle' },
        envelope: { attack: 0.02, decay: 0.1, sustain: 0.8, release: 0.25 },
      }).connect(gain);
      synths.push(synth);
      gains.push(gain);
    });
  }

  function disposeAudio() {
    synths.forEach((s) => s.dispose());
    gains.forEach((g) => g.dispose());
    synths = []; gains = [];
  }

  // Mute the selected voice unless "also hear my part" is checked.
  function applyMix() {
    parsed.parts.forEach((p, idx) => {
      if (!gains[idx]) return;
      const isSelected = p.voiceKey === selectedVoice;
      const mute = isSelected && !el.hearMine.checked;
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
          synths[idx].triggerAttackRelease(midiToFreq(n.midi), dur, time);
        }, t);
        scheduledIds.push(id);
      });
    });

    // cursor timeline = unique onsets in window (any voice)
    const onsets = new Set();
    parsed.parts.forEach((p) => p.notes.forEach((n) => {
      if (n.startBeat >= winStart - 1e-6 && n.startBeat < winEnd - 1e-6) onsets.add(round(n.startBeat));
    }));
    cursorTimeline = [...onsets].sort((a, b) => a - b);

    // schedule cursor stepping
    cursorTimeline.forEach((beat, i) => {
      const t = (beat - winStart) * spb;
      const id = Tone.Transport.schedule(() => stepCursorTo(i), t);
      scheduledIds.push(id);
    });

    const total = (winEnd - winStart) * spb;
    if (loop) {
      Tone.Transport.loop = true;
      Tone.Transport.loopStart = 0;
      Tone.Transport.loopEnd = total;
      const id = Tone.Transport.schedule(() => resetCursor(), total - 1e-3);
      scheduledIds.push(id);
    } else {
      Tone.Transport.loop = false;
      const id = Tone.Transport.schedule(() => stop(), total + 0.3);
      scheduledIds.push(id);
    }
  }

  const round = (x) => Math.round(x * 1000) / 1000;
  function clampMeasure(m) { return Math.min(Math.max(1, m || 1), parsed.measureCount); }

  // Build a per-measure beat map from the longest part (most onsets), so the
  // loop window maps measures->beats even without explicit barline math.
  function measureBeatRange(fromMeasure, toMeasure) {
    let start = Infinity, end = 0;
    parsed.parts.forEach((p) => p.notes.forEach((n) => {
      if (n.measure >= fromMeasure && n.measure <= toMeasure) {
        start = Math.min(start, n.startBeat);
        end = Math.max(end, n.startBeat + n.durBeat);
      }
    }));
    if (!isFinite(start)) { start = 0; end = 0; }
    return { start, end };
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
    }
    osmd.cursor.reset();
    osmd.cursor.show();
    if (osmd.cursor.update) osmd.cursor.update();
    cursorStep = 0;
    scrollCursorIntoView();
  }
  let cursorStep = 0;
  function stepCursorTo(i) {
    if (!osmd.cursor) return;
    if (i === 0) { osmd.cursor.reset(); osmd.cursor.show(); cursorStep = 0; scrollCursorIntoView(); return; }
    while (cursorStep < i) { osmd.cursor.next(); cursorStep++; }
    scrollCursorIntoView();
  }

  // Keep the follow cursor visible inside the scrollable score container
  // (essential on mobile where the score is a mini view).
  function scrollCursorIntoView() {
    const cEl = osmd && osmd.cursor && osmd.cursor.cursorElement;
    const wrap = el.osmd;
    if (!cEl || !wrap) return;
    const top = cEl.offsetTop;
    const bottom = top + cEl.offsetHeight;
    const vTop = wrap.scrollTop;
    const vBottom = vTop + wrap.clientHeight;
    if (top < vTop + 10 || bottom > vBottom - 10) {
      wrap.scrollTo({
        top: Math.max(0, top - wrap.clientHeight * 0.25),
        behavior: 'smooth',
      });
    }
    const left = cEl.offsetLeft;
    if (left < wrap.scrollLeft + 10 || left > wrap.scrollLeft + wrap.clientWidth - 30) {
      wrap.scrollTo({ left: Math.max(0, left - wrap.clientWidth * 0.3), behavior: 'smooth' });
    }
  }

  /* ---------- Transport ----------------------------------------------- */

  async function play() {
    if (playing) return;
    await Tone.start();
    if (!synths.length) buildAudio();
    applyMix();
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    resetCursor();
    buildScopeLane();
    scheduleAll();
    Tone.Transport.start('+0.1');
    playing = true;
    setStatus(`Playing — ${VOICE_DEFS.find((v) => v.key === selectedVoice)?.name} muted (sing it). Follow the gold cursor.`);
  }

  function stop() {
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    clearSchedule();
    if (osmd && osmd.cursor) osmd.cursor.hide();
    playing = false;
    setStatus('Stopped.');
  }

  /* ---------- Wire-up ------------------------------------------------- */

  function initControls() {
    PIECES.forEach((p) => {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = p.label; el.piece.appendChild(o);
    });
    el.piece.addEventListener('change', async () => {
      stop();
      const p = PIECES.find((x) => x.id === el.piece.value);
      try { await loadScore(p.url); buildAudio(); }
      catch (e) {
        const hint = p.id !== 'control'
          ? ' — antiochian scores are gitignored (copyrighted source); regenerate via omr/README.md.'
          : ' — ' + e.message;
        setStatus('Could not load ' + p.url + hint);
      }
    });
    el.bpm.addEventListener('input', () => {
      el.bpmOut.textContent = el.bpm.value;
      buildScopeLane();
      if (playing) { stop(); play(); }
    });
    el.play.addEventListener('click', play);
    el.stop.addEventListener('click', stop);
    el.hearMine.addEventListener('change', applyMix);
    el.loopOn.addEventListener('change', () => { if (playing) { stop(); play(); } });
    el.loopFrom.addEventListener('change', buildScopeLane);
    el.loopTo.addEventListener('change', buildScopeLane);
    el.micBtn.addEventListener('click', toggleMic);

    // Re-apply responsive OSMD sizing when crossing the narrow/wide boundary.
    let wasNarrow = null;
    window.addEventListener('resize', () => {
      if (!osmd) return;
      const n = isNarrow();
      if (n !== wasNarrow) {
        wasNarrow = n;
        applyResponsiveOsmdOptions();
        osmd.render();
        applyVoiceColors();
      }
    });
  }

  /* ---------- Mic ------------------------------------------------------ */

  async function toggleMic() {
    if (TrainingScope.isMicOn()) {
      TrainingScope.micStop();
      el.micBtn.classList.remove('on');
      el.micBtn.textContent = '🎤 Mic';
      setStatus('Mic off.');
      return;
    }
    try {
      await Tone.start();                       // user gesture → audio context running
      await TrainingScope.micStart(Tone.getContext().rawContext);
      el.micBtn.classList.add('on');
      el.micBtn.textContent = '🎤 On';
      if (el.scopeHint) el.scopeHint.textContent = 'sing your gold line — cyan is you, gold glow = on the note (±50¢, any octave)';
      setStatus('Mic on — sing your part. Headphones avoid feedback from the other voices.');
    } catch (e) {
      setStatus('Mic unavailable: ' + e.message);
    }
  }

  async function main() {
    initControls();
    if (window.TrainingScope && el.scope) {
      TrainingScope.attach(el.scope, el.scopeReadout, el.scopeHint);
      TrainingScope.setTimeSource(() => ({
        playing,
        t: playing ? Tone.Transport.seconds : null,
      }));
    }
    try {
      await loadScore(PIECES[0].url);
      buildAudio();
    } catch (e) {
      setStatus('Startup error: ' + e.message);
      console.error(e);
    }
  }

  main();
})();
