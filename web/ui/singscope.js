// Singscope — scrolling pitch history canvas aligned with the scale ladder.
// Y axis: moria values, row-for-row with ScaleLadder's _rowMap.
// X axis: time, scrolling right-to-left; newest point on the right edge.

const HISTORY_LEN = 600; // number of pitch points to retain
const BG_COLOR    = '#111';

export class Singscope {
  constructor(canvas) {
    this._canvas  = canvas;
    this._ctx     = canvas.getContext('2d');
    this._rowMap  = []; // [{cell, y, h}] — same structure as ScaleLadder._rowMap

    // Ring buffer of pitch points.
    // Each entry: { moria: number|null, snapMoria: number|null, confidence: number, gateOpen: bool }
    this._buf     = new Array(HISTORY_LEN).fill(null).map(() => ({
      moria: null, snapMoria: null, confidence: 0, gateOpen: false,
    }));
    this._head    = 0; // index of the next write slot (oldest data)
    this._count   = 0; // how many valid entries have been written

    this._rafId   = null;
    this._dirty   = true;

    this._ro = new ResizeObserver(() => this._onResize());
    this._ro.observe(canvas);
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /** Called on every pitch event from VoiceWorklet (~60 Hz). */
  pushPitch(msg) {
    const gateOpen = !!msg.gate_open;
    const cellId   = (typeof msg.cell_id === 'number') ? msg.cell_id : -1;
    const hasSnap  = Number.isFinite(cellId) && cellId !== -1;
    const rawMoria = (typeof msg.raw_moria === 'number' && Number.isFinite(msg.raw_moria))
      ? msg.raw_moria
      : null;
    const moria    = gateOpen ? (rawMoria ?? (hasSnap ? cellId : null)) : null;
    const snap     = (gateOpen && hasSnap) ? cellId : null;
    const conf     = (typeof msg.confidence === 'number') ? msg.confidence : 0;

    this._buf[this._head] = { moria, snapMoria: snap, confidence: conf, gateOpen };
    this._head = (this._head + 1) % HISTORY_LEN;
    if (this._count < HISTORY_LEN) this._count++;
    this._dirty = true;
  }

  /** Called when the scale ladder row layout changes (on grid refresh). */
  setRowMap(rowMap) {
    this._rowMap = rowMap;
    this._dirty  = true;
  }

  /** Start the animation loop. */
  start() {
    if (this._rafId !== null) return;
    const loop = () => {
      this._rafId = requestAnimationFrame(loop);
      if (this._dirty) {
        this._paint();
        this._dirty = false;
      }
    };
    this._rafId = requestAnimationFrame(loop);
  }

  /** Stop the animation loop. */
  stop() {
    if (this._rafId !== null) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
  }

  // ── Internal ────────────────────────────────────────────────────────────────

  _onResize() {
    const { width, height } = this._canvas.getBoundingClientRect();
    this._canvas.width  = Math.max(1, Math.round(width  * devicePixelRatio));
    this._canvas.height = Math.max(1, Math.round(height * devicePixelRatio));
    this._dirty = true;
  }

  /**
   * Map a moria value to a CSS-space Y coordinate (vertical centre of that row).
   * Returns null if the rowMap is empty or no matching row is found.
   */
  _scaledRowExtent(cssH) {
    if (!this._rowMap.length) return 1;
    const last = this._rowMap[this._rowMap.length - 1];
    const ladderH = last.y + last.h;
    return ladderH > 0 ? cssH / ladderH : 1;
  }

  _rowCenterY(row, cssH) {
    return (row.y + row.h / 2) * this._scaledRowExtent(cssH);
  }

  _moriaToY(moria, cssH, interpolate = false) {
    if (!this._rowMap.length) return null;

    // Exact match first.
    for (const row of this._rowMap) {
      if (row.cell.moria === moria) return this._rowCenterY(row, cssH);
    }

    if (interpolate) {
      const top = this._rowMap[0];
      const bottom = this._rowMap[this._rowMap.length - 1];

      if (moria >= top.cell.moria) return this._rowCenterY(top, cssH);
      if (moria <= bottom.cell.moria) return this._rowCenterY(bottom, cssH);

      for (let i = 0; i < this._rowMap.length - 1; i++) {
        const upper = this._rowMap[i];
        const lower = this._rowMap[i + 1];
        if (upper.cell.moria >= moria && moria >= lower.cell.moria) {
          const upperY = this._rowCenterY(upper, cssH);
          const lowerY = this._rowCenterY(lower, cssH);
          const span = upper.cell.moria - lower.cell.moria;
          const ratio = span > 0 ? (upper.cell.moria - moria) / span : 0;
          return upperY + (lowerY - upperY) * ratio;
        }
      }
    }

    // Nearest-moria fallback: binary search for the row whose moria is closest.
    // rowMap is ordered high-moria (top) → low-moria (bottom), so moria
    // values decrease as index increases.
    let best     = null;
    let bestDist = Infinity;
    for (const row of this._rowMap) {
      const d = Math.abs(row.cell.moria - moria);
      if (d < bestDist) { bestDist = d; best = row; }
    }
    return best ? this._rowCenterY(best, cssH) : null;
  }

  /** Return an ordered array of the most recent `count` points (oldest first). */
  _orderedPoints() {
    const n   = Math.min(this._count, HISTORY_LEN);
    const out = new Array(n);
    // _head points to the slot that will be overwritten next, so the oldest
    // live slot is (_head - n + HISTORY_LEN) % HISTORY_LEN.
    const start = (this._head - n + HISTORY_LEN) % HISTORY_LEN;
    for (let i = 0; i < n; i++) {
      out[i] = this._buf[(start + i) % HISTORY_LEN];
    }
    return out;
  }

  _paint() {
    const canvas = this._canvas;
    const ctx    = this._ctx;
    const dpr    = devicePixelRatio;
    const W      = canvas.width;
    const H      = canvas.height;

    if (W === 0 || H === 0) return;

    // Work in CSS pixels; scale once at the end.
    const cssW = W / dpr;
    const cssH = H / dpr;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 1. Background.
    ctx.fillStyle = BG_COLOR;
    ctx.fillRect(0, 0, cssW, cssH);

    if (!this._rowMap.length) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      return;
    }

    // 2. Faint bands for enabled-cell rows.
    ctx.fillStyle = 'rgba(255,255,255,0.04)';
    const rowScale = this._scaledRowExtent(cssH);
    for (const row of this._rowMap) {
      if (row.cell.enabled) {
        ctx.fillRect(0, row.y * rowScale, cssW, row.h * rowScale);
      }
    }

    const points = this._orderedPoints();
    const N      = points.length;
    if (N === 0) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      return;
    }

