/* timed_score.js — the versioned timed-score practice contract (ONEAPP-01).
 *
 * A timed-score document is the smallest plain-data representation the
 * practice shell (transport, target lane, recording, scoring) needs. It is a
 * PRACTICE TIMELINE, not a notation model: rendering stays with the
 * notation-specific engines (OSMD for MusicXML, the chant glyph renderer),
 * reachable through score.sourceRef and per-event anchors/notationData that
 * consumers must treat as opaque.
 *
 * Pitch is a tagged union so microtonal semantics survive end-to-end:
 * every note target carries a deterministic absolute `hz` PLUS its native
 * coordinate — 12-ET MIDI (a4Hz-referenced) or Byzantine moria
 * (refNiHz-referenced, 72 per octave). Byzantine pitch is never rounded to
 * MIDI; the 8/10/12/14/20-moria interval distinctions that define the genera
 * are representable only in the moria coordinate.
 */

export const CONTRACT_NAME = 'chanterlab.timed-score';
export const CONTRACT_VERSION = '1.0.0';

// The training app's only MIDI->Hz conversion (training-prototype/js/transport.js midiToFreq).
export const DEFAULT_A4_HZ = 440;
// The tuning engine's reference Ni default, C3 (src/tuning/grid.rs DEFAULT_REF_NI_HZ).
export const DEFAULT_REF_NI_HZ = 130.81;
export const MORIA_PER_OCTAVE = 72;

export function hzFromMidi(midi, a4Hz = DEFAULT_A4_HZ) {
  return a4Hz * Math.pow(2, (midi - 69) / 12);
}

export function hzFromMoria(moria, refNiHz = DEFAULT_REF_NI_HZ) {
  return refNiHz * Math.pow(2, moria / MORIA_PER_OCTAVE);
}

// Capability negotiation: a consumer reads these flags instead of sniffing the
// notation type. Unsupported capabilities are explicit — a document must not
// carry lane data its flags deny (the validator enforces coherence), and a
// consumer that lacks a capability must degrade predictably (hide the control,
// never guess).
export const CAPABILITY_KEYS = Object.freeze([
  'microtonal', // note pitch uses the moria coordinate; 12-ET rounding loses meaning
  'ison', // timeline.ison lane is populated (drone to schedule alongside melody)
  'tuningChanges', // tuning context mutates mid-piece (timeline.tuningChanges)
  'tempoChanges', // more than one tempo lane entry
  'explicitRests', // rests are first-class events (MusicXML adapter omits them: gaps are implicit)
  'sections', // measure-anchored loopable section index (timeline.sections)
  'phrases', // phrase-boundary markers (timeline.phrases)
  'checkpoints', // martyria checkpoints (timeline.checkpoints)
  'multiPart', // more than one selectable part
  'lyrics', // at least one event carries a lyric syllable
]);

const PART_ROLES = new Set(['satb', 'melody', 'ison']);

function err(errors, path, message) {
  errors.push(`${path}: ${message}`);
}

