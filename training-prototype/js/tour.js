/* tour.js — interactive guided tour (supersedes the issue #64 coach-marks).
 *
 * A device-aware, replayable walkthrough: a spotlight rings each REAL control
 * while a card explains it, with Skip / Back / Next. Mobile and desktop get
 * different step lists and copy — taps vs. clicks + keyboard shortcuts, and the
 * collapsed ⌄ bottom-sheet transport (mobile) vs. the always-open right rail
 * (desktop, where all three panes stack visibly and #expandHandle is hidden).
 *
 * Entry points:
 *   - first visit (auto)         — maybeAutoStartTour(), unless already seen or
 *                                  a WebDriver/headless browser (so the CI smoke
 *                                  test is never driven into an open overlay)
 *   - the header "?" menu        — "Take the tour"
 *   - ?tour=1 in the URL         — forces it even for returning visitors
 *                                  (tutorial.html's "Start the tour" links here)
 * A "seen" flag (TOUR_SEEN_KEY) is written on finish OR skip so it auto-runs
 * only once per browser.
 *
 * CLICK-THROUGH BY DESIGN: the whole overlay is pointer-events:none EXCEPT the
 * card, so (a) the highlighted control stays directly usable — "tap Play now"
 * actually works — and (b) automated clicks (the smoke test's page.click) are
 * never blocked even if the overlay were up. The spotlight is one transparent
 * box whose huge box-shadow dims everything else (the classic coach-mark hole).
 *
 * Owns: active, idx, steps, device (all private below). Depends only on
 * transport.setOverlay (expand) + the existing pane-tab buttons / el map — it
 * drives the same controls a user would, never a module's internals.
 */
import { el, TOUR_SEEN_KEY } from './state.js';
import { setOverlay } from './transport.js';

let active = false;
let idx = 0;
let steps = [];
let device = 'desktop';          // 're-evaluated at every start()
let settleTimer = 0;             // re-measure after the transport expand animates

// DOM refs (bound in initTour from the static markup in index.html)
let tourEl, spotEl, cardEl, stepEl, titleEl, bodyEl, skipBtn, backBtn, nextBtn;
let helpBtn, helpMenu, helpTour;
let menuOpen = false;

const isMobile = () => !!(window.matchMedia && window.matchMedia('(max-width:759px)').matches);

function seen() {
  try { return localStorage.getItem(TOUR_SEEN_KEY) === '1'; } catch (e) { return false; }
}
function writeSeen() {
  try { localStorage.setItem(TOUR_SEEN_KEY, '1'); } catch (e) { /* private mode — non-fatal */ }
}

/* ---------- reveal helpers (make a step's target visible first) ---------- *
 * On MOBILE the transport is a collapsed bottom sheet with one active pane, so
 * a pane target must be un-collapsed + its tab activated. On DESKTOP every pane
 * is already visible in the rail (#paneStrip is display:none), so there is
 * nothing to switch — position() just scrolls the rail to it. */
function revealPane(name) {
  return () => {
    if (device !== 'mobile') return;
    setOverlay(true);
    const tab = el.paneStrip && el.paneStrip.querySelector(`[data-pane="${name}"]`);
    if (tab) tab.click();
  };
}
function collapseTransport() { if (device === 'mobile') setOverlay(false); }

/* ---------- step specs ---------------------------------------------------- *
 * body: a string, or { mobile, desktop } for device-specific wording.
 * only:  'mobile' | 'desktop' restricts a step to one device (the ⌄ step is
 *        mobile-only — the desktop rail has no collapse). */
