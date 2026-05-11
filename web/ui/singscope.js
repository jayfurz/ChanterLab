// Singscope — scrolling pitch history canvas aligned with the scale ladder.
// Y axis: moria values, row-for-row with ScaleLadder's _rowMap.
// X axis: time, scrolling right-to-left; newest point on a configurable anchor.

const HISTORY_LEN = 600; // number of pitch points to retain
const BG_COLOR    = '#111';
const TRACE_START_MARK_W = 2;
const TRACE_STYLES = {
  reference: {
    snap: '#63b8ff',
    rawRgb: '125,190,255',
    rawAlphaScale: 0.62,
    snapWidth: 1.25,
    rawWidth: 1.25,
    marker: false,
  },
  live: {
    snap: '#50c850',
    rawRgb: '255,200,0',
    rawAlphaScale: 1,
    snapWidth: 1.5,
    rawWidth: 1.5,
    marker: true,
  },
};

function blankPoint() {
  return { atMs: null, moria: null, snapMoria: null, confidence: 0, gateOpen: false };
}

function createTraceState() {
  return {
    buf: new Array(HISTORY_LEN).fill(null).map(blankPoint),
    head: 0,
    count: 0,
  };
}

function cellAxisMoria(cell) {
  return cell.moria;
}

function performanceNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

export class Singscope {
  constructor(canvas) {
    this._canvas  = canvas;
    this._ctx     = canvas.getContext('2d');
    this._rowMap  = []; // [{cell, y, h}] — same structure as ScaleLadder._rowMap
    this._zoomMode = false;

    // Separate ring buffers keep reference/media playback from corrupting the
    // live mic trace when a chanter sings along.
    // Each entry: { atMs, moria, snapMoria, confidence, gateOpen }
    this._traces = {
      reference: createTraceState(),
      live: createTraceState(),
    };

    this._rafId   = null;
    this._dirty   = true;
    this._traceAnchorRatio = 1;
    this._tracePxPerSecond = null;

    this._ro = new ResizeObserver(() => this._onResize());
    this._ro.observe(canvas);
  }

  // ── Public API ──────────────────────────────────────────────────────────────

  /** Called on every live mic pitch event from VoiceWorklet (~60 Hz). */
  pushPitch(msg, options = {}) {
    const layer = options.layer === 'reference' ? 'reference' : 'live';
    this._pushPitchToLayer(layer, msg);
  }

  /** Called for imported/recorded playback reference pitch events. */
  pushReferencePitch(msg) {
    this._pushPitchToLayer('reference', msg);
  }

  clear(layer = 'all') {
    if (layer === 'live' || layer === 'reference') {
      this._resetTrace(layer);
    } else {
      this._resetTrace('live');
      this._resetTrace('reference');
    }
    this._dirty = true;
  }

  /** Called when the scale ladder row layout changes (on grid refresh). */
  setRowMap(rowMap) {
    this._rowMap = rowMap;
    this._dirty  = true;
  }

  /** Enable/disable zoom-mode grid lines aligned with the ladder. */
  setZoomMode(enabled) {
    this._zoomMode = !!enabled;
    this._dirty = true;
  }

  setTraceAnchorRatio(ratio) {
    this._traceAnchorRatio = Number.isFinite(ratio)
      ? Math.max(0, Math.min(1, ratio))
      : 1;
    this._dirty = true;
  }

  setTraceTiming({ anchorRatio = this._traceAnchorRatio, pxPerSecond = this._tracePxPerSecond } = {}) {
    this._traceAnchorRatio = Number.isFinite(anchorRatio)
      ? Math.max(0, Math.min(1, anchorRatio))
      : 1;
    this._tracePxPerSecond = Number.isFinite(pxPerSecond) && pxPerSecond > 0
      ? pxPerSecond
      : null;
    this._dirty = true;
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

  _traceState(layer) {
    return this._traces[layer] ?? this._traces.live;
  }

  _pushPitchToLayer(layer, msg) {
    const trace = this._traceState(layer);
    const gateOpen = !!msg.gate_open;
    const cellId   = (typeof msg.cell_id === 'number') ? msg.cell_id : -1;
    const hasSnap  = Number.isFinite(cellId) && cellId !== -1;
    const rawMoria = (typeof msg.raw_moria === 'number' && Number.isFinite(msg.raw_moria))
      ? msg.raw_moria
      : null;
    const snapMoria = (typeof msg.snap_moria === 'number' && Number.isFinite(msg.snap_moria))
      ? msg.snap_moria
      : cellId;
    const moria    = gateOpen ? (rawMoria ?? (hasSnap ? cellId : null)) : null;
    const snap     = (gateOpen && hasSnap) ? snapMoria : null;
    const conf     = (typeof msg.confidence === 'number') ? msg.confidence : 0;

    trace.buf[trace.head] = {
      atMs: performanceNow(),
      moria,
      snapMoria: snap,
      confidence: conf,
      gateOpen,
    };
    trace.head = (trace.head + 1) % HISTORY_LEN;
    if (trace.count < HISTORY_LEN) trace.count++;
    this._dirty = true;
  }

  _resetTrace(layer) {
    const trace = this._traceState(layer);
    for (let i = 0; i < HISTORY_LEN; i++) {
      trace.buf[i] = blankPoint();
    }
    trace.head = 0;
    trace.count = 0;
  }

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
      if (cellAxisMoria(row.cell) === moria) return this._rowCenterY(row, cssH);
    }

