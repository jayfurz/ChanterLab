/* state.js — shared foundation (leaf module; imports nothing from the app).
 * Holds the DOM element map (el), the status setter, and app-wide constants.
 *
 * SHARED MUTABLE-STATE OWNERSHIP (one writer per field; everyone else imports
 * it read-only via ESM live bindings). Edit a field only in its owner module:
 *   model.js     : parsed
 *   loader.js    : osmd, osmdSteps, windowed, sourceMeasureCount,
 *                  renderFromIdx, renderToIdx, printedFirst/Last, lastPrinted,
 *                  extending, renderDeferred, viewMode, loadToken, currentPieceId
 *   transport.js : synths, gains, scheduledIds, cursorWindow, cursorStep,
 *                  playState, userHoldUntil
 *   voices.js    : selectedVoice, activeVerse, melodyMuted
 *   scoring-ui.js: practiceSamples, scoringArmed, lastScoreResult, sessionLaps,
 *                  currentLapNum, bestLapHitPct, scoreSummaryShown,
 *                  reportDismissed, scoringStrictness
 *   sections.js  : currentSections, activeSectionIdx, xmlScannedSections,
 *                  sectionSheetOpen
 *   library.js   : libProto, libItems, libSearch, libFlat, libOffsets, libTotalH,
 *                  libRange, libOpen, libPushed, libCollapsed, libFacetDefs, ...
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

  // The 5 built-in dev pieces (the "Prototype" group). These stay reachable via
  // the hidden #pieceSelect (headless tests) AND appear in the library overlay.
export const PIECES = [
    { id: 'control', title: 'Control — clean SATB', composer: 'ChanterLab · dev', arrangement: '4-part, Full choir', label: 'Control — hand-made clean SATB', url: 'content/control_satb.musicxml' },
    { id: 'trisagion_v', title: 'Trisagion', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Trisagion (antiochian.org, vector extraction)', url: 'content/trisagion_vector.musicxml' },
    { id: 'cherubic_v', title: 'Cherubic Hymn', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Cherubic Hymn (antiochian.org, vector extraction)', url: 'content/cherubic_vector.musicxml' },
    { id: 'anaphora_v', title: 'Anaphora', composer: 'antiochian.org · vector', arrangement: 'Choral', label: 'Anaphora (antiochian.org, vector extraction)', url: 'content/anaphora_vector.musicxml' },
    { id: 'trisagion', title: 'Trisagion — OMR', composer: 'antiochian.org · OMR', arrangement: 'Choral', label: 'Trisagion (oemer OMR — kept for comparison)', url: 'content/trisagion_omr.musicxml' },
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

  // Diacritic- and case-insensitive fold for search + facet matching.
export const fold = (s) => (s == null ? '' : String(s))
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

export const PRACTICE_HISTORY_KEY = 'chanterlab_practice_history';
export const STRICTNESS_KEY = 'chanterlab_scoring_strictness';

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
    micNote: document.getElementById('micNote'),
    strictnessPicker: document.getElementById('strictnessPicker'),
    scope: document.getElementById('scope'),
    scopeReadout: document.getElementById('scopeReadout'),
    scopeHint: document.getElementById('scopeHint'),
    transport: document.getElementById('transport'),
    expandHandle: document.getElementById('expandHandle'),
    posOut: document.getElementById('posOut'),
    voiceChip: document.getElementById('voiceChip'),
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
  };

export const setStatus = (m) => { el.status.textContent = m; };

