/* model.js — MusicXML parsing + the parsed note model + parsed-derived queries.
 * Owner of `parsed`; only setParsed() (called by loader.loadScore) reassigns it.
 */
import { VOICE_DEFS } from './state.js';

export let parsed = null;   // { parts:[{voiceKey,voiceName,index,notes}], measureCount, maxVerse }
export function setParsed(p) { parsed = p; return p; }

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

  // Takes an already-parsed MusicXML Document (the SAME Document handed to
  // osmd.load, so the string is DOMParser'd exactly once per load).
export function parseMusicXML(doc) {
    if (doc.getElementsByTagName('parsererror').length) throw new Error('XML parse error');

    const partNodes = Array.from(doc.getElementsByTagName('part'));
    const scoreParts = Array.from(doc.getElementsByTagName('score-part'));
    const partNames = {};
    scoreParts.forEach((sp) => {
      partNames[sp.getAttribute('id')] = (textOf(sp, 'part-name') || '').trim();
    });

    let measureCount = 0;
    let maxVerse = 1;   // highest lyric <number="N"> seen anywhere in the piece
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
                // ACTIVE-verse lyric syllable — unchanged selection (missing
                // number or "1" wins), so single-verse pieces and the default
                // load state are byte-identical to pre-multi-verse behavior.
                // Trailing dash on begin/middle syllables shows word
                // continuation in the scope lane.
                let lyric = null;
                const lyricEls = child.getElementsByTagName('lyric');
                let lyricEl = lyricEls[0];
                for (let li = 0; li < lyricEls.length; li++) {
                  const num = lyricEls[li].getAttribute('number');
                  if (!num || num === '1') { lyricEl = lyricEls[li]; break; }
                }
                if (lyricEl) {
                  const txt = textOf(lyricEl, 'text');
                  if (txt) {
                    const syl = textOf(lyricEl, 'syllabic');
                    lyric = (syl === 'begin' || syl === 'middle') ? txt + '-' : txt;
                  }
                }
                // Per-verse syllable map for the verse toggle. Verse 1 mirrors
                // `lyric` above exactly (same element, same fallback) so
                // restoring verse 1 after a toggle reproduces the default
                // exactly, edge cases included. Verse 2+ read their own
                // <lyric number="N"> element independently.
                let lyricVerses = null;
                for (let li = 0; li < lyricEls.length; li++) {
                  const elI = lyricEls[li];
                  const num = elI.getAttribute('number');
                  const vnum = num ? (parseInt(num, 10) || 1) : 1;
                  if (vnum === 1) continue; // covered by `lyric` below
                  const txt = textOf(elI, 'text');
                  if (!txt) continue;
                  const syl = textOf(elI, 'syllabic');
                  const syllable = (syl === 'begin' || syl === 'middle') ? txt + '-' : txt;
                  if (!lyricVerses) lyricVerses = {};
                  if (!(vnum in lyricVerses)) lyricVerses[vnum] = syllable; // first wins on dup
                  if (vnum > maxVerse) maxVerse = vnum;
                }
                if (lyric != null) {
                  if (!lyricVerses) lyricVerses = {};
                  lyricVerses[1] = lyric;
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
                    lyricVerses,
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
    return { parts, measureCount, maxVerse };
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

  // Switch which verse's syllables live in n.lyric (the field everything else
  // — the scope lane, propagateLyrics — reads). Re-derives n.lyric on every
  // note from its lyricVerses map, then re-runs propagateLyrics so parts that
  // carry no lyrics of their own (borrowed at parse time) re-borrow from the
  // NEW verse's donor text instead of staying stuck on verse 1's borrow.
  //
  // FALLBACK DECISION: when a note has no syllable recorded for the selected
  // verse, we fall back to its verse-1 syllable rather than leaving it blank.
  // Alternate-verse markings (e.g. Sunday vs. weekday antiphon texts) usually
  // diverge for only a phrase or two and share the rest of the text; a visible
  // gap mid-passage would read as "the app broke" to a singer following the
  // gold lane, whereas the verse-1 text is still correct/singable there just
  // not verse-2-specific. Continuous-but-sometimes-verse-1 reads better than
  // honest-but-broken-looking gaps.
export function applyVerseLyrics(verse) {
    if (!parsed) return;
    parsed.parts.forEach((p) => {
      p.notes.forEach((n) => {
        if (!n.lyricVerses) { n.lyric = null; return; }
        if (n.lyricVerses[verse] != null) { n.lyric = n.lyricVerses[verse]; return; }
        n.lyric = n.lyricVerses[1] != null ? n.lyricVerses[1] : null;
      });
    });
    propagateLyrics(parsed.parts);
  }

  // A single-<part> chant: the sole line is the melody, so the S/A/T/B "which is
  // yours" picker is meaningless — we show a Playing/Muted toggle instead and
  // key the mix off melodyMuted (see applyMix).
export function isMonophonic() { return !!parsed && parsed.parts.length === 1; }

export function clampMeasure(m) { return Math.min(Math.max(1, m || 1), parsed.measureCount); }

  // Build a per-measure beat map from the longest part (most onsets), so the
  // loop window maps measures->beats even without explicit barline math.
export function measureBeatRange(fromMeasure, toMeasure) {
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