function isFiniteNumber(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

function validatePitch(pitch, path, errors) {
  if (!pitch || typeof pitch !== 'object') {
    err(errors, path, 'pitch must be an object');
    return;
  }
  if (pitch.type === 'midi') {
    if (!isFiniteNumber(pitch.midi)) err(errors, path, 'midi pitch needs a finite `midi`');
    if (!isFiniteNumber(pitch.a4Hz) || pitch.a4Hz <= 0) err(errors, path, 'midi pitch needs a positive `a4Hz`');
  } else if (pitch.type === 'moria') {
    if (!isFiniteNumber(pitch.moria)) err(errors, path, 'moria pitch needs a finite `moria`');
    if (!isFiniteNumber(pitch.refNiHz) || pitch.refNiHz <= 0) err(errors, path, 'moria pitch needs a positive `refNiHz`');
  } else {
    err(errors, path, `unknown pitch type "${pitch?.type}"`);
  }
}

function validateLane(lane, path, errors, entryCheck) {
  if (lane === undefined) return;
  if (!Array.isArray(lane)) {
    err(errors, path, 'must be an array when present');
    return;
  }
  lane.forEach((entry, i) => {
    if (!entry || typeof entry !== 'object') {
      err(errors, `${path}[${i}]`, 'must be an object');
      return;
    }
    if ('atSec' in entry && (!isFiniteNumber(entry.atSec) || entry.atSec < 0)) {
      err(errors, `${path}[${i}]`, 'atSec must be a finite number >= 0');
    }
    if (entryCheck) entryCheck(entry, `${path}[${i}]`);
  });
}

/* Validate a timed-score document. Returns { ok, errors } — never throws.
 * This is the compatibility gate consumers run before trusting a document;
 * a major-version mismatch is an error by design (see README migration notes).
 */
export function validateTimedScore(doc) {
  const errors = [];
  if (!doc || typeof doc !== 'object') return { ok: false, errors: ['document must be an object'] };

  if (doc.contract !== CONTRACT_NAME) err(errors, 'contract', `must be "${CONTRACT_NAME}"`);
  const major = String(doc.contractVersion ?? '').split('.')[0];
  if (major !== CONTRACT_VERSION.split('.')[0]) {
    err(errors, 'contractVersion', `major version must be ${CONTRACT_VERSION.split('.')[0]} (got "${doc.contractVersion}")`);
  }

  if (!doc.score || typeof doc.score !== 'object') err(errors, 'score', 'required object');
  else {
    if (typeof doc.score.id !== 'string' || !doc.score.id) err(errors, 'score.id', 'required non-empty string');
    if (typeof doc.score.notation !== 'string' || !doc.score.notation) err(errors, 'score.notation', 'required non-empty string');
  }

  if (!doc.capabilities || typeof doc.capabilities !== 'object') err(errors, 'capabilities', 'required object');
  else {
    for (const key of Object.keys(doc.capabilities)) {
      if (!CAPABILITY_KEYS.includes(key)) err(errors, `capabilities.${key}`, 'unknown capability key');
      else if (typeof doc.capabilities[key] !== 'boolean') err(errors, `capabilities.${key}`, 'must be boolean');
    }
    for (const key of CAPABILITY_KEYS) {
      if (!(key in doc.capabilities)) err(errors, `capabilities.${key}`, 'missing (all keys must be explicit)');
    }
  }

  const partIds = new Set();
  if (!Array.isArray(doc.parts) || doc.parts.length === 0) err(errors, 'parts', 'required non-empty array');
  else {
    doc.parts.forEach((p, i) => {
      if (!p || typeof p.id !== 'string' || !p.id) err(errors, `parts[${i}].id`, 'required non-empty string');
      else if (partIds.has(p.id)) err(errors, `parts[${i}].id`, `duplicate part id "${p.id}"`);
      else partIds.add(p.id);
      if (!PART_ROLES.has(p?.role)) err(errors, `parts[${i}].role`, `must be one of ${[...PART_ROLES].join('/')}`);
      if (typeof p?.selectable !== 'boolean') err(errors, `parts[${i}].selectable`, 'must be boolean');
    });
  }

  const tl = doc.timeline;
  if (!tl || typeof tl !== 'object') {
    err(errors, 'timeline', 'required object');
    return { ok: errors.length === 0, errors };
  }
  if (tl.units !== 'seconds') err(errors, 'timeline.units', 'must be "seconds"');
  if (!isFiniteNumber(tl.totalSec) || tl.totalSec < 0) err(errors, 'timeline.totalSec', 'must be a finite number >= 0');

  const eventIds = new Set();
  const lastStartByPart = new Map();
  let sawMoria = false;
  if (!Array.isArray(tl.events)) err(errors, 'timeline.events', 'required array');
  else {
    tl.events.forEach((e, i) => {
      const path = `timeline.events[${i}]`;
      if (!e || typeof e !== 'object') {
        err(errors, path, 'must be an object');
        return;
      }
      if (typeof e.id !== 'string' || !e.id) err(errors, `${path}.id`, 'required non-empty string');
      else if (eventIds.has(e.id)) err(errors, `${path}.id`, `duplicate event id "${e.id}"`);
      else eventIds.add(e.id);
      if (!partIds.has(e.partId)) err(errors, `${path}.partId`, `unknown part "${e.partId}"`);
      if (e.kind !== 'note' && e.kind !== 'rest') err(errors, `${path}.kind`, 'must be "note" or "rest"');
      if (!isFiniteNumber(e.startSec) || e.startSec < 0) err(errors, `${path}.startSec`, 'must be a finite number >= 0');
      if (!isFiniteNumber(e.endSec) || e.endSec < e.startSec) err(errors, `${path}.endSec`, 'must be finite and >= startSec');
      if (e.kind === 'note') {
        if (!e.target || typeof e.target !== 'object') err(errors, `${path}.target`, 'notes require a target');
        else {
          if (!isFiniteNumber(e.target.hz) || e.target.hz <= 0) err(errors, `${path}.target.hz`, 'must be a positive finite number');
          validatePitch(e.target.pitch, `${path}.target.pitch`, errors);
          if (e.target.pitch?.type === 'moria') sawMoria = true;
        }
      } else if (e.target != null) {
        err(errors, `${path}.target`, 'rests must have a null target');
      }
      const prev = lastStartByPart.get(e.partId);
      if (prev !== undefined && isFiniteNumber(e.startSec) && e.startSec < prev) {
        err(errors, `${path}.startSec`, 'events must be non-decreasing in startSec within a part');
      }
      if (isFiniteNumber(e.startSec)) lastStartByPart.set(e.partId, e.startSec);
    });
  }

  validateLane(tl.tempo, 'timeline.tempo', errors, (entry, path) => {
    if (!isFiniteNumber(entry.bpm) || entry.bpm <= 0) err(errors, `${path}.bpm`, 'must be a positive finite number');
  });
  validateLane(tl.ison, 'timeline.ison', errors);
  validateLane(tl.tuningChanges, 'timeline.tuningChanges', errors);
  validateLane(tl.checkpoints, 'timeline.checkpoints', errors);
  validateLane(tl.phrases, 'timeline.phrases', errors);
  if (tl.sections !== undefined && !Array.isArray(tl.sections)) err(errors, 'timeline.sections', 'must be an array when present');

  // Capability coherence: lane data a document's flags deny is an error, so
  // "unsupported capabilities are explicit" holds in both directions.
  const caps = doc.capabilities ?? {};
  if (sawMoria && caps.microtonal === false) err(errors, 'capabilities.microtonal', 'false but moria-typed pitches are present');
  if ((tl.ison?.length ?? 0) > 0 && caps.ison === false) err(errors, 'capabilities.ison', 'false but timeline.ison is populated');
  if ((tl.tuningChanges?.length ?? 0) > 0 && caps.tuningChanges === false) err(errors, 'capabilities.tuningChanges', 'false but timeline.tuningChanges is populated');
  if ((tl.checkpoints?.length ?? 0) > 0 && caps.checkpoints === false) err(errors, 'capabilities.checkpoints', 'false but timeline.checkpoints is populated');

  return { ok: errors.length === 0, errors };
}
