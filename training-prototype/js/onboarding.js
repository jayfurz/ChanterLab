/* onboarding.js — first-run coach-marks (issue #64): a lightweight,
 * dismissible hint sequence shown only until localStorage's ONBOARDING_KEY
 * flag is set. Reuses a single floating bubble (#onboardHint) — retexted and
 * repositioned per moment — so hints never stack; the flag is set once (after
 * the first full play->stop cycle) so the sequence never re-shows.
 *
 * Three moments, each firing at most once per browser:
 *   (a) on load                              — near Play
 *   (b) after the first play that ACTUALLY   — near the voice chip
 *       starts audio (coordinated with the
 *       issue #63 unlock guard — see onPlaySucceeded)
 *   (c) after the first Stop, only if the mic — near Play (generic; the mic
 *       was never turned on this run             button itself may be hidden
 *                                                 while the transport is
 *                                                 collapsed on mobile)
 *
 * Owns: onboarded, playedOnce, micEverUsed, done (all private below).
 */
import { el, ONBOARDING_KEY } from './state.js';
import { isMonophonic } from './model.js';

let onboarded = true;     // pessimistic default; set from localStorage in init()
let playedOnce = false;   // step (b) fires once, after the first successful Play
let micEverUsed = false;  // tracked from main.js's toggleMic() turning mic ON
let done = false;         // the whole sequence has concluded (step c decided)
let lastAnchor = null;

function readFlag() {
  try { return localStorage.getItem(ONBOARDING_KEY) === '1'; }
  catch (e) { return true; }   // storage disabled — don't nag every load
}
function writeFlag() {
  try { localStorage.setItem(ONBOARDING_KEY, '1'); } catch (e) { /* non-fatal */ }
}

function hideHint() {
  if (el.onboardHint) el.onboardHint.hidden = true;
}

  // Position the bubble's `left` (px) centered on the anchor's horizontal
  // center, clamped to stay fully on-screen — mobile-safe; `bottom` is fixed
  // in CSS (tracks --transport-h) so vertical placement is always just above
  // the transport, collapsed or expanded.
function positionHint(anchorEl) {
  const hint = el.onboardHint;
  if (!hint) return;
  lastAnchor = anchorEl || null;
  const vw = window.innerWidth || 360;
  // Mirrors the CSS max-width rule (min(280px, 100vw - 24px)) instead of
  // measuring the live element: offsetWidth read right after unhiding can
  // still reflect a pre-layout size on some engines/timings (observed ~195px
  // vs. the settled ~273px on a 390px viewport), which under-clamped the
  // bubble partly off-screen. The CSS-derived upper bound is always >= the
  // actual rendered width, so clamping against it never lets the bubble
  // overflow — worst case it sits a little more centered than strictly
  // necessary for a short line of text.
  const hw = Math.min(280, vw - 24);
  const rect = (anchorEl && anchorEl.getClientRects().length) ? anchorEl.getBoundingClientRect() : null;
  let cx = rect ? rect.left + rect.width / 2 : vw / 2;
  cx = Math.max(hw / 2 + 10, Math.min(cx, vw - hw / 2 - 10));
  hint.style.left = Math.round(cx) + 'px';
}

function showHint(text, anchorEl) {
  if (onboarded || !el.onboardHint || !el.onboardHintText) return;
  el.onboardHintText.textContent = text;
  el.onboardHint.hidden = false;
  positionHint(anchorEl);
}

export function initOnboarding() {
  onboarded = readFlag();
  if (el.onboardHintClose) el.onboardHintClose.addEventListener('click', hideHint);
  window.addEventListener('resize', () => {
    if (!onboarded && el.onboardHint && !el.onboardHint.hidden) positionHint(lastAnchor);
  });
  if (!onboarded) showHint('This plays the other voices — you sing YOURS. Tap ▶ to hear it.', el.play);
}

  // Called by main.js's toggleMic() the moment the mic is actually turned ON
  // (never on a failed getUserMedia attempt) — feeds step (c)'s condition.
export function markMicUsed() { micEverUsed = true; }

  // Called by transport.js right after a Play tap that ACTUALLY starts audio
  // (Tone context ended up 'running') — never after a tap that only produced
  // "Tap again to enable sound." (issue #63's suspended-context guard), so
  // onboarding never advances past step (a) while the context is still locked.
export function onPlaySucceeded() {
  if (onboarded || playedOnce) return;
  playedOnce = true;
  hideHint();
  const text = isMonophonic()
    ? 'Follow the melody — tap 🎤 to get scored.'
    : 'Your voice is muted — that’s the practice. Pick a different part here.';
  showHint(text, el.voiceChip);
}

  // Called by transport.js's stop(). Only meaningful after the first
  // successful Play (see playedOnce) — a Stop tapped before ever Playing is a
  // no-op for onboarding. Concludes the sequence and persists the flag either
  // way (step c only VISIBLY fires if the mic was never used).
export function onStopped() {
  if (onboarded || !playedOnce || done) return;
  done = true;
  hideHint();
  if (!micEverUsed) {
    showHint('Turn on 🎤 and you’ll get a per-note score.', el.play);
  }
  onboarded = true;
  writeFlag();
}
