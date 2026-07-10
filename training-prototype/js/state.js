/* state.js — shared foundation (leaf module; imports nothing from the app).
 * Holds the DOM element map (el), the status setter, and app-wide constants.
 *
 * SHARED MUTABLE-STATE OWNERSHIP (one writer per field; everyone else imports
 * it read-only via ESM live bindings). Edit a field only in its owner module:
 *   model.js     : parsed
 *   loader.js    : osmd, osmdSteps, windowed, sourceMeasureCount,
 *                  renderFromIdx, renderToIdx, printedFirst/Last, lastPrinted,
 *                  extending, renderDeferred, viewMode, loadToken, currentPieceId
 *   transport.js : synths, gains, master, scheduledIds, cursorWindow, cursorStep,
 *                  playState, userHoldUntil, lastFollowScroll, instrumentMode,
 *                  voiceBuffers, voiceLoadPromise, voiceLoadFailed, masterVolume,
 *                  volumeLevel (issue #74 F5 — master accompaniment volume)
 *   voices.js    : selectedVoice, activeVerse, melodyMuted
 *   scoring-ui.js: practiceSamples, scoringArmed, lastScoreResult, sessionLaps,
 *                  currentLapNum, bestLapHitPct, scoreSummaryShown,
 *                  reportDismissed, scoringStrictness
 *   sections.js  : currentSections, activeSectionIdx, xmlScannedSections,
 *                  sectionSheetOpen
 *   library.js   : libProto, libItems, libSearch, libFlat, libOffsets, libTotalH,
 *                  libRange, libOpen, libPushed, libCollapsed, libFacetDefs, ...
 *   tour.js      : active, idx, steps, device (all private)
 *   main.js      : resizeTimer, loopRenderTimer (private)
 * Cross-module resets go through the owner's exported helpers (resetVoiceState-
 * ForLoad, beginScoringSession, flushDeferredRender, prepare/clearXmlSections).
 */

export const GOLD = '#d4af37';
export const DIM = '#9aa0a6';

  // Windowed (lazy) rendering thresholds. Pieces with more SOURCE measures than
  // WINDOW_THRESHOLD render only a window at a time so first paint stays fast;
  // smaller pieces take the simple full-render path. INITIAL_WINDOW is the
  // printed-measure span rendered on first paint / grown per lazy extension;
  // WINDOW_BUFFER is the measure slack added around a jump target.
export const WINDOW_THRESHOLD = 200;
export const INITIAL_WINDOW = 100;
export const WINDOW_BUFFER = 12;

  // Canonical SATB order + labels; matched to parts by index and by name.
export const VOICE_DEFS = [
    { key: 'S', label: 'S', name: 'Soprano' },
    { key: 'A', label: 'A', name: 'Alto' },
    { key: 'T', label: 'T', name: 'Tenor' },
    { key: 'B', label: 'B', name: 'Bass' },
  ];

  // The built-in dev pieces (the "Prototype" group). These stay reachable via
  // the hidden #pieceSelect (headless tests) AND appear in the library overlay.
  // 'control' is listed LAST on purpose (issue #64): libProto (library.js)
  // mirrors this array's order verbatim for the Prototype group, and the
  // control fixture is a hand-made CI/dev regression sample, not a real chant
  // — it shouldn't be the first thing a visitor sees ahead of actual pieces.
