/* keys.js — desktop keyboard shortcuts (Calm Surface #73/§5, issue #72).
 *
 * New module, wired from main.js with a single init call. Deliberately does
 * NOT reach into transport.js/voices.js/sections.js/scoring-ui.js/state.js's
 * internals beyond their existing exports (or, for actions with no exported
 * entry point — mic, record — the same DOM elements/buttons those modules
 * already wire a click listener onto, via `el`). Nothing here is load-bearing
 * for mouse/touch use: every shortcut re-uses machinery another module
 * already owns and tested.
 *
 * Active at all widths (harmless on mobile — no hardware keyboard, and the
 * guards below make it a no-op while typing or with an overlay open) but
 * "advertised" (title-attribute shortcut suffixes) only >=1000px, per §5's
 * hover/tooltip policy.
 */
import { el } from './state.js';
import { parsed } from './model.js';
import { playPause } from './transport.js';
import { activeVerse, setVerse } from './voices.js';
import { toggleRecording } from './recording.js';

  /* ---------- Guards ---------------------------------------------------- */

  // Typing contexts: space must type a space in #libSearch, digits must type
  // digits in #loopFrom/#loopTo, etc. — every guarded element here is an
  // <input> (search/number/range/checkbox), <select>, or <textarea>.
  function isTypingTarget(t) {
    if (!t) return false;
    const tag = (t.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return true;
    return !!t.isContentEditable;
  }

  // The library overlay and the section-jump bottom sheet are their own
  // Esc-closable modal surfaces (sections.js/library.js already own that) —
  // shortcuts here would either double-fire an action behind the modal or
  // steal a key (e.g. arrow keys) a listbox inside them wants. Read straight
  // off the DOM `hidden` flag both modules already toggle — no new exports
  // needed from either.
  function overlayOpen() {
    return !!((el.overlay && !el.overlay.hidden) || (el.sectionSheet && !el.sectionSheet.hidden));
  }

  /* ---------- Actions ----------------------------------------------------- *
   * Each either calls an exported function directly (playPause, setVerse) or
   * drives the exact control another module already wired a listener onto
   * (clicking a button / toggling a checkbox + firing its `change`) — so the
   * existing disabled/hidden/no-op logic in that module is inherited for
   * free, rather than re-implemented here.
   */

  function clickIfEnabled(btn) {
    if (btn && !btn.disabled) btn.click();
  }

  function toggleCheckboxControl(box) {
    if (!box) return;
    box.checked = !box.checked;
    box.dispatchEvent(new Event('change', { bubbles: true }));
  }

  // V: cycle the verse toggle (voices.js). No-op for single-verse pieces —
  // mirrors buildVersePicker's own `max < 2` hide condition.
  function cycleVerse() {
    const max = parsed ? (parsed.maxVerse || 1) : 1;
    if (max < 2) return;
    setVerse((activeVerse % max) + 1);
  }

  // 1-4: select the Nth vbtn in the voice picker (S/A/T/B order — see
  // voices.js's buildVoicePicker). A monophonic piece renders a 2-segment
  // Playing/Muted control instead (no .vbtn at all), so this is naturally a
  // no-op there — nothing to query.
  function selectVoiceSlot(n) {
    const btns = el.voicePicker ? [...el.voicePicker.querySelectorAll('.vbtn')] : [];
    const b = btns[n - 1];
    if (b) b.click();
  }

  const KEY_ACTIONS = {
    ' ': (e) => { e.preventDefault(); playPause(); },
    'Spacebar': (e) => { e.preventDefault(); playPause(); },   // legacy IE-style key name, cheap to keep
    'ArrowLeft': (e) => { if (el.secPrev && !el.secPrev.disabled) { e.preventDefault(); el.secPrev.click(); } },
    'ArrowRight': (e) => { if (el.secNext && !el.secNext.disabled) { e.preventDefault(); el.secNext.click(); } },
    'v': () => cycleVerse(),
    'V': () => cycleVerse(),
    'm': () => clickIfEnabled(el.micBtn),
    'M': () => clickIfEnabled(el.micBtn),
    'r': () => { toggleRecording(); },
    'R': () => { toggleRecording(); },
    'l': () => toggleCheckboxControl(el.loopOn),
    'L': () => toggleCheckboxControl(el.loopOn),
    '1': () => selectVoiceSlot(1),
    '2': () => selectVoiceSlot(2),
    '3': () => selectVoiceSlot(3),
    '4': () => selectVoiceSlot(4),
  };

  function onKeydown(e) {
    if (e.defaultPrevented || e.isComposing) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;   // never hijack a browser/OS chord
    if (e.repeat) return;                              // one toggle per press, not per auto-repeat tick
    if (isTypingTarget(e.target)) return;
    if (overlayOpen()) return;                          // Esc (unchanged, owned elsewhere) still works
    const fn = KEY_ACTIONS[e.key];
    if (fn) fn(e);
  }

  /* ---------- Desktop tooltip suffixes (§5 "Hover/tooltip policy") ------- *
   * Native `title` only — no tooltip component. ">=1000px, keys.js appends
   * the shortcut to the title." Reverted on a resize back below the
   * breakpoint so mobile never shows a hint for a key it can't use.
   * voicePicker/versePicker are rebuilt per piece/load (fresh DOM nodes), so
   * a MutationObserver re-applies the suffix to newly-built buttons whenever
   * the desktop breakpoint is currently active.
   */
  function titleTargets() {
    const vbtns = el.voicePicker ? [...el.voicePicker.querySelectorAll('.vbtn')] : [];
    const verseBtns = (el.verseRow && !el.verseRow.hidden && el.versePicker)
      ? [...el.versePicker.querySelectorAll('.segbtn')] : [];
    return [
      [el.play, 'Space'],
      [el.secPrev, '←'],
      [el.secNext, '→'],
      [el.micBtn, 'M'],
      [el.recBtn, 'R'],
      [el.loopOn && el.loopOn.closest('label'), 'L'],
      ...vbtns.map((b, i) => [b, String(i + 1)]),
      ...verseBtns.map((b) => [b, 'V cycles']),
    ];
  }

  function applyDesktopTitles(active) {
    titleTargets().forEach(([node, key]) => {
      if (!node) return;
      if (node.dataset.baseTitle == null) node.dataset.baseTitle = node.getAttribute('title') || '';
      const base = node.dataset.baseTitle;
      node.title = active ? (base ? `${base} (${key})` : `(${key})`) : base;
    });
  }

export function initKeys() {
    document.addEventListener('keydown', onKeydown);

    const mq = (window.matchMedia && window.matchMedia('(min-width:1000px)')) || { matches: false };
    const sync = () => applyDesktopTitles(!!mq.matches);
    sync();
    if (mq.addEventListener) mq.addEventListener('change', sync);
    else if (mq.addListener) mq.addListener(sync);   // Safari <14 fallback

    // Re-suffix freshly-built voice/verse buttons (piece switch, voice-list
    // change) while the desktop breakpoint is active. No-op cost otherwise —
    // childList mutations on these two small containers are infrequent
    // (once per piece load), never per-frame.
    if (typeof MutationObserver === 'function') {
      const mo = new MutationObserver(() => { if (mq.matches) sync(); });
      if (el.voicePicker) mo.observe(el.voicePicker, { childList: true });
      if (el.versePicker) mo.observe(el.versePicker, { childList: true });
    }
  }
