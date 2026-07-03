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
 * Transport lives in a FIXED bottom overlay (owner's design): while PLAYING it
 * minifies to a single always-reachable row (big Pause + position + voice
 * chip + expand handle); when PAUSED it expands to the full control set.
 * Auto-scroll etiquette: the follow cursor only ever scrolls the score
 * CONTAINER (never the page), keeps the selected voice's staff in view, and
 * suspends for ~3 s after the user touches/scrolls that container. Paused =
 * zero auto-scroll.
 *
 * Pure client-side. No build step. Libraries are vendored in ./vendor.
 */
(() => {
  'use strict';

  const GOLD = '#d4af37';
  const DIM = '#9aa0a6';

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

  // Batch-ingested library pieces (omr/ingest_catalog.py output). The manifest
  // lists pipeline-ACCEPTED extractions only; it is local-only (gitignored,
  // derived from copyrighted PDFs), so a fresh clone simply has no group.
  async function loadIngestManifest() {
    try {
      const res = await fetch('omr/out/ingest/manifest.json');
      if (!res.ok) return;
      const items = await res.json();
      if (!Array.isArray(items) || !items.length) return;
      const group = document.createElement('optgroup');
      group.label = `Ingested library (${items.length})`;
      items.forEach((it) => {
        const piece = {
          id: 'ingest_' + it.id,
          label: `${it.title}${it.composer ? ' — ' + it.composer : ''}`,
          url: 'omr/' + it.musicxml,
        };
        PIECES.push(piece);
        const o = document.createElement('option');
        o.value = piece.id;
        o.textContent = piece.label;
        group.appendChild(o);
      });
      el.piece.appendChild(group);
    } catch (e) { /* no local ingest output — fine */ }
  }

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
    hpMode: document.getElementById('hpMode'),
    micNote: document.getElementById('micNote'),
    scope: document.getElementById('scope'),
    scopeReadout: document.getElementById('scopeReadout'),
    scopeHint: document.getElementById('scopeHint'),
    transport: document.getElementById('transport'),
    expandHandle: document.getElementById('expandHandle'),
    posOut: document.getElementById('posOut'),
    voiceChip: document.getElementById('voiceChip'),
    viewPicker: document.getElementById('viewPicker'),
  };

  let osmd = null;
  let parsed = null;         // { parts: [ {voiceKey, notes:[{midi,startBeat,durBeat,measure}]} ], measureCount }
  let selectedVoice = 'S';
  let synths = [];           // Tone.PolySynth per part
  let gains = [];            // Tone.Gain per part
  let scheduledIds = [];
  let osmdSteps = [];        // OSMD's cursor step table: one {beat, measure} per cursor.next()
  let cursorWindow = [];     // absolute osmdSteps indices inside the current loop window
  let playState = 'stopped'; // 'stopped' | 'playing' | 'paused'
  let viewMode = 'split';    // 'split' | 'score' | 'scope'
  let userHoldUntil = 0;     // auto-scroll suspended until this perf.now() ms

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
      let lastNoteOnset = null; // notated onset of the last pitched note (chord followers share it)
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
            const onset = isChord ? (lastNoteOnset !== null ? lastNoteOnset : beatCursor) : beatCursor;

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
                const midi = midiOf(step, octave, alter);
                // <tie type="stop"> = continuation of a held note: extend the
                // note it continues instead of re-attacking it in playback
                // (and double-drawing it in the scope lane).
                const isTieStop = Array.from(child.getElementsByTagName('tie'))
                  .some((t) => t.getAttribute('type') === 'stop');
                let merged = false;
                if (isTieStop) {
                  for (let k = notes.length - 1; k >= 0 && k >= notes.length - 8; k--) {
                    const prev = notes[k];
                    if (prev.midi === midi && Math.abs(prev.startBeat + prev.durBeat - onset) < 1e-6) {
                      prev.durBeat += durBeat;
                      merged = true;
                      break;
                    }
                  }
                }
                if (!merged) {
                  notes.push({
                    midi,
                    startBeat: onset,
                    durBeat,
                    measure: measureNumber,
                  });
                }
                lastNoteOnset = onset;
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

  // Walk OSMD's cursor iterator once (after load+render) and record every
  // step it will take: timestamp in quarter-note beats + printed measure
  // number. OSMD steps on EVERY voice-entry timestep — including rest-only
  // ones our note parse has no onset for — so the playback cursor must be
  // scheduled from THIS table to stay 1:1 with cursor.next(); anything less
  // leaves the score cursor progressively behind the audio on rest-heavy
  // pieces (Cherubic: 7 such steps, Anaphora: 3, Trisagion: 0).
  function buildOsmdStepTable() {
    osmdSteps = [];
    const cur = osmd && osmd.cursor;
    if (!cur) return;
    cur.reset();
    const it = cur.Iterator;
    let guard = 0;
    while (!it.EndReached && guard++ < 20000) {
      const ts = it.CurrentEnrolledTimestamp || it.currentTimeStamp;
      const sm = osmd.Sheet && osmd.Sheet.SourceMeasures
        ? osmd.Sheet.SourceMeasures[it.CurrentMeasureIndex] : null;
      osmdSteps.push({
        beat: ts.RealValue * 4, // OSMD timestamps are in whole notes; we count quarters
        measure: (sm && (sm.MeasureNumberXML || sm.MeasureNumber)) || (it.CurrentMeasureIndex + 1),
      });
      cur.next();
    }
    cur.reset();
    cur.hide();
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
        // We do our own container-scoped following — OSMD's followCursor
        // scrolls the PAGE, which made Pause unreachable on mobile.
        followCursor: false,
        newSystemFromXML: true,   // honor the engraving's line breaks from the extractor
        drawMeasureNumbers: false, // OSMD ordinals diverge from printed numbers at split measures
        cursorsOptions: [{ type: 0, color: GOLD, alpha: 0.4, follow: false }],
      });
    }
    await osmd.load(xml);
    // MUST come after load(): OSMD's load() resets zoom to 1, so a zoom set
    // earlier is silently lost — phones then render at full desktop scale.
    applyResponsiveOsmdOptions();
    osmd.render();
    buildOsmdStepTable();
    buildVoicePicker();
    applyVoiceColors();
    // default loop = whole piece
    el.loopFrom.value = 1;
    el.loopTo.value = parsed.measureCount;
    buildScopeLane();
    fitScoreHeight();
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
    fitScoreHeight();
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
    updateVoiceChip();
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

  function updateVoiceChip() {
    const def = VOICE_DEFS.find((v) => v.key === selectedVoice);
    el.voiceChip.textContent = def ? `${def.label} · ${def.name}` : selectedVoice;
  }

  /* ---------- View modes + adaptive score height ----------------------- */

  function setView(mode) {
    viewMode = mode;
    document.body.classList.remove('view-split', 'view-score', 'view-scope');
    document.body.classList.add('view-' + mode);
    [...el.viewPicker.children].forEach((b) =>
      b.classList.toggle('active', b.dataset.view === mode));
    fitScoreHeight();
  }

  // Height in px of the first rendered music system (one line of all staves).
  function firstSystemHeightPx() {
    try {
      const sys = osmd.GraphicSheet.MusicPages[0].MusicSystems[0];
      return sys.PositionAndShape.Size.height * 10 * osmd.zoom;
    } catch (e) {
      // fallback: total svg height / number of systems
      try {
        const svg = el.osmd.querySelector('svg');
        const nSys = osmd.GraphicSheet.MusicPages
          .reduce((a, p) => a + p.MusicSystems.length, 0) || 1;
        return svg.getBoundingClientRect().height / nSys;
      } catch (e2) { return null; }
    }
  }

  // Adapt the score container to the rendered system height when feasible:
  // grow past the view-mode budget (up to a hard cap) so a full 4-part system
  // — Tenor and Bass included — is visible without scrolling. Internal scroll
  // (with active-voice priority) remains the fallback for taller renders.
  function fitScoreHeight() {
    if (!osmd || !el.osmd) return;
    const svg = el.osmd.querySelector('svg');
    if (!svg) return;
    const vh = window.innerHeight / 100;
    const budget = { split: 44 * vh, score: 66 * vh, scope: 32 * vh }[viewMode];
    const hardCap = (viewMode === 'scope' ? 44 : 72) * vh;
    const svgH = svg.getBoundingClientRect().height + 14; // + container padding
    let h = Math.min(svgH, budget);
    const sysH = firstSystemHeightPx();
    if (sysH) {
      const wantSystem = Math.min(sysH + 26, hardCap);   // one full system + slack
      if (wantSystem > h) h = Math.min(svgH, wantSystem);
    }
    el.osmd.style.maxHeight = Math.max(120, Math.round(h)) + 'px';
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
  // NOTE: this is the ONLY place backing-voice gain changes, and it depends
  // solely on voice selection — never on mic input/level (see Headphones mode
  // in scope.js for the OS-level ducking story).
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
      const id = Tone.Transport.schedule(() => resetCursor(), total - 1e-3);
      scheduledIds.push(id);
    } else {
      Tone.Transport.loop = false;
      const id = Tone.Transport.schedule(() => stop(), total + 0.3);
      scheduledIds.push(id);
    }
  }

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
    scrollCursorIntoView();
  }
  let cursorStep = 0;
  function stepCursorTo(i) {
    if (!osmd.cursor) return;
    if (i < cursorStep) {
      // loop wrapped without an explicit reset — rewind and re-advance
      osmd.cursor.reset(); osmd.cursor.show(); cursorStep = 0;
    }
    while (cursorStep < i) { osmd.cursor.next(); cursorStep++; }
    updatePos(osmdSteps[i] ? osmdSteps[i].measure : null);
    scrollCursorIntoView();
  }

  function updatePos(measure) {
    if (!el.posOut) return;
    el.posOut.textContent = measure
      ? `m ${measure}/${parsed ? parsed.measureCount : '?'}`
      : 'm –';
  }

  // Keep the follow cursor visible inside the scrollable score container.
  // Etiquette (owner's design):
  //   - only ever scrolls the score CONTAINER — never the page,
  //   - only while PLAYING (paused/stopped = page + score fully free),
  //   - suspends ~3 s after any user touch/scroll on the container,
  //   - vertically prioritizes the SELECTED voice's staff (the cursor element
  //     spans the whole system, so the active staff sits at a fractional
  //     height within it — S top … B bottom).
  function scrollCursorIntoView() {
    if (playState !== 'playing') return;
    if (performance.now() < userHoldUntil) return;
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

  function noteUserTouch() { userHoldUntil = performance.now() + 3000; }

  /* ---------- Transport ----------------------------------------------- */

  async function playPause() {
    if (playState === 'playing') { pause(); return; }
    if (playState === 'paused') { await resume(); return; }
    await startPlayback();
  }

  async function startPlayback() {
    await Tone.start();
    if (!synths.length) buildAudio();
    applyMix();
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    buildScopeLane();
    scheduleAll();
    playState = 'playing';
    resetCursor();
    Tone.Transport.start('+0.1');
    updatePlayUI();
    setOverlay(false);
    setStatus(`Playing — ${VOICE_DEFS.find((v) => v.key === selectedVoice)?.name} muted (sing it). Follow the gold cursor.`);
  }

  function pause() {
    Tone.Transport.pause();
    playState = 'paused';
    updatePlayUI();
    setOverlay(true);
    setStatus('Paused — scroll freely. ▶ resumes where you left off.');
  }

  async function resume() {
    await Tone.start();
    playState = 'playing';
    Tone.Transport.start();
    updatePlayUI();
    setOverlay(false);
    setStatus(`Playing — ${VOICE_DEFS.find((v) => v.key === selectedVoice)?.name} muted (sing it).`);
  }

  function stop() {
    Tone.Transport.stop();
    Tone.Transport.position = 0;
    clearSchedule();
    if (osmd && osmd.cursor) osmd.cursor.hide();
    playState = 'stopped';
    updatePos(null);
    updatePlayUI();
    setOverlay(true);
    setStatus('Stopped.');
  }

  function updatePlayUI() {
    el.play.textContent =
      playState === 'playing' ? '⏸ Pause' :
      playState === 'paused' ? '▶ Resume' : '▶ Play';
  }

  /* ---------- Transport overlay (fixed bottom sheet) -------------------- */

  function setOverlay(expanded) {
    el.transport.classList.toggle('collapsed', !expanded);
    el.expandHandle.setAttribute('aria-expanded', String(expanded));
  }

  function initOverlay() {
    el.expandHandle.addEventListener('click', () =>
      setOverlay(el.transport.classList.contains('collapsed')));
    el.voiceChip.addEventListener('click', () => setOverlay(true));
    // Reserve page bottom padding = live overlay height, so the overlay never
    // covers the singscope's now-line (or any content) at full page scroll.
    const sync = () => document.documentElement.style.setProperty(
      '--transport-h', el.transport.offsetHeight + 'px');
    new ResizeObserver(sync).observe(el.transport);
    sync();
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
      if (playState === 'playing') { stop(); startPlayback(); }
      else if (playState === 'paused') stop();
    });
    el.play.addEventListener('click', playPause);
    el.stop.addEventListener('click', stop);
    el.hearMine.addEventListener('change', applyMix);
    el.loopOn.addEventListener('change', () => {
      if (playState !== 'stopped') { stop(); startPlayback(); }
    });
    el.loopFrom.addEventListener('change', buildScopeLane);
    el.loopTo.addEventListener('change', buildScopeLane);
    el.micBtn.addEventListener('click', toggleMic);
    el.hpMode.addEventListener('change', onHeadphonesToggle);
    [...el.viewPicker.children].forEach((b) =>
      b.addEventListener('click', () => setView(b.dataset.view)));

    // auto-scroll etiquette: user touch on the score container suspends
    // cursor-follow for ~3 s (each event refreshes the window)
    ['touchstart', 'touchmove', 'pointerdown', 'wheel'].forEach((ev) =>
      el.osmd.addEventListener(ev, noteUserTouch, { passive: true }));

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
      fitScoreHeight();
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
      // Headphones mode ON (default) = raw mic: echoCancellation OFF so the
      // phone can't duck the backing voices while you sing.
      await TrainingScope.setMicProcessing(!el.hpMode.checked);
      await TrainingScope.micStart(Tone.getContext().rawContext);
      el.micBtn.classList.add('on');
      el.micBtn.textContent = '🎤 On';
      if (el.scopeHint) el.scopeHint.textContent = 'sing your gold line — cyan is you, gold glow = on the note (±50¢, any octave)';
      setStatus('Mic on — sing your part. Headphones avoid feedback from the other voices.');
    } catch (e) {
      setStatus('Mic unavailable: ' + e.message);
    }
  }

  async function onHeadphonesToggle() {
    const hp = el.hpMode.checked;
    el.micNote.textContent = hp
      ? '🎧 raw mic: backing voices stay at constant volume while you sing.'
      : '🔊 speaker mode: echo cancellation on — the phone may duck the backing voices while you sing.';
    try {
      await TrainingScope.setMicProcessing(!hp);   // re-acquires the mic if it is live
      if (TrainingScope.isMicOn()) {
        setStatus(hp
          ? 'Headphones mode: raw mic — backing voices stay at constant volume.'
          : 'Speaker mode: echo cancellation on — ducking may occur while you sing.');
      }
    } catch (e) {
      setStatus('Mic switch failed: ' + e.message);
    }
  }

  async function main() {
    initControls();
    loadIngestManifest();   // async, appends an optgroup when local ingest output exists
    initOverlay();
    setView('split');
    updatePlayUI();
    setOverlay(true);
    if (window.TrainingScope && el.scope) {
      TrainingScope.attach(el.scope, el.scopeReadout, el.scopeHint);
      TrainingScope.setTimeSource(() => ({
        playing: playState === 'playing',
        // keep the lane frozen in place while paused (t survives the pause)
        t: playState === 'stopped' ? null : Tone.Transport.seconds,
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

  // Tiny debug/verification hook (used by the headless checks; harmless in prod).
  window.__training = {
    gains: () => gains.map((g) => g.gain.value),
    playState: () => playState,
    holdRemaining: () => Math.max(0, userHoldUntil - performance.now()),
    viewMode: () => viewMode,
    cursorStep: () => cursorStep,
    osmdSteps: () => osmdSteps.map((s) => ({ beat: s.beat, measure: s.measure })),
    parsedNoteCounts: () => (parsed ? parsed.parts.map((p) => p.notes.length) : []),
    zoom: () => (osmd ? osmd.zoom : null),
  };

  main();
})();