export const PIECES = [
    { id: 'trisagion_v', title: 'Trisagion', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Trisagion (antiochian.org, vector extraction)', url: 'content/trisagion_vector.musicxml' },
    { id: 'cherubic_v', title: 'Cherubic Hymn', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Cherubic Hymn (antiochian.org, vector extraction)', url: 'content/cherubic_vector.musicxml' },
    { id: 'anaphora_v', title: 'Anaphora', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Anaphora (antiochian.org, vector extraction)', url: 'content/anaphora_vector.musicxml' },
    { id: 'trisagion', title: 'Trisagion — OMR', composer: 'antiochian.org · OMR', arrangement: 'Choral', label: 'Trisagion (oemer OMR — kept for comparison)', url: 'content/trisagion_omr.musicxml' },
    // Hand-made regression fixture (NOT a real chant): its ending is musically
    // truncated — it skips "have mercy on" — so it is not for practice, only
    // for scoring/CI smoke checks that need a small, always-committed score.
    // See loader.loadStartingPiece for why it's still the guaranteed fallback
    // when the library manifest (gitignored) isn't present, e.g. every CI
    // checkout / fresh clone.
    { id: 'control', title: 'Test fixture — SATB control', composer: 'ChanterLab · dev', arrangement: '4-part, Full choir', label: 'Test fixture — SATB control (hand-made, CI/dev only)', url: 'content/control_satb.musicxml' },
    // Second hand-made, always-committed fixture (BASE-02): distinct key/melody
    // from 'control' so CI can prove a REAL cross-piece switch on every fresh
    // checkout, not just a reselect-the-same-piece fallback.
    { id: 'control2', title: 'Test fixture — SATB control II', composer: 'ChanterLab · dev', arrangement: '4-part, Full choir', label: 'Test fixture — SATB control II (hand-made, CI/dev only)', url: 'content/control_unison_ii.musicxml' },
  ];
export const N_BUILTIN = PIECES.length;

  /* ---------- Library data (batch-ingested pieces) --------------------- *
   * omr/ingest_catalog.py writes a manifest of pipeline-ACCEPTED extractions.
   * It can hold thousands of entries, so it is NOT poured into the combobox —
   * it feeds the full-screen library browser (windowed list) below. The
   * manifest is local-only (gitignored, derived from copyrighted PDFs); a fresh
   * clone simply shows the Prototype group + a "run the ingester" hint.
   */
export const DEFAULT_MANIFEST = 'omr/out/ingest/manifest.json';

  // Preferred landing piece for first paint (issue #64) — a real chant from
  // the ingested library rather than the 'control' dev fixture above.
  // loader.loadStartingPiece uses this ONLY when the manifest actually loaded
  // and lists this id (see loadLibraryManifest, library.js); every other case
  // — most notably every CI checkout / fresh clone, which has no manifest at
  // all — falls back to 'control' exactly as before this feature existed.
  // 10B (not 10A): the owner prefers the 4-language Hilko setting, which
  // starts in English — 10A starts in a different language first. Exact id
  // as it appears in the manifest (mixed case) — 90.6% integrity.
export const DEFAULT_STARTING_PIECE_ID = '10B_Trisagion_Hymn-Hilko-T3-4Lang';

  // Diacritic- and case-insensitive fold for search + facet matching.
export const fold = (s) => (s == null ? '' : String(s))
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

export const PRACTICE_HISTORY_KEY = 'chanterlab_practice_history';
export const STRICTNESS_KEY = 'chanterlab_scoring_strictness';
  // Interactive guided tour (tour.js) — set once the visitor finishes OR skips
  // the walkthrough, so first-run auto-start fires at most once per browser.
  // (Replaced the old 'chanterlab_onboarded' coach-mark flag, issue #64.)
export const TOUR_SEEN_KEY = 'chanterlab_tour_seen';
export const INSTRUMENT_KEY = 'chanterlab_instrument';
  // Master accompaniment volume (issue #74 follow-up, fix F5): 0..1.25, applied
  // to a Tone.Gain sitting between the per-part gains and the limiter — see
  // transport.js buildAudio(). This is the sanctioned answer to iOS's
  // un-zeroable call-volume floor (docs/design/IOS-AUDIO-SESSION-ANALYSIS.md).
export const VOLUME_KEY = 'chanterlab_volume';
  // In-app practice recording (issue #67): the Voice/Music balance of the
  // RECORDING mix (0..1), and a one-time "headphones give the cleanest
  // recording" hint flag. Both persisted; the balance never touches playback.
export const REC_BALANCE_KEY = 'chanterlab_rec_balance';
export const REC_HINT_KEY = 'chanterlab_rec_hint_seen';

export const el = {
    osmd: document.getElementById('osmd'),
    status: document.getElementById('status'),
    retryStart: document.getElementById('retryStart'),
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
    // in-app practice recording (issue #67)
    recBtn: document.getElementById('recBtn'),
    recTime: document.getElementById('recTime'),
    recSave: document.getElementById('recSave'),
    recBalRow: document.getElementById('recBalRow'),
    recBalance: document.getElementById('recBalance'),
    recHint: document.getElementById('recHint'),
    strictnessPicker: document.getElementById('strictnessPicker'),
    instrumentPicker: document.getElementById('instrumentPicker'),
    // Master accompaniment volume (issue #74 F5) — one slider row in #paneSound.
    volume: document.getElementById('volume'),
    volumeOut: document.getElementById('volumeOut'),
    // Timing calibration (#paneSound): Playback sync (L_out) + Voice response
    // (L_in) sliders and the 🎯 wizard button.
    scopeSync: document.getElementById('scopeSync'),
    scopeSyncOut: document.getElementById('scopeSyncOut'),
    responseLag: document.getElementById('responseLag'),
    responseOut: document.getElementById('responseOut'),
    calibrateBtn: document.getElementById('calibrateBtn'),
    scope: document.getElementById('scope'),
    scopeReadout: document.getElementById('scopeReadout'),
    scopeHint: document.getElementById('scopeHint'),
    transport: document.getElementById('transport'),
    handleRow: document.getElementById('handleRow'),
    expandHandle: document.getElementById('expandHandle'),
    posOut: document.getElementById('posOut'),
    voiceChip: document.getElementById('voiceChip'),
    // Calm Surface (issue #73): mini-row § shortcut + the three tabbed panes
    // inside the expandable transport (Practice / Sound / More).
    sectionsMini: document.getElementById('sectionsMini'),
    paneStrip: document.getElementById('paneStrip'),
    panePractice: document.getElementById('panePractice'),
    paneSound: document.getElementById('paneSound'),
    paneMore: document.getElementById('paneMore'),
    viewPicker: document.getElementById('viewPicker'),
    verseRow: document.getElementById('verseRow'),
    versePicker: document.getElementById('versePicker'),
    currentPiece: document.getElementById('currentPiece'),
    pieceAttrib: document.getElementById('pieceAttrib'),
    pdfLink: document.getElementById('pdfLink'),
    libraryBtn: document.getElementById('libraryBtn'),
    overlay: document.getElementById('libraryOverlay'),
    libSearch: document.getElementById('libSearch'),
    libClose: document.getElementById('libClose'),
    libFacets: document.getElementById('libFacets'),
    libCount: document.getElementById('libCount'),
    libList: document.getElementById('libList'),
    libViewport: document.getElementById('libViewport'),
    scoreBusy: document.getElementById('scoreBusy'),
    scoreBusyText: document.getElementById('scoreBusyText'),
    scoreMore: document.getElementById('scoreMore'),
    scoreMoreText: document.getElementById('scoreMoreText'),
    renderFull: document.getElementById('renderFull'),
    // lightweight post-lap report strip (issue #55)
    scoreReport: document.getElementById('scoreReport'),
    scoreReportTotals: document.getElementById('scoreReportTotals'),
    scoreReportSpots: document.getElementById('scoreReportSpots'),
    scoreReportClose: document.getElementById('scoreReportClose'),
    // jump-to-section controls
    sectionsRow: document.getElementById('sectionsRow'),
    sectionsBtn: document.getElementById('sectionsBtn'),
    sectionsLabel: document.getElementById('sectionsLabel'),
    secPrev: document.getElementById('secPrev'),
    secNext: document.getElementById('secNext'),
    sectionSheet: document.getElementById('sectionSheet'),
    sectionSheetList: document.getElementById('sectionSheetList'),
    sectionSheetClose: document.getElementById('sectionSheetClose'),
    // timing calibration wizard (js/calibrate.js)
    calibrateOverlay: document.getElementById('calibrateOverlay'),
    calibTitle: document.getElementById('calibTitle'),
    calibBody: document.getElementById('calibBody'),
    calibActions: document.getElementById('calibActions'),
    calibClose: document.getElementById('calibClose'),
  };

export const setStatus = (m) => { el.status.textContent = m; };

