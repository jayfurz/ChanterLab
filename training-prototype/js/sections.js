/* sections.js — jump-to-section index (manifest-first, XML-scan fallback),
 * the bottom-sheet UI, prev/next nav, and live active-section tracking.
 */
import { el } from './state.js';
import { parsed } from './model.js';
import { ensureRenderWindow, lastPrinted } from './loader.js';
import { stop, parkCursorAtWindowStart, playState } from './transport.js';
import { buildScopeLane } from './voices.js';

export let currentSections = [];
export let activeSectionIdx = -1;
export let xmlScannedSections = [];   // fallback sections scanned from the loaded XML
let sectionSheetOpen = false;

  /* ---------- Jump to section ----------------------------------------- *
   * Multi-section pieces (full liturgies) carry a section index — a list of
   * {title, measure} in ascending printed-measure order. Source of truth is the
   * manifest (piece.sections); a FALLBACK scans the loaded MusicXML's top part
   * for <direction placement="above"><words>…</words></direction> markers.
   * Selecting a section stops playback, sets the loop window to that section's
   * measure span, renders + parks the cursor there, and scrolls it into view —
   * without auto-playing. The active section is tracked live during playback.
   */

  // Fallback source: printed measure + title for every top-part <words>
  // direction. ≥2 hits → usable as a section index (see resolveSectionsFor).
  function scanXmlSections(doc) {
    try {
      const part = doc && doc.getElementsByTagName('part')[0];
      if (!part) return [];
      const out = [];
      for (const meas of Array.from(part.getElementsByTagName('measure'))) {
        const num = parseInt(meas.getAttribute('number'), 10);
        if (!num) continue;
        // only DIRECT-child <direction> of the measure; first words wins
        for (const d of Array.from(meas.children)) {
          if (d.tagName !== 'direction') continue;
          if (d.getAttribute('placement') !== 'above') continue;
          const w = d.getElementsByTagName('words')[0];
          const txt = w && (w.textContent || '').trim();
          if (txt) { out.push({ title: txt, measure: num }); break; }
        }
      }
      // de-dupe consecutive same-measure entries defensively; keep ascending
      return out.sort((a, b) => a.measure - b.measure);
    } catch (e) { return []; }
  }

  // Manifest sections win when present (≥2); else the XML-scanned fallback (≥2);
  // else none (control stays hidden).
  function resolveSectionsFor(piece) {
    const ms = piece && Array.isArray(piece.sections) ? piece.sections : null;
    if (ms && ms.length >= 2) return ms.map((s) => ({ title: String(s.title), measure: s.measure }));
    if (xmlScannedSections.length >= 2) return xmlScannedSections.slice();
    return [];
  }

  // Recompute the section index for the just-loaded piece and (re)build the UI.
export function applySections(piece) {
    currentSections = resolveSectionsFor(piece);
    activeSectionIdx = -1;
    buildSectionSheet();
    updateSectionsUI();
  }

  // Highest printed measure at/below `measure` → its section index (or -1).
