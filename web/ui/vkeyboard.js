// VKeyboard — maps QWERTY keys to scale cells and drives the AudioEngine.
//
// Default layout (rebuilt from cells on every grid change):
//
//   Upper row  q w e r t y u i o p  → enabled non-degree cells, moria [-36, 108)
//   Home row   a s d f g h j k l   → octave-0 degrees Ni..Zo + octave+1 Ni, Pa
//   Bottom row z x c v b n m       → octave-1 degrees Ni..Zo
//
// "Octave N" means moria in [N*72, (N+1)*72).

const HOME_KEYS = ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'];
const BOT_KEYS  = ['z', 'x', 'c', 'v', 'b', 'n', 'm'];
const TOP_KEYS  = ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'];

const DEGREE_ORDER = ['Ni', 'Pa', 'Vou', 'Ga', 'Di', 'Ke', 'Zo'];

export class VKeyboard {
  /**
   * @param {import('../audio/audio_engine.js').AudioEngine} engine
   * @param {object|null} ladderRef - ScaleLadder instance (may be null)
   */
  constructor(engine, ladderRef) {
    this._engine  = engine;
    this._ladder  = ladderRef;
    this._keyMap  = new Map(); // key string → moria
    this._held    = new Set(); // keys currently depressed

    window.addEventListener('keydown', e => this._onKeyDown(e));
    window.addEventListener('keyup',   e => this._onKeyUp(e));
  }

  // Rebuild key→moria mapping from the current grid cells array.
  // Call whenever the grid (or its reference) changes.
  rebuildKeyMap(cells) {
    this._keyMap.clear();

    // Index enabled degree cells by "octave:degree".
    const byOctDeg = new Map(); // `${oct}:${degree}` → moria
    const nonDeg   = [];

    for (const c of cells) {
      if (!c.enabled) continue;
      if (c.degree !== null) {
        const oct = Math.floor(c.moria / 72);
        byOctDeg.set(`${oct}:${c.degree}`, c.moria);
      } else {
        nonDeg.push(c.moria);
      }
    }

    // Home row — octave-0 degrees, then octave+1 Ni and Pa to fill remaining keys.
    let hi = 0;
    for (const deg of DEGREE_ORDER) {
      if (hi >= HOME_KEYS.length) break;
      const m = byOctDeg.get(`0:${deg}`);
      if (m !== undefined) this._keyMap.set(HOME_KEYS[hi], m);
      hi++;
    }
    if (hi < HOME_KEYS.length) {
      const ni1 = byOctDeg.get('1:Ni');
      if (ni1 !== undefined) { this._keyMap.set(HOME_KEYS[hi], ni1); hi++; }
    }
    if (hi < HOME_KEYS.length) {
      const pa1 = byOctDeg.get('1:Pa');
      if (pa1 !== undefined) this._keyMap.set(HOME_KEYS[hi], pa1);
    }

    // Bottom row — octave-1 degrees.
    for (let i = 0; i < DEGREE_ORDER.length && i < BOT_KEYS.length; i++) {
      const m = byOctDeg.get(`-1:${DEGREE_ORDER[i]}`);
      if (m !== undefined) this._keyMap.set(BOT_KEYS[i], m);
    }

    // Upper row — enabled non-degree cells in [-36, 108), lowest first.
    const chromatic = nonDeg
      .filter(m => m >= -36 && m < 108)
      .sort((a, b) => a - b);
    for (let i = 0; i < TOP_KEYS.length && i < chromatic.length; i++) {
      this._keyMap.set(TOP_KEYS[i], chromatic[i]);
    }
  }

  async _onKeyDown(e) {
    if (e.repeat || e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

    const key   = e.key.toLowerCase();
    const moria = this._keyMap.get(key);
    if (moria === undefined) return;
    if (this._held.has(key)) return;
    this._held.add(key);

    if (!this._engine.ready) await this._engine.init();
    this._engine.noteOn(moria);
    this._ladder?.setActiveCells(this._heldMoria());
  }

  _onKeyUp(e) {
    const key   = e.key.toLowerCase();
    const moria = this._keyMap.get(key);
    if (moria === undefined) return;
    this._held.delete(key);
    this._engine.noteOff(moria);
    this._ladder?.setActiveCells(this._heldMoria());
  }

  _heldMoria() {
    const out = new Set();
    for (const key of this._held) {
      const m = this._keyMap.get(key);
      if (m !== undefined) out.add(m);
    }
    return out;
  }
}
