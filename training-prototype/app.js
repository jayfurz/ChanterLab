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

  // The 5 built-in dev pieces (the "Prototype" group). These stay reachable via
  // the hidden #pieceSelect (headless tests) AND appear in the library overlay.
  const PIECES = [
    { id: 'control', title: 'Control — clean SATB', composer: 'ChanterLab · dev', arrangement: '4-part, Full choir', label: 'Control — hand-made clean SATB', url: 'content/control_satb.musicxml' },
    { id: 'trisagion_v', title: 'Trisagion', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Trisagion (antiochian.org, vector extraction)', url: 'content/trisagion_vector.musicxml' },
    { id: 'cherubic_v', title: 'Cherubic Hymn', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Cherubic Hymn (antiochian.org, vector extraction)', url: 'content/cherubic_vector.musicxml' },
    { id: 'anaphora_v', title: 'Anaphora', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Anaphora (antiochian.org, vector extraction)', url: 'content/anaphora_vector.musicxml' },
    { id: 'trisagion', title: 'Trisagion — OMR', composer: 'antiochian.org · OMR', arrangement: 'Choral', label: 'Trisagion (oemer OMR — kept for comparison)', url: 'content/trisagion_omr.musicxml' },
  ];
  const N_BUILTIN = PIECES.length;

  /* ---------- Library data (batch-ingested pieces) --------------------- *
   * omr/ingest_catalog.py writes a manifest of pipeline-ACCEPTED extractions.
   * It can hold thousands of entries, so it is NOT poured into the combobox —
   * it feeds the full-screen library browser (windowed list) below. The
   * manifest is local-only (gitignored, derived from copyrighted PDFs); a fresh
   * clone simply shows the Prototype group + a "run the ingester" hint.
   */
  const DEFAULT_MANIFEST = 'omr/out/ingest/manifest.json';

  // Diacritic- and case-insensitive fold for search + facet matching.
  const fold = (s) => (s == null ? '' : String(s))
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

  // Prototype items (the 5 built-ins) rendered into the library too.
  const libProto = PIECES.slice(0, N_BUILTIN).map((p) => ({
    id: p.id, title: p.title, composer: p.composer, tone: null,
    arrangement: p.arrangement, liturgicalDate: '', section: 'proto',
    norm: fold([p.title, p.composer, p.arrangement].join(' ')),
  }));
  const libItems = [];   // manifest-derived items

  async function loadLibraryManifest() {
    const override = new URLSearchParams(location.search).get('manifest');
    const url = override || DEFAULT_MANIFEST;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error('no manifest');
      const items = await res.json();
      if (Array.isArray(items)) {
        items.forEach((it) => {
          const id = 'ingest_' + it.id;
          if (!PIECES.some((p) => p.id === id)) {
            PIECES.push({
              id, title: it.title,
              label: `${it.title}${it.composer ? ' — ' + it.composer : ''}`,
              url: 'omr/' + it.musicxml,
              pdfUrl: it.pdfUrl || null,
            });
          }
          libItems.push({
            id, title: it.title || '(untitled)', composer: (it.composer || '').trim(),
            tone: (it.tone != null && it.tone !== '') ? String(it.tone) : null,
            toneClean: (typeof it.toneClean === 'number') ? it.toneClean : null,
            arrangement: it.arrangementType || '', liturgicalDate: it.liturgicalDate || '',
            pdfUrl: it.pdfUrl || null,
            section: 'lib',
            // taxonomy from ingest_catalog.liturgical_group (see LIB_GROUP_ORDER)
            group: it.group || 'Other services & misc',
            sub: (it.sub != null && it.sub !== '') ? it.sub : null,
            rank: (typeof it.rank === 'number') ? it.rank : 99000,
            norm: fold([it.title, it.composer, it.liturgicalDate, it.arrangementType,
                        it.bookName, it.group, it.sub].join(' ')),
          });
        });
      }
    } catch (e) { /* no manifest (fresh clone / bad URL) — empty state is fine */ }
    buildFacets();
    if (libOpen) rebuildLib();
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
    currentPiece: document.getElementById('currentPiece'),
    pdfLink: document.getElementById('pdfLink'),
    libraryBtn: document.getElementById('libraryBtn'),
    overlay: document.getElementById('libraryOverlay'),
    libSearch: document.getElementById('libSearch'),
    libClose: document.getElementById('libClose'),
    libFacets: document.getElementById('libFacets'),
    libCount: document.getElementById('libCount'),
    libList: document.getElementById('libList'),
    libViewport: document.getElementById('libViewport'),
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

  // --- library browser state ---
  // fixed row heights (windowing math): piece row, group header, sub-header, hint
  const LIB_ROW_H = 66, LIB_GROUP_H = 46, LIB_SUB_H = 30, LIB_HINT_H = 64;
  // Canonical section order — mirrors ingest_catalog.LIB_GROUP_ORDER. Prototype
  // is pinned above these; anything unlisted falls to the tail (defensive).
  const LIB_GROUP_ORDER = [
    'Divine Liturgy', 'Presanctified Liturgy', 'Anastasimatarion',
    'Vespers', 'Orthros', 'Triodion', 'Pentecostarion',
    'Menaion', 'Theotokia', 'Other services & misc',
  ];
  // Huge groups collapsed by default (tap the header to expand; a search hit
  // inside auto-expands them).
  const LIB_COLLAPSIBLE = new Set(['Menaion', 'Theotokia']);
  const libCollapsed = new Set(['Menaion', 'Theotokia']);
  const libFacetDefs = { arrangement: [], tone: [], composer: [] };
  const libActive = { arrangement: new Set(), tone: new Set(), composer: new Set() };
  let libSearch = '';        // folded search string
  let libFlat = [];          // [{type:'group'|'sub'|'row'|'hint', ...}]
  let libOffsets = [];       // prefix pixel offset per flat index
  let libTotalH = 0;
  let libRange = [-1, -1];   // currently-rendered [start,end) window
  let libOpen = false;
  let libPushed = false;     // whether we pushed a history entry for the overlay
  let libSearchTimer = 0, libScrollRaf = 0;

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
                // first lyric syllable, with a trailing dash on begin/middle
                // syllables so the scope can show word continuation
                let lyric = null;
                const lyricEl = child.getElementsByTagName('lyric')[0];
                if (lyricEl) {
                  const txt = textOf(lyricEl, 'text');
                  if (txt) {
                    const syl = textOf(lyricEl, 'syllabic');
                    lyric = (syl === 'begin' || syl === 'middle') ? txt + '-' : txt;
                  }
                }
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
                    lyric,
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

    propagateLyrics(parts);
    return { parts, measureCount };
  }

  // Engravings often print the shared text under only one staff (or a subset)
  // while every part sings the same words. For the scope lane, borrow
  // syllables for lyric-poor parts from the best rhythm-matched lyric-bearing
  // part: copy at exactly matching onsets only, so differing rhythms
  // (melismas, part-specific figures) never get wrong text forced onto them.
  function propagateLyrics(parts) {
    const r3 = (x) => Math.round(x * 1000) / 1000;
    const lyricCount = (p) => p.notes.reduce((a, n) => a + (n.lyric ? 1 : 0), 0);
    const hasOwn = (p) => lyricCount(p) >= Math.max(3, p.notes.length * 0.2);
    const donors = parts.filter(hasOwn).map((p) => ({
      map: new Map(p.notes.filter((n) => n.lyric).map((n) => [r3(n.startBeat), n.lyric])),
    }));
    if (!donors.length) return;
    parts.forEach((p) => {
      if (hasOwn(p)) return;
      let best = null, bestHits = 0;
      donors.forEach((d) => {
        let hits = 0;
        p.notes.forEach((n) => { if (d.map.has(r3(n.startBeat))) hits++; });
        if (hits > bestHits) { bestHits = hits; best = d.map; }
      });
      if (!best) return;
      p.notes.forEach((n) => {
        if (!n.lyric) n.lyric = best.get(r3(n.startBeat)) || null;
      });
    });
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
        lyric: n.lyric || null,
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

  /* ---------- Library browser (full-screen overlay) -------------------- *
   * Windowed list: a tall spacer (#libViewport) holds the full scroll height;
   * only the rows crossing the viewport (+ a small buffer) are ever in the DOM,
   * each absolutely positioned at a precomputed offset. This keeps the DOM at a
   * few dozen rows even with thousands of pieces. Search + facet chips filter
   * the flat list; a rebuild recomputes offsets and re-windows from the top.
   */

  // Facet definitions derived from the loaded data.
  function buildFacets() {
    // arrangement: substring buckets, keep only those present, by count
    const buckets = [
      ['Choral', 'choral'], ['Chant', 'chant'], ['4-part', '4-part'],
      ['2-part', '2-part'], ['Full choir', 'full choir'],
    ];
    libFacetDefs.arrangement = buckets.map(([label, needle]) => {
      const test = (a) => a.includes(needle);
      const count = libItems.reduce((n, it) => n + (test(fold(it.arrangement)) ? 1 : 0), 0);
      return { value: label, label, test, count };
    }).filter((b) => b.count > 0).sort((a, b) => b.count - a.count);

    // tone: ONLY clean tones 1-8 (toneClean) — junk/multi-tone chips dropped.
    const toneCounts = {};
    libItems.forEach((it) => {
      if (it.toneClean) toneCounts[it.toneClean] = (toneCounts[it.toneClean] || 0) + 1;
    });
    libFacetDefs.tone = Object.keys(toneCounts).map((v) => ({
      value: v, label: 'Tone ' + v, count: toneCounts[v], num: parseInt(v, 10),
    })).sort((a, b) => a.num - b.num);

    // composer: top 8 by count
    const compCounts = {};
    libItems.forEach((it) => { if (it.composer) compCounts[it.composer] = (compCounts[it.composer] || 0) + 1; });
    libFacetDefs.composer = Object.entries(compCounts).sort((a, b) => b[1] - a[1]).slice(0, 8)
      .map(([value, count]) => ({ value, label: value, count }));

    renderChips();
  }

  function renderChips() {
    el.libFacets.innerHTML = '';
    const group = (title, defs, dim) => {
      if (!defs.length) return;
      const g = document.createElement('div'); g.className = 'facet-group';
      const lab = document.createElement('span'); lab.className = 'facet-label'; lab.textContent = title;
      g.appendChild(lab);
      const strip = document.createElement('div'); strip.className = 'facet-strip';
      defs.forEach((d) => {
        const c = document.createElement('button');
        c.className = 'chip-f' + (libActive[dim].has(d.value) ? ' on' : '');
        c.dataset.dim = dim; c.dataset.val = d.value;
        c.textContent = `${d.label} (${d.count})`;
        strip.appendChild(c);
      });
      g.appendChild(strip); el.libFacets.appendChild(g);
    };
    group('Type', libFacetDefs.arrangement, 'arrangement');
    group('Tone', libFacetDefs.tone, 'tone');
    group('Composer', libFacetDefs.composer, 'composer');
  }

  function itemPasses(it) {
    if (libSearch && !it.norm.includes(libSearch)) return false;
    if (libActive.arrangement.size) {
      const ok = [...libActive.arrangement].some((v) => {
        const b = libFacetDefs.arrangement.find((x) => x.value === v);
        return b && b.test(fold(it.arrangement));
      });
      if (!ok) return false;
    }
    if (libActive.tone.size && !libActive.tone.has(String(it.toneClean))) return false;
    if (libActive.composer.size && !libActive.composer.has(it.composer)) return false;
    return true;
  }

  const libFiltersActive = () =>
    !!libSearch || libActive.arrangement.size || libActive.tone.size || libActive.composer.size;

  const libRowH = (f) => f.type === 'group' ? LIB_GROUP_H
    : f.type === 'sub' ? LIB_SUB_H : f.type === 'hint' ? LIB_HINT_H : LIB_ROW_H;

  // Recompute the filtered, SECTIONED flat list, its offsets, the count line,
  // and re-window. Sections render in LIB_GROUP_ORDER; each group's items are
  // sorted by (rank, title) so sub-headers (tone / month / service) fall out
  // contiguously and in order. Collapsible groups render header-only unless
  // expanded; while filtering, every group with matches auto-expands so hits
  // are always visible. keepScroll leaves the scroll position alone (used when
  // toggling a group) instead of jumping back to the top.
  function rebuildLib(keepScroll) {
    const filtering = libFiltersActive();
    const proto = libProto.filter(itemPasses);
    const lib = libItems.filter(itemPasses);

    const byGroup = new Map();
    lib.forEach((it) => {
      if (!byGroup.has(it.group)) byGroup.set(it.group, []);
      byGroup.get(it.group).push(it);
    });
    // any group the manifest introduced that we don't order explicitly → tail
    const order = LIB_GROUP_ORDER.slice();
    [...byGroup.keys()].forEach((g) => { if (!order.includes(g)) order.push(g); });

    libFlat = [];
    if (proto.length) {
      libFlat.push({ type: 'group', group: 'Prototype', count: proto.length, collapsible: false, expanded: true });
      proto.forEach((it) => libFlat.push({ type: 'row', item: it }));
    }
    order.forEach((group) => {
      const items = byGroup.get(group);
      if (!items || !items.length) return;
      const collapsible = LIB_COLLAPSIBLE.has(group);
      // filtering forces open so matches show; else honor the collapse toggle
      const expanded = filtering ? true : !libCollapsed.has(group);
      libFlat.push({ type: 'group', group, count: items.length, collapsible, expanded });
      if (!expanded) return;
      items.sort((a, b) => (a.rank - b.rank) || a.title.localeCompare(b.title));
      let curSub;
      items.forEach((it) => {
        if (it.sub && it.sub !== curSub) {
          curSub = it.sub;
          libFlat.push({ type: 'sub', label: it.sub });
        }
        libFlat.push({ type: 'row', item: it });
      });
    });

    if (!libItems.length) {
      libFlat.push({ type: 'hint', label: 'No library yet — run <code>omr/ingest_catalog.py</code> to populate.' });
    } else if (!proto.length && !lib.length) {
      libFlat.push({ type: 'hint', label: 'No matches — clear the search or filter chips.' });
    }

    libOffsets = []; let off = 0;
    for (const f of libFlat) { libOffsets.push(off); off += libRowH(f); }
    libTotalH = off;
    el.libViewport.style.height = libTotalH + 'px';

    const total = libProto.length + libItems.length;
    const shown = proto.length + lib.length;
    el.libCount.textContent = `${total} piece${total === 1 ? '' : 's'} · ${shown} shown`;

    if (keepScroll) el.libList.scrollTop = Math.min(el.libList.scrollTop, Math.max(0, libTotalH - el.libList.clientHeight));
    else el.libList.scrollTop = 0;
    libRange = [-1, -1];
    renderWindow(true);
  }

  // first flat index whose top offset exceeds px (binary search)
  function firstVisibleIndex(px) {
    let lo = 0, hi = libFlat.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (libOffsets[mid] <= px) lo = mid + 1; else hi = mid; }
    return lo;
  }

  function makeFlatEl(f, top) {
    if (f.type === 'group') {
      const h = document.createElement('div');
      h.className = 'lib-group' + (f.collapsible ? ' collapsible' : '')
        + (f.collapsible && !f.expanded ? ' collapsed' : '');
      h.style.top = top + 'px'; h.style.height = LIB_GROUP_H + 'px';
      if (f.collapsible) { h.setAttribute('role', 'button'); h.tabIndex = 0; h.dataset.group = f.group; h.setAttribute('aria-expanded', String(f.expanded)); }
      const name = document.createElement('span'); name.className = 'lib-group-name'; name.textContent = f.group;
      const cnt = document.createElement('span'); cnt.className = 'lib-group-count';
      cnt.textContent = `${f.count} piece${f.count === 1 ? '' : 's'}`;
      h.appendChild(name); h.appendChild(cnt);
      if (f.collapsible) { const chev = document.createElement('span'); chev.className = 'lib-group-chev'; chev.textContent = '▸'; h.appendChild(chev); }
      return h;
    }
    if (f.type === 'sub') {
      const h = document.createElement('div'); h.className = 'lib-sub';
      h.style.top = top + 'px'; h.style.height = LIB_SUB_H + 'px'; h.textContent = f.label;
      return h;
    }
    if (f.type === 'hint') {
      const h = document.createElement('div'); h.className = 'lib-hint';
      h.style.top = top + 'px'; h.style.height = LIB_HINT_H + 'px'; h.innerHTML = f.label;
      return h;
    }
    const it = f.item;
    // div[role=button], not <button>: rows may contain a nested PDF link and
    // interactive-inside-interactive is invalid (and flaky on iOS Safari).
    const b = document.createElement('div');
    b.className = 'lib-row'; b.setAttribute('role', 'button'); b.tabIndex = 0;
    b.style.top = top + 'px'; b.style.height = LIB_ROW_H + 'px'; b.dataset.id = it.id;
    const t = document.createElement('div'); t.className = 'lib-row-title'; t.textContent = it.title;
    const m = document.createElement('div'); m.className = 'lib-row-meta';
    if (it.composer) { const c = document.createElement('span'); c.className = 'composer'; c.textContent = it.composer; m.appendChild(c); }
    if (it.tone) {
      const tb = document.createElement('span'); tb.className = 'badge tone';
      tb.textContent = /^\d+$/.test(it.tone) ? 'T' + it.tone : it.tone; m.appendChild(tb);
    }
    if (it.arrangement) { const a = document.createElement('span'); a.className = 'arr'; a.textContent = it.arrangement; m.appendChild(a); }
    b.appendChild(t); b.appendChild(m);
    if (it.pdfUrl) {
      // link to the original engraving — must not trigger row selection
      const pdf = document.createElement('a');
      pdf.className = 'lib-pdf'; pdf.href = it.pdfUrl;
      pdf.target = '_blank'; pdf.rel = 'noopener';
      pdf.title = 'Open the original sheet music (PDF)';
      pdf.textContent = '𝄞 PDF';
      b.appendChild(pdf);
    }
    return b;
  }

  function renderWindow(force) {
    const top = el.libList.scrollTop;
    const vh = el.libList.clientHeight || window.innerHeight;
    let start = firstVisibleIndex(top) - 1; if (start < 0) start = 0;
    let end = start; while (end < libFlat.length && libOffsets[end] < top + vh) end++;
    const buf = 6;
    start = Math.max(0, start - buf); end = Math.min(libFlat.length, end + buf);
    if (!force && start === libRange[0] && end === libRange[1]) return;
    libRange = [start, end];
    const frag = document.createDocumentFragment();
    for (let i = start; i < end; i++) frag.appendChild(makeFlatEl(libFlat[i], libOffsets[i]));
    el.libViewport.replaceChildren(frag);
  }

  // Expand / collapse a collapsible section (Menaion, Theotokia). No-op while
  // filtering (groups are force-expanded then). Keeps the scroll position so
  // the tapped header stays put.
  function toggleGroup(group) {
    if (!LIB_COLLAPSIBLE.has(group) || libFiltersActive()) return;
    if (libCollapsed.has(group)) libCollapsed.delete(group); else libCollapsed.add(group);
    rebuildLib(true);
  }

  function openLibrary() {
    libOpen = true;
    el.overlay.hidden = false;
    document.body.classList.add('lib-lock');
    rebuildLib();
    // avoid popping the soft keyboard over the list on touch devices
    if (!('ontouchstart' in window)) setTimeout(() => { try { el.libSearch.focus(); } catch (e) {} }, 30);
    if (window.history && history.pushState && !libPushed) { history.pushState({ libOpen: true }, ''); libPushed = true; }
  }

  function closeLibrary(fromPop) {
    if (!libOpen) return;
    libOpen = false;
    el.overlay.hidden = true;
    document.body.classList.remove('lib-lock');
    if (libPushed && !fromPop) { libPushed = false; if (history.state && history.state.libOpen) history.back(); }
    else libPushed = false;
  }

  function setCurrentPiece(p) {
    if (el.currentPiece) el.currentPiece.textContent = p ? (p.title || p.label || p.id) : '—';
    // show the original-engraving link for ingested pieces (transport bar)
    if (el.pdfLink) {
      if (p && p.pdfUrl) { el.pdfLink.href = p.pdfUrl; el.pdfLink.hidden = false; }
      else { el.pdfLink.hidden = true; el.pdfLink.removeAttribute('href'); }
    }
  }

  // Keep the hidden #pieceSelect in sync when a built-in is chosen elsewhere.
  function syncSelect(id) {
    if (el.piece && [...el.piece.options].some((o) => o.value === id)) el.piece.value = id;
  }

  // Load any piece by id through the existing stop → loadScore → buildAudio flow.
  async function loadPieceById(id, opts) {
    opts = opts || {};
    stop();
    const p = PIECES.find((x) => x.id === id);
    if (!p) { setStatus('Unknown piece: ' + id); return; }
    try {
      await loadScore(p.url);
      buildAudio();
      setCurrentPiece(p);
      if (!opts.fromSelect) syncSelect(id);
    } catch (e) {
      const hint = p.id !== 'control'
        ? ' — score is gitignored (copyrighted source); regenerate via omr/README.md.'
        : ' — ' + e.message;
      setStatus('Could not load ' + p.url + hint);
    }
  }

  function resolvePieceId(id) {
    if (PIECES.some((p) => p.id === id)) return id;
    if (PIECES.some((p) => p.id === 'ingest_' + id)) return 'ingest_' + id;
    return null;
  }

  function initLibrary() {
    el.libraryBtn.addEventListener('click', openLibrary);
    el.libClose.addEventListener('click', () => closeLibrary());
    el.overlay.addEventListener('click', (e) => { if (e.target === el.overlay) closeLibrary(); });
    el.libSearch.addEventListener('input', () => {
      clearTimeout(libSearchTimer);
      libSearchTimer = setTimeout(() => { libSearch = fold(el.libSearch.value.trim()); rebuildLib(); }, 120);
    });
    el.libFacets.addEventListener('click', (e) => {
      const c = e.target.closest('.chip-f'); if (!c) return;
      const dim = c.dataset.dim, val = c.dataset.val;
      if (libActive[dim].has(val)) libActive[dim].delete(val); else libActive[dim].add(val);
      c.classList.toggle('on');
      rebuildLib();
    });
    el.libList.addEventListener('click', (e) => {
      const grp = e.target.closest('.lib-group.collapsible');
      if (grp) { toggleGroup(grp.dataset.group); return; }
      if (e.target.closest('.lib-pdf')) return;   // PDF link: let it open, don't select
      const row = e.target.closest('.lib-row'); if (!row) return;
      loadPieceById(row.dataset.id).then(() => closeLibrary());
    });
    el.libList.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const grp = e.target.closest('.lib-group.collapsible');
      if (grp) { e.preventDefault(); toggleGroup(grp.dataset.group); return; }
      const row = e.target.closest('.lib-row'); if (!row) return;
      e.preventDefault();
      loadPieceById(row.dataset.id).then(() => closeLibrary());
    });
    el.libList.addEventListener('scroll', () => {
      if (libScrollRaf) return;
      libScrollRaf = requestAnimationFrame(() => { libScrollRaf = 0; renderWindow(false); });
    }, { passive: true });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && libOpen) closeLibrary(); });
    window.addEventListener('popstate', () => { if (libOpen) closeLibrary(true); });
  }

  /* ---------- Wire-up ------------------------------------------------- */

  function initControls() {
    PIECES.forEach((p) => {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = p.label; el.piece.appendChild(o);
    });
    // Hidden built-in selector (kept for headless tests). The library overlay
    // is the primary picker; both route through loadPieceById.
    el.piece.addEventListener('change', () => loadPieceById(el.piece.value, { fromSelect: true }));
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
      if (libOpen) renderWindow(true);
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
    initLibrary();
    loadLibraryManifest();  // async; feeds the library overlay (never the combobox)
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
      setCurrentPiece(PIECES[0]);
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

  // Programmatic library hook (headless tests). select() resolves either the
  // prefixed piece id ('ingest_<x>') or the bare manifest id ('<x>').
  window.__library = {
    open: () => openLibrary(),
    close: () => closeLibrary(),
    select: async (id) => {
      const rid = resolvePieceId(id);
      if (!rid) return null;
      await loadPieceById(rid);
      closeLibrary();
      return playState;
    },
    count: () => libProto.length + libItems.length,
    shown: () => libFlat.filter((f) => f.type === 'row').length,
    domRows: () => el.libViewport.childElementCount,
    isOpen: () => libOpen,
    // sectioned-UI introspection for the headless checks
    sections: () => libFlat.filter((f) => f.type === 'group')
      .map((f) => ({ group: f.group, count: f.count, collapsible: f.collapsible, expanded: f.expanded })),
    subs: () => libFlat.filter((f) => f.type === 'sub').map((f) => f.label),
    toggle: (group) => { toggleGroup(group); return libFlat.filter((f) => f.type === 'group' && f.group === group).map((f) => f.expanded)[0]; },
    collapsed: () => [...libCollapsed],
    toneFacets: () => libFacetDefs.tone.map((t) => t.value),
    scrollToGroup: (group) => {
      const i = libFlat.findIndex((f) => f.type === 'group' && f.group === group);
      if (i < 0) return false;
      el.libList.scrollTop = libOffsets[i];
      renderWindow(true);
      return true;
    },
  };

  main();
})();