export function sectionIndexForMeasure(measure) {
    if (!currentSections.length || measure == null) return -1;
    let lo = 0, hi = currentSections.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (currentSections[mid].measure <= measure) { ans = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    return ans;
  }

  function updateSectionsUI() {
    const has = currentSections.length >= 2;
    if (el.sectionsRow) el.sectionsRow.hidden = !has;
    // Calm Surface (#73): the always-visible mini-row § shortcut tracks the same
    // "multi-section piece" condition — hidden entirely for short hymns.
    if (el.sectionsMini) el.sectionsMini.hidden = !has;
    updateSectionLabel();
    markActiveSectionItem();
    updateSectionNav();
  }

  function updateSectionLabel() {
    if (!el.sectionsLabel) return;
    const s = activeSectionIdx >= 0 ? currentSections[activeSectionIdx] : null;
    el.sectionsLabel.textContent = s ? s.title : 'Sections';
    if (el.sectionsBtn) {
      el.sectionsBtn.title = s ? `Section: ${s.title} (m${s.measure}) — tap to jump` : 'Jump to a section';
    }
  }

export function updateSectionNav() {
    const n = currentSections.length;
    if (el.secPrev) el.secPrev.disabled = !n || activeSectionIdx <= 0;
    if (el.secNext) el.secNext.disabled = !n || (activeSectionIdx >= 0 && activeSectionIdx >= n - 1);
  }

  // Set the active section index and refresh only the bits that depend on it.
export function setActiveSection(idx) {
    if (idx === activeSectionIdx) return;
    activeSectionIdx = idx;
    updateSectionLabel();
    markActiveSectionItem();
    updateSectionNav();
  }

  // (Re)build the bottom-sheet list. Small (≤ a few dozen rows) → no windowing.
  function buildSectionSheet() {
    const list = el.sectionSheetList;
    if (!list) return;
    list.innerHTML = '';
    currentSections.forEach((s, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'sec-item' + (i === activeSectionIdx ? ' active' : '');
      b.dataset.idx = String(i);
      b.setAttribute('role', 'option');
      const mm = document.createElement('span');
      mm.className = 'sec-item-m'; mm.textContent = 'm ' + s.measure;
      const tt = document.createElement('span');
      tt.className = 'sec-item-t'; tt.textContent = s.title;
      b.append(mm, tt);
      list.appendChild(b);
    });
  }

  function markActiveSectionItem() {
    if (!el.sectionSheetList) return;
    el.sectionSheetList.querySelectorAll('.sec-item').forEach((node) => {
      node.classList.toggle('active', Number(node.dataset.idx) === activeSectionIdx);
    });
  }

  // Core: seek to section i. Stops playback, sets loop = [measure, next-1]
  // (last section → through the last printed measure), renders + parks the
  // cursor, scrolls into view. Does NOT auto-play.
export function jumpToSection(i) {
    if (!currentSections.length) return false;
    if (el.play && el.play.disabled) return false;   // busy: a load is in flight
    i = Math.max(0, Math.min(i | 0, currentSections.length - 1));
    const s = currentSections[i];
    const next = currentSections[i + 1];
    const from = Math.max(1, Math.round(s.measure) || 1);
    const to = next
      ? Math.max(from, Math.round(next.measure) - 1)
      : Math.max(from, lastPrinted || (parsed ? parsed.measureCount : from));
    if (playState !== 'stopped') stop();
    ensureRenderWindow(from, to);            // large scores: render the range first
    el.loopFrom.value = from;
    el.loopTo.value = to;
    buildScopeLane();
    parkCursorAtWindowStart();
    setActiveSection(i);
    return true;
  }

  function openSectionSheet() {
    if (currentSections.length < 2 || !el.sectionSheet) return;
    sectionSheetOpen = true;
    el.sectionSheet.hidden = false;
    document.body.classList.add('sec-lock');
    buildSectionSheet();
    // scroll the active row (if any) into view within the sheet
    requestAnimationFrame(() => {
      const act = el.sectionSheetList && el.sectionSheetList.querySelector('.sec-item.active');
      if (act) act.scrollIntoView({ block: 'center' });
    });
  }

  function closeSectionSheet() {
    if (!sectionSheetOpen) return;
    sectionSheetOpen = false;
    if (el.sectionSheet) el.sectionSheet.hidden = true;
    document.body.classList.remove('sec-lock');
  }

export function initSections() {
    if (el.sectionsBtn) el.sectionsBtn.addEventListener('click', () => {
      if (sectionSheetOpen) closeSectionSheet(); else openSectionSheet();
    });
    // Calm Surface (#73): the mini-row § opens the same bottom sheet.
    if (el.sectionsMini) el.sectionsMini.addEventListener('click', () => {
      if (sectionSheetOpen) closeSectionSheet(); else openSectionSheet();
    });
    if (el.secPrev) el.secPrev.addEventListener('click', () =>
      jumpToSection(activeSectionIdx < 0 ? 0 : activeSectionIdx - 1));
    if (el.secNext) el.secNext.addEventListener('click', () =>
      jumpToSection(activeSectionIdx < 0 ? 0 : activeSectionIdx + 1));
    if (el.sectionSheetClose) el.sectionSheetClose.addEventListener('click', () => closeSectionSheet());
    if (el.sectionSheet) el.sectionSheet.addEventListener('click', (e) => {
      if (e.target === el.sectionSheet) closeSectionSheet();   // scrim tap
    });
    if (el.sectionSheetList) el.sectionSheetList.addEventListener('click', (e) => {
      const item = e.target.closest('.sec-item');
      if (!item) return;
      closeSectionSheet();
      jumpToSection(Number(item.dataset.idx));
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && sectionSheetOpen) { e.stopPropagation(); closeSectionSheet(); }
    });
  }

// XML-section storage helpers (called by loader.loadScore, which owns the load).
export function clearXmlSections() { xmlScannedSections = []; }
export function prepareXmlSections(doc) { xmlScannedSections = scanXmlSections(doc); }