    if (interpolate) {
      const top = this._rowMap[0];
      const bottom = this._rowMap[this._rowMap.length - 1];

      if (moria >= cellAxisMoria(top.cell)) return this._rowCenterY(top, cssH);
      if (moria <= cellAxisMoria(bottom.cell)) return this._rowCenterY(bottom, cssH);

      for (let i = 0; i < this._rowMap.length - 1; i++) {
        const upper = this._rowMap[i];
        const lower = this._rowMap[i + 1];
        const upperMoria = cellAxisMoria(upper.cell);
        const lowerMoria = cellAxisMoria(lower.cell);
        if (upperMoria >= moria && moria >= lowerMoria) {
          const upperY = this._rowCenterY(upper, cssH);
          const lowerY = this._rowCenterY(lower, cssH);
          const span = upperMoria - lowerMoria;
          const ratio = span > 0 ? (upperMoria - moria) / span : 0;
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
      const d = Math.abs(cellAxisMoria(row.cell) - moria);
      if (d < bestDist) { bestDist = d; best = row; }
    }
    return best ? this._rowCenterY(best, cssH) : null;
  }

  /** Return an ordered array of the most recent `count` points (oldest first). */
  _orderedPoints(layer) {
    const trace = this._traceState(layer);
    const n   = Math.min(trace.count, HISTORY_LEN);
    const out = new Array(n);
    // _head points to the slot that will be overwritten next, so the oldest
    // live slot is (_head - n + HISTORY_LEN) % HISTORY_LEN.
    const start = (trace.head - n + HISTORY_LEN) % HISTORY_LEN;
    for (let i = 0; i < n; i++) {
      out[i] = trace.buf[(start + i) % HISTORY_LEN];
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

    // 2b. Zoom-mode grid lines every 2 moria.
    if (this._zoomMode && this._rowMap.length) {
      const moriaVals = this._rowMap.map(r => r.cell.moria);
      const minMoria = Math.min(...moriaVals);
      const maxMoria = Math.max(...moriaVals);
      const firstGrid = Math.ceil(minMoria / 2) * 2;
      ctx.strokeStyle = 'rgba(255,255,255,0.15)';
      ctx.lineWidth = 1;
      for (let m = firstGrid; m <= maxMoria; m += 2) {
        const y = this._moriaToY(m, cssH, true);
        if (y === null) continue;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(cssW, y);
        ctx.stroke();
      }
    }

    const referencePoints = this._orderedPoints('reference');
    const livePoints = this._orderedPoints('live');
    if (referencePoints.length === 0 && livePoints.length === 0) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      return;
    }

    const traceAnchorX = cssW * this._traceAnchorRatio;
    const latestReferenceAt = referencePoints.length
      ? referencePoints[referencePoints.length - 1]?.atMs
      : 0;
    const latestLiveAt = livePoints.length
      ? livePoints[livePoints.length - 1]?.atMs
      : 0;
    const latestAtMs = Math.max(
      latestReferenceAt ?? 0,
      latestLiveAt ?? 0,
      performanceNow(),
    );

    this._paintTraceLayer(ctx, referencePoints, traceAnchorX, latestAtMs, cssW, cssH, TRACE_STYLES.reference);
    this._paintTraceLayer(ctx, livePoints, traceAnchorX, latestAtMs, cssW, cssH, TRACE_STYLES.live);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  _paintTraceLayer(ctx, points, traceAnchorX, latestAtMs, cssW, cssH, style) {
    const N = points.length;
    if (N === 0) return;

    const xStep = cssW / Math.max(HISTORY_LEN - 1, 1);
    const sampleStartX = traceAnchorX - (N - 1) * xStep;
    const xOf = i => {
      const pt = points[i];
      if (this._tracePxPerSecond && Number.isFinite(pt?.atMs)) {
        return traceAnchorX - ((latestAtMs - pt.atMs) / 1000) * this._tracePxPerSecond;
      }
      return sampleStartX + i * xStep;
    };

    // Snap polyline, stepped horizontally.
    // Draw horizontal/vertical steps only when snapMoria !== null.
    ctx.lineWidth   = style.snapWidth;
    ctx.strokeStyle = style.snap;
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

    // Raw pitch polyline, confidence-modulated alpha.
    ctx.lineWidth = style.rawWidth;

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
      const alpha = Math.max(0.08, Math.min(1, conf * style.rawAlphaScale));
      ctx.strokeStyle = `rgba(${style.rawRgb},${alpha.toFixed(3)})`;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }

    if (style.marker) this._paintTraceStartMarker(ctx, points[N - 1], traceAnchorX, cssH);
  }

  _paintTraceStartMarker(ctx, latest, traceAnchorX, cssH) {
    if (!latest?.gateOpen || latest.moria === null) return;
    const y = this._moriaToY(latest.moria, cssH, true);
    if (y === null) return;

    const alpha = Math.max(0.35, Math.min(1, latest.confidence || 0.75));
    const x0 = Math.max(0, traceAnchorX - TRACE_START_MARK_W);
    const x1 = Math.max(0, traceAnchorX);
    ctx.save();
    ctx.strokeStyle = `rgba(255,55,55,${alpha.toFixed(3)})`;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    ctx.stroke();
    ctx.restore();
  }
}
