/* library.js — the full-screen piece library: manifest ingest, windowed
 * sectioned list, debounced search, and faceted filter chips.
 */
import { el, PIECES, N_BUILTIN, DEFAULT_MANIFEST, fold } from './state.js';
import { loadPieceById } from './loader.js';

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

  // Hymn-type facet (issue #85, manifest field `hymnType`) — human labels for
  // the slugs ingest_catalog.py's HYMN_ORDINARY/HYMN_PROPER/ANAPHORA_SUB
  // produce. Most slugs are just their words underscore-joined ("cherubic_
  // hymn" -> "Cherubic Hymn", "apolytikion" -> "Apolytikion") so a title-case
  // transform handles them; this map only overrides the few that would read
  // wrong straight — a dropped apostrophe, or a slug name that doesn't match
  // the actual liturgical term (see hymn_type()'s own comments there).
  const HYMN_TYPE_STOPWORDS = new Set(['of', 'the', 'a', 'an', 'and']);
  const HYMN_TYPE_LABELS = {
    lords_prayer: "Lord's Prayer",
    magnification: 'Megalynarion',          // slug name is misleading — this
                                             // bucket is magnificat/megalynarion
                                             // text, not literal "magnification"
    communion_praise: 'Communion Hymn',
    anaphora_litany: 'Litany of the Anaphora',
  };
  function hymnTypeLabel(slug) {
    if (HYMN_TYPE_LABELS[slug]) return HYMN_TYPE_LABELS[slug];
    return slug.split('_').map((w, i) => (i > 0 && HYMN_TYPE_STOPWORDS.has(w))
      ? w : w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  }
export const libCollapsed = new Set(['Menaion', 'Theotokia']);
export const libFacetDefs = { arrangement: [], tone: [], hymnType: [], composer: [] };
  const libActive = { arrangement: new Set(), tone: new Set(), hymnType: new Set(), composer: new Set() };
  let libSearch = '';        // folded search string
export let libFlat = [];          // [{type:'group'|'sub'|'row'|'hint', ...}]
export let libOffsets = [];       // prefix pixel offset per flat index
  let libTotalH = 0;
  let libRange = [-1, -1];   // currently-rendered [start,end) window
export let libOpen = false;
  let libPushed = false;     // whether we pushed a history entry for the overlay
  let libSearchTimer = 0, libScrollRaf = 0;

  // Prototype items (the 5 built-ins) rendered into the library too.
export const libProto = PIECES.slice(0, N_BUILTIN).map((p) => ({
    id: p.id, title: p.title, composer: p.composer, tone: null,
    arrangement: p.arrangement, liturgicalDate: '', section: 'proto',
    norm: fold([p.title, p.composer, p.arrangement].join(' ')),
  }));
export const libItems = [];   // manifest-derived items

export async function loadLibraryManifest() {
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
              // Manifest attribution (composer/book of the original source
              // engraving). Only ever set for ingest_* library items — the 5
              // hard-coded Prototype PIECES above never carry a bookName, and
              // that's exactly the signal setCurrentPiece() uses to decide
              // whether to show the attribution line (see there).
              attribComposer: (it.composer || '').trim() || null,
              bookName: (it.bookName || '').trim() || null,
              // section index for the jump-to-section control (manifest source;
              // ascending by printed measure). Absent for single-hymn pieces.
              sections: Array.isArray(it.sections) ? it.sections : null,
            });
          }
          const toneClean = (typeof it.toneClean === 'number') ? it.toneClean : null;
          const hymnType = it.hymnType || null;
          const key = (it.key || '').trim() || null;
          libItems.push({
            id, title: it.title || '(untitled)', composer: (it.composer || '').trim(),
            tone: (it.tone != null && it.tone !== '') ? String(it.tone) : null,
            toneClean,
            arrangement: it.arrangementType || '', liturgicalDate: it.liturgicalDate || '',
            bookName: (it.bookName || '').trim() || null,
            pdfUrl: it.pdfUrl || null,
            section: 'lib',
            // taxonomy from ingest_catalog.liturgical_group (see LIB_GROUP_ORDER)
            group: it.group || 'Other services & misc',
            sub: (it.sub != null && it.sub !== '') ? it.sub : null,
            rank: (typeof it.rank === 'number') ? it.rank : 99000,
            // hymn-type facet (issue #85, manifest field `hymnType`) — slug
            // from ingest_catalog.hymn_type(), null on whole-liturgy/multi-
            // hymn compilations it conservatively declines to classify.
            hymnType,
            // key signature label (issue #85, manifest field `key`, e.g. "F
            // major / D minor") — present on every item, but only ever RENDERED
            // on a row when computeKeyVisibility() below flags it as needed to
            // break a title+composer collision; always folded into the search
            // index regardless (see norm below).
            key,
            showKey: false,
            // search index (issue #76/#85): fold in the QA'd tone (toneClean
            // only — the raw `tone` field is littered with junk like
            // "Carpathian" / "1,2,3,4,5,6,7,8" that would pollute free-text
            // matches) as "Tone N", plus the human hymn-type label and the key
            // label, so "cherubic tone 3" or "cherubic f major" can find a
            // piece via metadata that isn't in its title — see itemPasses()/
            // searchMatches() below, which AND search terms independently
            // across this string rather than requiring a contiguous phrase.
            norm: fold([it.title, it.composer, it.liturgicalDate, it.arrangementType,
                        it.bookName, it.group, it.sub,
                        toneClean ? ('Tone ' + toneClean) : '',
                        hymnType ? hymnTypeLabel(hymnType) : '', key || ''].join(' ')),
          });
        });
      }
    } catch (e) { /* no manifest (fresh clone / bad URL) — empty state is fine */ }
    computeKeyVisibility();
    buildFacets();
    if (libOpen) rebuildLib();
  }

  // Key-collision detection (issue #85). Two keys alone (C major/A minor,
  // F major/D minor) cover 89% of the manifest, so printing `key` on every
  // row would just repeat the same handful of labels 3,000+ times — pure
  // clutter, not information. It earns a spot on a row only when title +
  // composer already collide and DON'T resolve the ambiguity themselves —
  // e.g. the Divine Liturgy's "Cherubic Hymn" cluster has 9 settings; 8
  // different composers already tell those apart with zero help from key,
  // but Richard Toensing alone contributes two (D major vs E-flat major) —
  // those two, and only those two, need the key label. Computed once from
  // the loaded data (grouped by group+title+composer), independent of
  // whatever the user is currently searching/filtering for, so it's exact
  // rather than a "show more while searching" heuristic that would still
  // over- or under-show it.
  function computeKeyVisibility() {
    const buckets = new Map();
    libItems.forEach((it) => {
      if (!it.key) return;
      const k = it.group + ' ' + fold(it.title) + ' ' + fold(it.composer);
      if (!buckets.has(k)) buckets.set(k, []);
      buckets.get(k).push(it);
    });
    buckets.forEach((bucket) => {
      if (bucket.length < 2) return;
      if (new Set(bucket.map((it) => it.key)).size > 1) {
        bucket.forEach((it) => { it.showKey = true; });
      }
    });
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

    // hymn type (issue #85): top 10 by count. 480 of 3,314 items are null
    // (whole-liturgy/multi-hymn compilations hymn_type() conservatively
    // declines to classify — see ingest_catalog.py) and are excluded, same as
    // junk tones above. ~25 distinct slugs exist across the manifest; capped
    // to the top 10 so the chip strip stays scannable (same reasoning as
    // composer's top-8 cap below).
    const htCounts = {};
    libItems.forEach((it) => { if (it.hymnType) htCounts[it.hymnType] = (htCounts[it.hymnType] || 0) + 1; });
    libFacetDefs.hymnType = Object.entries(htCounts).sort((a, b) => b[1] - a[1]).slice(0, 10)
      .map(([value, count]) => ({ value, label: hymnTypeLabel(value), count }));

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
    group('Hymn', libFacetDefs.hymnType, 'hymnType');
    group('Tone', libFacetDefs.tone, 'tone');
    group('Composer', libFacetDefs.composer, 'composer');
  }

  // Purely-numeric search tokens ("3") are matched at a word boundary so they
  // don't also hit digits embedded in unrelated text — a catalog code like
  // "13A" contains the character "3" but a search for tone "3" shouldn't
  // treat it as a hit (issue #76). Single-LETTER tokens get the same guard
  // (issue #85, now that `key` is in the search index): in "cherubic f
  // major" the 'f' means the standalone note name F, but a bare substring
  // 'f' also hits "E-flat", "Fr. Sergei", "4-part-Full choir"… — boundary
  // matching keeps the F-major rows and drops those. Multi-letter tokens
  // keep the existing loose substring match (so "cheru" still finds
  // "Cherubic" mid-word).
  function tokenMatches(norm, token) {
    if (/^[a-z0-9]$/.test(token) || /^\d+$/.test(token))
      return new RegExp('(^|[^a-z0-9])' + token + '($|[^a-z0-9])').test(norm);
    return norm.includes(token);
  }

  // Splits the (already folded) query on whitespace and requires every token
  // to appear SOMEWHERE in the item's norm string — an AND across fields, not
  // a contiguous phrase. This is what lets "cherubic tone 3" find a piece
  // whose tone comes from a different part of norm than its title (issue
  // #76); it's strictly more permissive than the old plain .includes() check,
  // so every query that matched before still matches (a contiguous phrase
  // trivially contains each of its own words).
  function searchMatches(it) {
    if (!libSearch) return true;
    return libSearch.split(/\s+/).filter(Boolean).every((t) => tokenMatches(it.norm, t));
  }

  function itemPasses(it) {
    if (!searchMatches(it)) return false;
    if (libActive.arrangement.size) {
      const ok = [...libActive.arrangement].some((v) => {
        const b = libFacetDefs.arrangement.find((x) => x.value === v);
        return b && b.test(fold(it.arrangement));
      });
      if (!ok) return false;
    }
    if (libActive.hymnType.size && !libActive.hymnType.has(it.hymnType)) return false;
    if (libActive.tone.size && !libActive.tone.has(String(it.toneClean))) return false;
    if (libActive.composer.size && !libActive.composer.has(it.composer)) return false;
    return true;
  }

  const libFiltersActive = () =>
    !!libSearch || libActive.arrangement.size || libActive.hymnType.size
    || libActive.tone.size || libActive.composer.size;

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
    // Tone (issue #76) — right after composer, quiet/muted (not the old gold
    // "badge" pill). Only the QA'd toneClean (1-8): the raw `tone` field is
    // littered with junk ("Carpathian", "Chant", multi-tone lists like
    // "1,2,3,4,5,6,7,8") that doesn't scan on a row — toneClean already
    // exists to filter that out (see buildFacets), so reuse it here instead
    // of re-deriving. Absent for ordinary chants and for the Western choral
    // settings that make up most of the "Cherubic Hymn" title cluster — rows
    // without a tone render exactly as before (no gap, no reflow: this span
    // simply isn't created, same as bookName/arrangement already do above).
    if (it.toneClean) {
      const tb = document.createElement('span'); tb.className = 'tone'; tb.textContent = 'Tone ' + it.toneClean; m.appendChild(tb);
    }
    // Key signature (issue #85) — right after tone, and ONLY when
    // computeKeyVisibility() flagged this row as a genuine title+composer
    // collision that key is the last remaining way to tell apart (see that
    // function's comment). Every item has a key, but two values (C major/A
    // minor, F major/D minor) alone cover 89% of the manifest — rendering it
    // unconditionally would repeat one of a handful of labels on almost every
    // one of 3,314 rows for zero information gain, so this stays off by
    // default and on for the rare row that actually needs it. Ultra-muted
    // (dimmer + smaller than tone/book/arr) since when it does show, it's
    // the least-important thing on the row — a tiebreaker, not a headline.
    if (it.showKey && it.key) {
      const kb = document.createElement('span'); kb.className = 'key'; kb.textContent = it.key; m.appendChild(kb);
    }
    // Source book — only when it adds information beyond what the group
    // header / sub-header above this row already say (e.g. Menaion collapses
    // "Menaion" + "Kazan Menaion" under one group; Anastasimatarion never
    // surfaces the underlying Octoechos/Octoechos Eothina book name).
    if (it.bookName && it.bookName !== it.group && it.bookName !== it.sub) {
      const bk = document.createElement('span'); bk.className = 'book'; bk.textContent = it.bookName; m.appendChild(bk);
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

export function renderWindow(force) {
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
export function toggleGroup(group) {
    if (!LIB_COLLAPSIBLE.has(group) || libFiltersActive()) return;
    if (libCollapsed.has(group)) libCollapsed.delete(group); else libCollapsed.add(group);
    rebuildLib(true);
  }

export function openLibrary() {
    libOpen = true;
    el.overlay.hidden = false;
    document.body.classList.add('lib-lock');
    rebuildLib();
    // avoid popping the soft keyboard over the list on touch devices
    if (!('ontouchstart' in window)) setTimeout(() => { try { el.libSearch.focus(); } catch (e) {} }, 30);
    if (window.history && history.pushState && !libPushed) { history.pushState({ libOpen: true }, ''); libPushed = true; }
  }

export function closeLibrary(fromPop) {
    if (!libOpen) return;
    libOpen = false;
    el.overlay.hidden = true;
    document.body.classList.remove('lib-lock');
    if (libPushed && !fromPop) { libPushed = false; if (history.state && history.state.libOpen) history.back(); }
    else libPushed = false;
  }

export function initLibrary() {
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
      // Close the overlay immediately so the phased load progress (status +
      // score spinner) is visible in the main UI while the piece loads.
      closeLibrary();
      loadPieceById(row.dataset.id);
    });
    el.libList.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const grp = e.target.closest('.lib-group.collapsible');
      if (grp) { e.preventDefault(); toggleGroup(grp.dataset.group); return; }
      const row = e.target.closest('.lib-row'); if (!row) return;
      e.preventDefault();
      closeLibrary();
      loadPieceById(row.dataset.id);
    });
    el.libList.addEventListener('scroll', () => {
      if (libScrollRaf) return;
      libScrollRaf = requestAnimationFrame(() => { libScrollRaf = 0; renderWindow(false); });
    }, { passive: true });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && libOpen) closeLibrary(); });
    window.addEventListener('popstate', () => { if (libOpen) closeLibrary(true); });
  }

