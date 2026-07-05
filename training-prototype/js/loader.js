/* loader.js — phased score load, OSMD build, windowed rendering, coloring,
 * view/fit sizing, and piece switching. Owns osmd + the render-window state.
 */
import { el, setStatus, GOLD, DIM, VOICE_DEFS, PIECES, WINDOW_THRESHOLD, INITIAL_WINDOW, WINDOW_BUFFER, DEFAULT_STARTING_PIECE_ID } from './state.js';
import { parseMusicXML, setParsed, parsed, isMonophonic } from './model.js';
import { buildVoicePicker, buildVersePicker, buildScopeLane, resetVoiceStateForLoad, selectedVoice } from './voices.js';
import { buildAudio, stop, playState } from './transport.js';
import { applySections, updateSectionNav, prepareXmlSections, clearXmlSections } from './sections.js';

export let osmd = null;
export let osmdSteps = [];        // OSMD cursor step table (rebuilt every render)
export let windowed = false;
export let sourceMeasureCount = 0;
export let renderFromIdx = 0, renderToIdx = 0;
let printedFirst = new Map();
let printedLast = new Map();
export let lastPrinted = 1;
let extending = false;
export let viewMode = 'split';
let loadToken = 0;
let currentPieceId = null;

export { currentPieceId };

  // Yield to the browser between load phases so the status/spinner actually
  // paints: rAF waits for the next frame, the nested setTimeout lets that frame
  // paint before the next synchronous block runs.
  const nextPaint = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

  // Busy state: status spinner + a spinner overlay on the score box, plus a
  // disabled Play button. `text` (when busy) drives both the status line and the
  // score overlay label.
  function setBusy(busy, text) {
    el.status.classList.toggle('busy', !!busy);
    if (busy) {
      if (text) setStatus(text);
      if (el.scoreBusyText && text) el.scoreBusyText.textContent = text;
      if (el.scoreBusy) el.scoreBusy.hidden = false;
    } else if (el.scoreBusy) {
      el.scoreBusy.hidden = true;
    }
    if (el.play) el.play.disabled = !!busy;
    // Section jumps mid-load would race the incoming piece's parsed/osmd swap.
    if (el.sectionsBtn) el.sectionsBtn.disabled = !!busy;
    if (busy) {
      if (el.secPrev) el.secPrev.disabled = true;
      if (el.secNext) el.secNext.disabled = true;
    } else {
      updateSectionNav();
    }
  }

  /* ---------- OSMD rendering + coloring ------------------------------- */

  // Narrow screens: drop the engraved title/part names (the voice picker and
  // gold coloring carry that) and zoom OSMD out so systems fit the width.
export function isNarrow() { return el.osmd.clientWidth < 560; }

