/* Characterization fixture: a parsed MusicXML model, hand-authored to the
 * exact shape parseMusicXML produces (training-prototype/js/model.js):
 *   parsed = { parts:[{voiceKey, voiceName, index, notes}], measureCount, maxVerse }
 *   note   = { midi, startBeat, durBeat, measure, lyric, lyricVerses }
 * with the parser's semantics baked in:
 *   - times in quarter-note beats (from <duration>/divisions);
 *   - ties already merged: the soprano's measure-2 C5 is a half note tied
 *     across the barline into measure 3, stored as ONE note with durBeat 3;
 *   - rests omitted entirely: the alto's measure-3 gap (beats 8..9) simply has
 *     no note — gaps are implicit in this model;
 *   - chords: followers share the leader's onset (alto beats 4..8 sounds with
 *     soprano's tie); begin/middle syllables carry a trailing '-'.
 * 4/4 throughout; measures start at beats 0, 4, 8; piece spans beats 0..12.
 */
export const WESTERN_PARSED_FIXTURE = Object.freeze({
  parts: [
    {
      voiceKey: 'S',
      voiceName: 'Soprano',
      index: 0,
      notes: [
        { midi: 67, startBeat: 0, durBeat: 1, measure: 1, lyric: 'Ho-', lyricVerses: { 1: 'Ho-' } },
        { midi: 69, startBeat: 1, durBeat: 1, measure: 1, lyric: 'ly', lyricVerses: { 1: 'ly' } },
        { midi: 71, startBeat: 2, durBeat: 2, measure: 1, lyric: 'God', lyricVerses: { 1: 'God' } },
        { midi: 72, startBeat: 4, durBeat: 3, measure: 2, lyric: 'Might-', lyricVerses: { 1: 'Might-' } },
        { midi: 71, startBeat: 7, durBeat: 1, measure: 2, lyric: 'y', lyricVerses: { 1: 'y' } },
        { midi: 69, startBeat: 8, durBeat: 4, measure: 3, lyric: 'One', lyricVerses: { 1: 'One' } },
      ],
    },
    {
      voiceKey: 'A',
      voiceName: 'Alto',
      index: 1,
      notes: [
        { midi: 60, startBeat: 0, durBeat: 2, measure: 1, lyric: 'Ho-', lyricVerses: { 1: 'Ho-' } },
        { midi: 62, startBeat: 2, durBeat: 2, measure: 1, lyric: 'God', lyricVerses: { 1: 'God' } },
        { midi: 64, startBeat: 4, durBeat: 4, measure: 2, lyric: 'Might-', lyricVerses: { 1: 'Might-' } },
        { midi: 65, startBeat: 9, durBeat: 3, measure: 3, lyric: 'One', lyricVerses: { 1: 'One' } },
      ],
    },
  ],
  measureCount: 3,
  maxVerse: 1,
});