const STEPS = [
  {
    id: 'welcome', target: null,
    title: 'Welcome to ChanterLab',
    body: 'The choir sings every part but yours — you sing along and get scored. Here’s the quick tour.',
  },
  {
    id: 'scope', target: () => document.getElementById('scopeWrap'),
    title: 'The singscope',
    body: 'With your mic on, your pitch draws across here in cyan — and turns gold the moment you land on the right note.',
  },
  {
    id: 'score', target: () => document.getElementById('scoreArea'),
    title: 'Your music',
    body: 'The sheet music scrolls and a cursor keeps your place. You follow your own voice’s line.',
  },
  {
    id: 'play', target: () => el.play,
    title: 'Play',
    body: {
      mobile: 'Tap ▶ Play to hear the choir. Tap again to pause; ■ stops and rewinds.',
      desktop: 'Click ▶ Play — or press the Space bar — to hear the choir. Space again pauses; ■ stops and rewinds.',
    },
  },
  {
    id: 'chip', target: () => el.voiceChip,
    title: 'Your part',
    body: {
      mobile: 'This chip shows your voice (S/A/T/B). Tap it to mute your part so you sing it — tap again to hear it while you’re still learning.',
      desktop: 'This chip shows your voice (S/A/T/B). Click it to mute your part so you sing it — click again to hear it while you’re still learning.',
    },
  },
  {
    id: 'open', only: 'mobile', target: () => el.expandHandle, reveal: collapseTransport,
    title: 'More controls',
    body: 'Everything else tucks away down here. Tap ⌄ to open the full controls — voice, tempo, mic and the library.',
  },
  {
    id: 'voice', target: () => el.voicePicker, reveal: revealPane('practice'),
    title: 'Pick your voice',
    body: {
      mobile: 'Under Practice, choose the part you’re learning — Soprano, Alto, Tenor or Bass.',
      desktop: 'Under Practice, choose the part you’re learning — Soprano, Alto, Tenor or Bass (or press 1–4).',
    },
  },
  {
    id: 'tempo', target: () => el.panePractice && el.panePractice.querySelector('.row-fine'),
    reveal: revealPane('practice'),
    title: 'Tempo & loop',
    body: {
      mobile: 'Slow a hard passage right down, or set a Loop range and tick “on” to drill just those bars.',
      desktop: 'Slow a hard passage right down, or set a Loop range and press L to drill just those bars.',
    },
  },
  {
    id: 'mic', target: () => el.micBtn, reveal: revealPane('sound'),
    title: 'Sing & get scored',
    body: {
      mobile: 'In Sound, tap 🎤 Mic to sing along and get a per-note score. Headphones give the cleanest result on a phone.',
      desktop: 'In Sound, click 🎤 Mic (or press M) to sing along and get a per-note score. Headphones keep the mic from hearing the backing voices.',
    },
  },
  {
    id: 'library', target: () => el.libraryBtn, reveal: revealPane('more'),
    title: 'The library',
    body: 'Open 📚 Library to search thousands of hymns and chants by title, composer or feast.',
  },
  {
    id: 'finish', target: null,
    title: 'You’re ready',
    body: 'Sing along, watch the scope, and check your score after each pass. You can replay this anytime from the “?” up top.',
    guideLink: true,
  },
];

function buildSteps() {
  steps = STEPS.filter((s) => !s.only || s.only === device);
}

/* ---------- overlay state ------------------------------------------------- */
function setActive(on) {
  active = on;
  if (tourEl) tourEl.hidden = !on;
  // keys.js treats body.tour-active like an open modal, so Space/arrows don't
  // fire the transport/section shortcuts behind the tour (see keys.overlayOpen).
  document.body.classList.toggle('tour-active', on);
}

/* ---------- render + position -------------------------------------------- */
function stepText(step) {
  return (step.body && typeof step.body === 'object')
    ? (step.body[device] || step.body.desktop) : step.body;
}

function renderStep() {
  const step = steps[idx];
  if (!step) { endTour(true); return; }
  if (step.reveal) { try { step.reveal(); } catch (e) { /* non-fatal */ } }

  stepEl.textContent = `${idx + 1} / ${steps.length}`;
  titleEl.textContent = step.title;
  bodyEl.textContent = stepText(step);
  if (step.guideLink) {
    const a = document.createElement('a');
    a.href = 'tutorial.html';
    a.target = '_blank';
    a.rel = 'noopener';
    a.className = 'tour-guide-link';
    a.textContent = '📖 Open the written guide ↗';
    bodyEl.append(document.createElement('br'), a);
  }

  backBtn.hidden = idx === 0;
  const last = idx === steps.length - 1;
  nextBtn.textContent = last ? 'Done' : 'Next →';
  skipBtn.hidden = last;

  // Position now, then again after the transport's 0.3s expand animation
  // settles (reveal may have un-collapsed it). #tourSpot/#tourCard carry a CSS
  // transition so the second placement glides rather than snaps.
  clearTimeout(settleTimer);
  requestAnimationFrame(() => requestAnimationFrame(() => { if (active) position(step, true); }));
  settleTimer = setTimeout(() => { if (active && steps[idx] === step) position(step, false); }, 360);
}

function position(step, doScroll) {
  if (!step) return;
  const target = step.target ? step.target() : null;
  let rect = null;
  if (target && target.getClientRects().length) {
    if (doScroll) { try { target.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) { /* older engines */ } }
    rect = target.getBoundingClientRect();
  }

  const vw = window.innerWidth, vh = window.innerHeight;
  const PAD = 6, GAP = 14;

  if (rect) {
    spotEl.classList.remove('no-target');
    spotEl.style.left = (rect.left - PAD) + 'px';
    spotEl.style.top = (rect.top - PAD) + 'px';
    spotEl.style.width = (rect.width + PAD * 2) + 'px';
    spotEl.style.height = (rect.height + PAD * 2) + 'px';
  } else {
    // No target (welcome / finish): dim the whole screen, no hole.
    spotEl.classList.add('no-target');
    spotEl.style.left = '0px';
    spotEl.style.top = '0px';
    spotEl.style.width = vw + 'px';
    spotEl.style.height = vh + 'px';
  }

  const cw = cardEl.offsetWidth, ch = cardEl.offsetHeight;
  let left, top;
  if (!rect) {
    left = (vw - cw) / 2;
    top = (vh - ch) / 2;
  } else {
    const below = vh - rect.bottom, above = rect.top, right = vw - rect.right, leftSp = rect.left;
    if (below >= ch + GAP) { top = rect.bottom + GAP; left = rect.left + rect.width / 2 - cw / 2; }
    else if (above >= ch + GAP) { top = rect.top - GAP - ch; left = rect.left + rect.width / 2 - cw / 2; }
    else if (leftSp >= cw + GAP) { left = rect.left - GAP - cw; top = rect.top + rect.height / 2 - ch / 2; }
    else if (right >= cw + GAP) { left = rect.right + GAP; top = rect.top + rect.height / 2 - ch / 2; }
    else { left = (vw - cw) / 2; top = (vh - ch) / 2; }
  }
  left = Math.max(12, Math.min(left, vw - cw - 12));
  top = Math.max(12, Math.min(top, vh - ch - 12));
  cardEl.style.left = Math.round(left) + 'px';
  cardEl.style.top = Math.round(top) + 'px';
}