export function applyResponsiveOsmdOptions() {
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

  // Walk OSMD's cursor iterator once (after each render) and record every step
  // it will take: timestamp in quarter-note beats + printed measure number.
  // OSMD steps on EVERY voice-entry timestep — including rest-only ones our note
  // parse has no onset for — so the playback cursor must be scheduled from THIS
  // table to stay 1:1 with cursor.next(); anything less leaves the score cursor
  // progressively behind the audio on rest-heavy pieces (Cherubic: 7 such steps,
  // Anaphora: 3, Trisagion: 0).
  //
  // WINDOWED NOTE: OSMD clips the cursor iterator to [MinMeasureToDrawIndex,
  // MaxMeasureToDrawIndex] (see Cursor.resetIterator), so in windowed mode this
  // table covers only the rendered window — hence it is rebuilt on every render.
  // Enrolled timestamps stay ABSOLUTE even when the window starts mid-piece (the
  // iterator ctor fast-forwards with moveToNext, accumulating time), so beats
  // stay in the same frame as parsed.parts / measureBeatRange. The cursor is
  // HIDDEN during the walk so cursor.update() (which early-returns while hidden)
  // never touches the graphics of measures outside the rendered window.
  function buildOsmdStepTable() {
    osmdSteps = [];
    const cur = osmd && osmd.cursor;
    if (!cur) return;
    cur.hide();     // update() no-ops while hidden → walk never reads un-rendered graphics
    cur.reset();
    const it = cur.Iterator;
    let guard = 0;
    while (!it.EndReached && guard++ < 40000) {
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

  function ensureOsmd() {
    if (osmd) return;
    osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(el.osmd, {
      // autoResize OFF: we drive re-layout ourselves (debounced, one render per
      // settle) so OSMD's own resize handler can't stack extra renders on ours.
      autoResize: false,
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

  // Phased, painting load. Returns true on completion, false if a newer load
  // superseded this one (the load token changed) — the caller must then skip
  // its post-load work. Phases yield via nextPaint() so the spinner + status
  // actually paint between the heavy synchronous blocks (parse, OSMD build,
  // render). See setDrawRange/ensureRenderWindow for the windowed-render path.
  async function loadScore(url) {
    const myToken = ++loadToken;
    const mine = () => myToken === loadToken;
    clearXmlSections();             // reset; re-derived from this load's Document (sections.js)
    setBusy(true, 'Fetching score…');
    try {
      // Phase 1 — Fetching (the fetch is the only pre-existing event-loop yield)
      const xml = await (await fetch(url)).text();
      if (!mine()) return false;
      await nextPaint();

      // Phase 2 — Parsing. DOMParser ONCE: the resulting Document feeds both our
      // own note model and osmd.load(doc) below (OSMD skips its DOMParser pass
      // when handed a node instead of a string).
      setBusy(true, 'Parsing…');
      await nextPaint();
      const doc = new DOMParser().parseFromString(xml, 'application/xml');
      setParsed(parseMusicXML(doc));
      resetVoiceStateForLoad();   // activeVerse=1, melodyMuted=false (voices.js)
      // Fallback section index: scan the top part's <words> directions now while
      // the parsed Document is in hand. Used only when the manifest lacks
      // sections for this piece (see resolveSectionsFor).
      prepareXmlSections(doc);   // scan + store this load's XML sections (sections.js)
      if (!mine()) return false;

      // Phase 3 — Building score (OSMD reads the Sheet model from the Document)
      setBusy(true, 'Building score…');
      await nextPaint();
      ensureOsmd();
      await osmd.load(doc);
      if (!mine()) return false;
      // MUST come after load(): OSMD's load() resets zoom to 1, so a zoom set
      // earlier is silently lost — phones then render at full desktop scale.
      applyResponsiveOsmdOptions();

      sourceMeasureCount = osmd.Sheet.SourceMeasures.length;
      buildPrintedIndexMap();
      windowed = sourceMeasureCount > WINDOW_THRESHOLD;
      // Color the Sheet model BEFORE the first render → one render per load
      // (was two: render() then applyVoiceColors()→render() again).
      colorSheet();
      // default loop = whole piece (unchanged behavior)
      el.loopFrom.value = 1;
      el.loopTo.value = parsed.measureCount;

      // Phase 4 — Rendering (windowed first paint for large scores)
      if (windowed) {
        renderFromIdx = 0;
        renderToIdx = indexToPrinted(INITIAL_WINDOW);
        setBusy(true, `Rendering ${sourceMeasureCount} measures (windowed)…`);
        setDrawRange(renderFromIdx, renderToIdx);
      } else {
        renderFromIdx = 0;
        renderToIdx = sourceMeasureCount - 1;
        setBusy(true, `Rendering ${sourceMeasureCount} measures…`);
        setDrawRange(0, Number.MAX_VALUE);
      }
      await nextPaint();
      renderNow();                 // single render() + step table + fit
      if (!mine()) return false;
      buildVoicePicker();
      buildVersePicker();
      updateScoreMore();

      // Phase 5 — Preparing audio (non-visual work; Play was disabled until now)
      setBusy(true, 'Preparing audio…');
      await nextPaint();
      buildScopeLane();
      if (!mine()) return false;

      const nVoices = parsed.parts.length;
      const voicesLabel = `${nVoices} ${nVoices === 1 ? 'voice' : 'voices'}`;
      const loadTail = isMonophonic()
        ? 'Press Play for the melody, or mute it and sing along.'
        : 'Pick a voice and press Play.';
      setStatus(windowed
        ? `Loaded: ${voicesLabel}, ${parsed.measureCount} measures (windowed — scroll or press Play to render more). ${loadTail}`
        : `Loaded: ${voicesLabel}, ${parsed.measureCount} measures. ${loadTail}`);
      return true;
    } finally {
      // Only the active load clears the busy state; a superseded load leaves it
      // for the newer load that took over.
      if (mine()) setBusy(false);
    }
  }

  /* ---------- Windowed (lazy) rendering ------------------------------- *
   * Large scores render one measure-window at a time so first paint is fast.
   * The window is tracked as inclusive SOURCE-measure index bounds
   * [renderFromIdx, renderToIdx]; ensureRenderWindow expands/replaces it and
   * re-renders only when a requested printed range falls outside it. Beats in
   * the step table stay absolute (see buildOsmdStepTable), so audio scheduling
   * and the cursor stay correct across window changes. printedFirst/printedLast
   * map printed numbers to source indices (Finley: 422 source measures, 371
   * printed numbers — split continuations reuse the printed number).
   *
   * A follow-up "jump to section" feature drives this via window.__training:
   *   __training.seekTo(fromPrinted, toPrinted)  // renders window + sets loop
   * or the lower-level __training.ensureWindow(fromPrinted, toPrinted).
   */

  function buildPrintedIndexMap() {
    printedFirst = new Map();
    printedLast = new Map();
    lastPrinted = 1;
    const sms = (osmd.Sheet && osmd.Sheet.SourceMeasures) || [];
    sms.forEach((sm, idx) => {
      const n = (sm.MeasureNumberXML != null ? sm.MeasureNumberXML : sm.MeasureNumber) || (idx + 1);
      if (!printedFirst.has(n)) printedFirst.set(n, idx);
      printedLast.set(n, idx);
      if (n > lastPrinted) lastPrinted = n;
    });
  }

  // printed measure number -> first/last source-measure index (clamped; falls
  // back to the nearest present number, then the sheet edge).
export function indexFromPrinted(p) {
    p = Math.max(1, Math.min(Math.round(p) || 1, lastPrinted));
    for (let q = p; q >= 1; q--) if (printedFirst.has(q)) return printedFirst.get(q);
    return 0;
  }
  function indexToPrinted(p) {
    p = Math.max(1, Math.min(Math.round(p) || 1, lastPrinted));
    for (let q = p; q <= lastPrinted; q++) if (printedLast.has(q)) return printedLast.get(q);
    return sourceMeasureCount - 1;
  }
  // source-measure index -> its printed number (for the "showing through m N" UI)
export function printedForIndex(idx) {
    const sms = (osmd.Sheet && osmd.Sheet.SourceMeasures) || [];
    const sm = sms[Math.max(0, Math.min(idx, sms.length - 1))];
    return sm ? ((sm.MeasureNumberXML != null ? sm.MeasureNumberXML : sm.MeasureNumber) || idx + 1) : idx + 1;
  }

  // Set the render window on the engraving rules. Indices are 0-based SOURCE
  // measure indices, inclusive. We ZERO the *Number fields so OSMD's
  // ImplicitMeasure (pickup-bar) override in render() can't rewrite our indices
  // from them; full render restores the default Number.MAX_VALUE upper bound.
  function setDrawRange(fromIdx, toIdx) {
    const R = osmd.EngravingRules;
    const full = toIdx === Number.MAX_VALUE;
    R.MinMeasureToDrawIndex = Math.max(0, fromIdx | 0);
    R.MaxMeasureToDrawIndex = full ? Number.MAX_VALUE : Math.max(fromIdx | 0, toIdx | 0);
    R.MinMeasureToDrawNumber = 0;
    R.MaxMeasureToDrawNumber = full ? Number.MAX_VALUE : 0;
  }

  // One render + the rebuilds that depend on it. Colors already live on the
  // Sheet model, so a single render() paints them (no second coloring render).
  function renderNow() {
    osmd.render();
    buildOsmdStepTable();
    fitScoreHeight();
  }

  // A re-layout is only safe while stopped: renderNow() rebuilds the step table
  // and hides the cursor, desyncing the stepCursorTo callbacks already scheduled
  // on the Transport. Callers that can fire mid-playback (voice change, resize)
  // defer the render to the next stop().
  let renderDeferred = false;
export function requestRender() {
    if (playState === 'stopped') renderNow();
    else renderDeferred = true;
  }

  // Expand/replace the rendered window so [fromPrinted, toPrinted] is covered,
  // then re-render. No-op for small (non-windowed) scores or when already
  // covered. Grows generously so repeated small asks don't thrash: a contiguous
  // extension roughly doubles the window (keeping the top so scroll position and
  // already-read measures persist); a disjoint jump builds a fresh window around
  // the target. Returns true if it re-rendered.
export function ensureRenderWindow(fromPrinted, toPrinted) {
    if (!windowed || !osmd || !osmd.Sheet) return false;
    const wantFrom = indexFromPrinted(fromPrinted);
    const wantTo = Math.max(wantFrom, indexToPrinted(toPrinted));
    if (wantFrom >= renderFromIdx && wantTo <= renderToIdx) return false;   // covered
    const last = sourceMeasureCount - 1;
    let newFrom, newTo;
    if (wantFrom >= renderFromIdx && wantFrom <= renderToIdx + 1) {
      // contiguous extension downward — keep the current top
      newFrom = renderFromIdx;
      newTo = Math.max(wantTo, renderToIdx + (renderToIdx - renderFromIdx) + 1);
    } else {
      // disjoint jump (earlier, or far past the current window) — fresh window
      newFrom = Math.max(0, wantFrom - WINDOW_BUFFER);
      newTo = Math.max(wantTo, wantFrom + INITIAL_WINDOW);
    }
    renderFromIdx = Math.max(0, Math.min(newFrom, wantFrom));
    renderToIdx = Math.min(last, newTo);
    setBusy(true, 'Rendering more measures…');
    setDrawRange(renderFromIdx, renderToIdx);
    renderNow();
    setBusy(false);
    updateScoreMore();
    return true;
  }

  // Render the entire score (drop windowing for this piece). Used by the
  // "Render full score" action.
export function renderFullScore() {
    if (!windowed || renderToIdx >= sourceMeasureCount - 1) return;
    if (playState !== 'stopped') return;   // unsafe mid-playback (see requestRender)
    setBusy(true, `Rendering all ${sourceMeasureCount} measures…`);
    renderFromIdx = 0;
    renderToIdx = sourceMeasureCount - 1;
    setDrawRange(0, Number.MAX_VALUE);
    renderNow();
    setBusy(false);
    updateScoreMore();
  }

  // Windowed-render footer: visible only while a large score is partly rendered.
  function updateScoreMore() {
    if (!el.scoreMore) return;
    if (windowed && renderToIdx < sourceMeasureCount - 1) {
      el.scoreMore.hidden = false;
      el.scoreMore.classList.remove('working');
      if (el.scoreMoreText) {
        el.scoreMoreText.textContent = `Showing through m ${printedForIndex(renderToIdx)} of ${lastPrinted} — scroll for more`;
      }
    } else {
      el.scoreMore.hidden = true;
    }
  }

  // Lazy extension when the user scrolls to the bottom of the rendered portion.
  // Only while stopped: a re-render rebuilds the step table and hides the follow
  // cursor, so we never do it mid-playback (playback already rendered its loop
  // window up front via startPlayback → ensureRenderWindow).
export function maybeExtendOnScroll() {
    if (!windowed || extending || playState !== 'stopped') return;
    if (renderToIdx >= sourceMeasureCount - 1) return;
    const wrap = el.osmd;
    if (!wrap) return;
    if (wrap.scrollTop + wrap.clientHeight < wrap.scrollHeight - 80) return;  // not near bottom
    extending = true;
    if (el.scoreMore) {
      el.scoreMore.hidden = false;
      el.scoreMore.classList.add('working');
      if (el.scoreMoreText) el.scoreMoreText.textContent = 'Rendering more…';
    }
    // let the "Rendering more…" label paint before the synchronous render
    requestAnimationFrame(() => setTimeout(() => {
      const grow = Math.max(INITIAL_WINDOW, renderToIdx - renderFromIdx);
      renderToIdx = Math.min(sourceMeasureCount - 1, renderToIdx + grow);
      setDrawRange(renderFromIdx, renderToIdx);
      renderNow();
      updateScoreMore();
      extending = false;
    }, 0));
  }

  // Color the selected voice's noteheads gold, all others dim gray, on the
  // Sheet model. OSMD keeps these across re-renders (they live on the notes), so
  // this can run once before the first render.
  function colorSheet() {
    if (!osmd || !osmd.Sheet) return;
    osmd.Sheet.Instruments.forEach((instr, idx) => {
      const color = matchesSelected(idx, instr.Name) ? GOLD : DIM;
      instr.Voices.forEach((voice) => {
        voice.VoiceEntries.forEach((ve) => {
          ve.Notes.forEach((note) => {
            note.NoteheadColor = color;
            if ('NoteheadColorXml' in note) note.NoteheadColorXml = color;
          });
        });
      });
    });
  }

  // Re-color + re-render (single render) for a later voice change. OSMD has no
  // live notehead recolor, so a voice change re-renders the current window.
export function applyVoiceColors() {
    if (!osmd || !osmd.Sheet) return;
    colorSheet();
    requestRender();
  }

  function matchesSelected(partIndex, instrName) {
    const p = parsed.parts[partIndex];
    if (p) return p.voiceKey === selectedVoice;
    // fallback by name
    const def = VOICE_DEFS.find((v) => v.key === selectedVoice);
    return def && (instrName || '').toLowerCase().startsWith(def.name.toLowerCase());
  }

  /* ---------- View modes + adaptive score height ----------------------- */

export function setView(mode) {
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

  function setCurrentPiece(p) {
    currentPieceId = p ? p.id : null;
    if (el.currentPiece) el.currentPiece.textContent = p ? (p.title || p.label || p.id) : '—';
    // Attribution line (composer + source book). Gated on p.bookName, which
    // only manifest-derived library pieces ever carry — the 5 hard-coded
    // Prototype PIECES (incl. the control piece) never set it, so this is a
    // strict no-op (hidden, empty text) for every piece without real
    // attribution data.
    if (el.pieceAttrib) {
      const bits = (p && p.bookName) ? [p.attribComposer, p.bookName].filter(Boolean) : [];
      if (bits.length) { el.pieceAttrib.textContent = bits.join(' — '); el.pieceAttrib.hidden = false; }
      else { el.pieceAttrib.textContent = ''; el.pieceAttrib.hidden = true; }
    }
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
export async function loadPieceById(id, opts) {
    opts = opts || {};
    stop();
    const p = PIECES.find((x) => x.id === id);
    if (!p) { setStatus('Unknown piece: ' + id); return; }
    try {
      const completed = await loadScore(p.url);
      if (!completed) return;   // superseded by a newer load — skip stale post-load work
      buildAudio();
      setCurrentPiece(p);
      applySections(p);
      if (!opts.fromSelect) syncSelect(id);
    } catch (e) {
      setBusy(false);
      // Technical detail to the console; a friendly, actionable line to the singer.
      console.error(`Could not load piece "${p.id}" (${p.url}):`, e);
      setStatus(`Could not load "${p.title || p.label || p.id}". Try another piece or reload.`);
    }
  }

export function resolvePieceId(id) {
    if (PIECES.some((p) => p.id === id)) return id;
    if (PIECES.some((p) => p.id === 'ingest_' + id)) return 'ingest_' + id;
    return null;
  }

  // One landing-piece load attempt: loadScore + the same post-load wiring
  // loadPieceById does (buildAudio/setCurrentPiece/applySections). Shared by
  // loadStartingPiece's preferred-piece attempt and its control fallback.
  async function loadStartingCandidate(p) {
    const completed = await loadScore(p.url);
    if (completed) { buildAudio(); setCurrentPiece(p); applySections(p); }
    return completed;
  }

  // Initial piece load, factored out so the Retry button can re-attempt it.
  //
  // Issue #64: the default landing piece is the library's 10A Trisagion Hymn
  // (Hilko) — but ONLY when the library manifest actually loaded and lists it
  // (resolvePieceId resolves DEFAULT_STARTING_PIECE_ID against PIECES, which
  // library.loadLibraryManifest populates; main.js awaits that manifest fetch
  // before calling loadStartingPiece so this check is meaningful). Every other
  // case — most notably every CI checkout / fresh clone, which has no
  // manifest at all (it's gitignored) — falls back to the 'control' fixture
  // exactly as before this feature existed, with no extra network round-trip.
export async function loadStartingPiece() {
    if (el.retryStart) el.retryStart.hidden = true;
    const control = PIECES.find((p) => p.id === 'control') || PIECES[0];
    const preferredId = resolvePieceId(DEFAULT_STARTING_PIECE_ID);
    const primary = (preferredId && PIECES.find((p) => p.id === preferredId)) || control;
    try {
      await loadStartingCandidate(primary);
    } catch (e) {
      if (primary === control) {
        setBusy(false);
        setStatus('Could not load the starting piece — check your connection.');
        if (el.retryStart) el.retryStart.hidden = false;   // offer a retry
        console.error(e);
        return;
      }
      // The manifest listed the preferred landing piece but its MusicXML
      // didn't actually fetch (e.g. a stale/partial local ingest) — fall back
      // to the always-committed control fixture rather than stranding the
      // app on a broken retry loop for a piece CI never even guarantees.
      console.error(`Could not load preferred starting piece "${primary.id}" (${primary.url}); falling back to control:`, e);
      try {
        await loadStartingCandidate(control);
      } catch (e2) {
        setBusy(false);
        setStatus('Could not load the starting piece — check your connection.');
        if (el.retryStart) el.retryStart.hidden = false;
        console.error(e2);
      }
    }
  }

// Apply a render that was deferred because it arrived mid-playback (see requestRender).
export function flushDeferredRender() { if (renderDeferred) { renderDeferred = false; renderNow(); } }