    // X spread: distribute N points across cssW so the rightmost point sits at
    // the right edge. Each step is cssW / (HISTORY_LEN - 1) so the spacing is
    // constant regardless of how many points have accumulated.
    const xStep = cssW / Math.max(HISTORY_LEN - 1, 1);
    // Index of the leftmost x position for the oldest point in `points`.
    const startX = (HISTORY_LEN - N) * xStep;

    const xOf = i => startX + i * xStep;

    // 3. Snap polyline (green, stepped horizontally).
    // Draw horizontal/vertical steps only when snapMoria !== null.
    ctx.lineWidth   = 1.5;
    ctx.strokeStyle = '#50c850';
    ctx.beginPath();
    let snapInPath = false;
    let prevSnapY  = null;

    for (let i = 0; i < N; i++) {
      const pt = points[i];
      if (pt.snapMoria === null) {
        snapInPath = false;
        prevSnapY  = null;
        continue;
      }
      const y = this._moriaToY(pt.snapMoria, cssH);
      if (y === null) continue;

      const x = xOf(i);
      if (!snapInPath || prevSnapY === null) {
        ctx.moveTo(x, y);
        snapInPath = true;
      } else {
        // Stepped: draw vertical then horizontal.
        if (y !== prevSnapY) {
          ctx.lineTo(x, prevSnapY); // horizontal to this x at old y
          ctx.lineTo(x, y);         // then drop/rise to new y
        } else {
          ctx.lineTo(x, y);
        }
      }
      prevSnapY = y;
    }
    ctx.stroke();

    // 4. Raw pitch polyline (amber, confidence-modulated alpha).
    ctx.lineWidth = 1.5;

    for (let i = 1; i < N; i++) {
      const prev = points[i - 1];
      const curr = points[i];

      // Break at gate-closed or missing pitch.
      if (!prev.gateOpen || !curr.gateOpen || prev.moria === null || curr.moria === null) continue;

      const y0 = this._moriaToY(prev.moria, cssH, true);
      const y1 = this._moriaToY(curr.moria, cssH, true);
      if (y0 === null || y1 === null) continue;

      const x0 = xOf(i - 1);
      const x1 = xOf(i);

      // Average confidence for the segment.
      const conf = (prev.confidence + curr.confidence) / 2;
      ctx.strokeStyle = `rgba(255,200,0,${conf.toFixed(3)})`;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }

    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }
}