function onReflow() { if (active) position(steps[idx], false); }

/* ---------- navigation ---------------------------------------------------- */
export function startTour() {
  if (!tourEl) return;
  closeMenu();
  device = isMobile() ? 'mobile' : 'desktop';
  buildSteps();
  idx = 0;
  setActive(true);
  renderStep();
}

export function tourNext() {
  if (!active) return;
  if (idx >= steps.length - 1) { endTour(true); return; }
  idx += 1;
  renderStep();
}

export function tourPrev() {
  if (!active || idx <= 0) return;
  idx -= 1;
  renderStep();
}

export function endTour() {
  if (!active) return;
  clearTimeout(settleTimer);
  setActive(false);
  writeSeen();
  // Return the app to its default resting state: on mobile that means the
  // Practice pane selected and the transport re-collapsed so the score is
  // visible again (matches cold-load). Desktop collapse is a visual no-op.
  if (device === 'mobile') {
    const tab = el.paneStrip && el.paneStrip.querySelector('[data-pane="practice"]');
    if (tab) tab.click();
    setOverlay(false);
  }
}

/* ---------- header "?" help menu ----------------------------------------- */
function openMenu() {
  if (!helpMenu) return;
  helpMenu.hidden = false;
  menuOpen = true;
  helpBtn.setAttribute('aria-expanded', 'true');
}
function closeMenu() {
  if (!helpMenu || !menuOpen) return;
  helpMenu.hidden = true;
  menuOpen = false;
  helpBtn.setAttribute('aria-expanded', 'false');
}

/* ---------- init + auto-start -------------------------------------------- */
export function initTour() {
  tourEl = document.getElementById('tour');
  if (!tourEl) return;
  spotEl = document.getElementById('tourSpot');
  cardEl = document.getElementById('tourCard');
  stepEl = document.getElementById('tourStep');
  titleEl = document.getElementById('tourTitle');
  bodyEl = document.getElementById('tourBody');
  skipBtn = document.getElementById('tourSkip');
  backBtn = document.getElementById('tourBack');
  nextBtn = document.getElementById('tourNext');

  skipBtn.addEventListener('click', () => endTour(false));
  backBtn.addEventListener('click', tourPrev);
  nextBtn.addEventListener('click', tourNext);

  helpBtn = document.getElementById('helpBtn');
  helpMenu = document.getElementById('helpMenu');
  helpTour = document.getElementById('helpTour');
  if (helpBtn && helpMenu) {
    helpBtn.addEventListener('click', (e) => { e.stopPropagation(); menuOpen ? closeMenu() : openMenu(); });
    if (helpTour) helpTour.addEventListener('click', () => { closeMenu(); startTour(); });
    // click-away + Esc close the little menu
    document.addEventListener('click', (e) => {
      if (menuOpen && !helpMenu.contains(e.target) && e.target !== helpBtn) closeMenu();
    });
  }

  // Tour keyboard control. Capture phase + stopPropagation so these never leak
  // to keys.js (belt-and-suspenders — body.tour-active already gates it there).
  document.addEventListener('keydown', (e) => {
    if (!active) return;
    if (e.key === 'Escape') { e.preventDefault(); endTour(false); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); tourPrev(); }
    else if (e.key === 'ArrowRight' || e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault(); e.stopPropagation(); tourNext();
    }
  }, true);

  window.addEventListener('resize', onReflow);
  window.addEventListener('scroll', onReflow, true);   // capture inner (pane/rail) scrolls too
}

export function maybeAutoStartTour() {
  try {
    const p = new URLSearchParams(location.search);
    if (p.get('tour') === '1') { startTour(); return; }   // explicit — always
    if (navigator.webdriver) return;                        // never onboard automation (CI smoke)
    if (seen()) return;                                     // once per browser
    startTour();
  } catch (e) { /* never let onboarding break boot */ }
}

// Read-only introspection for the window.__tour test hook (see main.js).
export const tourState = {
  isActive: () => active,
  index: () => idx,
  count: () => steps.length,
  device: () => device,
  stepIds: () => steps.map((s) => s.id),
};
