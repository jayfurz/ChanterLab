// ScaleLadder — canvas-based scale degree visualizer.
// Paints cells top-to-bottom: high moria at top.

// degree field in JSON is either a string variant name or null.
const DEGREE_INDEX = { Ni: 0, Pa: 1, Vou: 2, Ga: 3, Di: 4, Ke: 5, Zo: 6 };
const DEGREE_H = 26;
const NONDEG_H = 12;

// Pthora region colors (cycled by region_idx).
const REGION_COLORS = [
  null,               // region 0 = base, no tint
  'rgba(83,192,240,0.12)',
  'rgba(233,69,96,0.12)',
  'rgba(80,200,120,0.12)',
  'rgba(200,160,60,0.12)',
  'rgba(160,80,200,0.12)',
];

export class ScaleLadder {
  constructor(canvas, app) {
    this.canvas = canvas;
    this.app = app;
    this._cells = [];
    this._rowMap = []; // [{cell, y, h}] top-to-bottom
    this._activeCells = new Set(); // moria values of currently playing cells

    this._ro = new ResizeObserver(() => this._onResize());
    this._ro.observe(canvas);

    canvas.addEventListener('click', e => this._onClick(e));
    canvas.addEventListener('contextmenu', e => this._onRightClick(e));
    canvas.addEventListener('dragover', e => this._onDragOver(e));
    canvas.addEventListener('drop', e => this._onDrop(e));
  }

  /** Highlight cells that are currently playing (from keyboard). */
  setActiveCells(moriaSet) {
    this._activeCells = moriaSet;
    this._paint();
  }

  /** Re-read cells from WASM and repaint. */
  refresh() {
    const json = this.app.grid.cellsJson();
    this._cells = JSON.parse(json);
    this._paint();
  }

  _onResize() {
    const { width, height } = this.canvas.getBoundingClientRect();
    this.canvas.width = width * devicePixelRatio;
    this.canvas.height = height * devicePixelRatio;
    this._paint();
  }

  _paint() {
    const cells = this._cells;
    if (!cells.length) return;

    const dpr = devicePixelRatio;
    const W = this.canvas.width;
    const H = this.canvas.height;
    const ctx = this.canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    ctx.scale(dpr, dpr);

    const cssW = W / dpr;
    const cssH = H / dpr;

    // Build row map top-to-bottom (cells are sorted low→high by moria from
    // the engine; we reverse so the highest moria is at the top of the canvas).
    const reversed = [...cells].reverse();

    // Total natural height to determine if we need to scroll (we don't scroll
    // yet — just fit into the available height by scaling row heights).
    const naturalH = reversed.reduce((s, c) => s + (c.degree !== null ? DEGREE_H : NONDEG_H), 0);
    const scale = Math.min(1, cssH / naturalH);

    this._rowMap = [];
    let y = 0;
    for (const cell of reversed) {
      const h = Math.max(2, (cell.degree !== null ? DEGREE_H : NONDEG_H) * scale);
      this._rowMap.push({ cell, y, h });
      y += h;
    }

    // Paint rows.
    for (const { cell, y: ry, h } of this._rowMap) {
      const isDeg = cell.degree !== null;

      // Region background tint.
      const regionColor = REGION_COLORS[cell.region_idx % REGION_COLORS.length];
      if (regionColor) {
        ctx.fillStyle = regionColor;
        ctx.fillRect(0, ry, cssW, h);
      }

      // Cell fill.
      const isActive = this._activeCells.has(cell.moria);
      if (isActive) {
        ctx.fillStyle = '#2a5f9f';
        ctx.fillRect(1, ry + 0.5, cssW - 2, h - 1);
      } else if (isDeg && cell.enabled) {
        ctx.fillStyle = '#1e3a5f';
        ctx.fillRect(1, ry + 0.5, cssW - 2, h - 1);
      } else if (isDeg) {
        ctx.fillStyle = '#12243a';
        ctx.fillRect(1, ry + 0.5, cssW - 2, h - 1);
      }

      // Separator line.
      ctx.strokeStyle = isDeg ? '#334' : '#222';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(0, ry + h);
      ctx.lineTo(cssW, ry + h);
      ctx.stroke();

      if (!isDeg) continue;

      // Degree label.
      const name = cell.degree ?? '?';
      ctx.font = `${Math.round(11 * scale)}px 'Segoe UI', system-ui, sans-serif`;
      ctx.fillStyle = isActive ? '#ffffff' : (cell.enabled ? '#53c0f0' : '#445');
      ctx.fillText(name, 6, ry + h / 2 + 4 * scale);

      // Hz label.
      const hz = this.app.grid.moriaToHz(cell.moria + cell.accidental);
      ctx.font = `${Math.round(9 * scale)}px monospace`;
      ctx.fillStyle = cell.enabled ? '#8ab' : '#334';
      const hzStr = hz.toFixed(1);
      const tw = ctx.measureText(hzStr).width;
      ctx.fillText(hzStr, cssW - tw - 4, ry + h / 2 + 4 * scale);

      // Accidental badge.
      if (cell.accidental !== 0) {
        const sign = cell.accidental > 0 ? '+' : '';
        const badge = `${sign}${cell.accidental}`;
        ctx.font = `bold ${Math.round(9 * scale)}px monospace`;
        ctx.fillStyle = '#e94560';
        const bw = ctx.measureText(badge).width;
        ctx.fillText(badge, cssW / 2 - bw / 2, ry + h / 2 + 4 * scale);
      }
    }

    this._paintIntervals(ctx, cssW, scale);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  /**
   * Draw interval labels (in moria) between consecutive degree cells.
   *
   * Each label sits in the visual gap between two degree rows. The width of
   * a horizontal bar is proportional to the interval size (reference: 24 moria
   * = full ladder width). Color: red for narrow intervals (≤ 6 moria, i.e.
   * chromatic near-semitones), yellow for wider steps.
   *
   * Uses effective_moria (moria + accidental) so the display reacts to
   * accidentals applied to any degree.
   */
  _paintIntervals(ctx, cssW, scale) {
    const degRows = this._rowMap.filter(r => r.cell.degree !== null);

    for (let i = 0; i < degRows.length - 1; i++) {
      const upper = degRows[i];      // smaller canvas y → higher moria
      const lower = degRows[i + 1];

      const upperEff = upper.cell.moria + upper.cell.accidental;
      const lowerEff = lower.cell.moria + lower.cell.accidental;
      const interval = upperEff - lowerEff;
      if (interval <= 0) continue;

      const gapTop    = upper.y + upper.h;
      const gapBottom = lower.y;
      const gapH      = gapBottom - gapTop;
      if (gapH < 3) continue;  // no room

      const midY  = gapTop + gapH / 2;
      const color = interval <= 6 ? '#e94560' : '#f0c040';

      // Horizontal bar: width ∝ interval (24 moria ≈ full width).
      const barW = Math.min((interval / 24) * cssW * 0.82, cssW * 0.82);
      const barH = Math.max(1.5, Math.min(gapH * 0.25, 5));
      const barX = (cssW - barW) / 2;
      ctx.fillStyle = color + '50';
      ctx.fillRect(barX, midY - barH / 2, barW, barH);

      // Interval number, centered in the gap.
      if (gapH >= 7) {
        const fontSize = Math.max(7, Math.round(9 * scale));
        ctx.font = `bold ${fontSize}px monospace`;
        ctx.fillStyle = color;
        const label = String(interval);
        const tw = ctx.measureText(label).width;
        ctx.fillText(label, cssW / 2 - tw / 2, midY + fontSize * 0.38);
      }
    }
  }

  /** Return the cell hit by a CSS-space y coordinate, or null. */
  _hitTest(cssY) {
    for (const row of this._rowMap) {
      if (cssY >= row.y && cssY < row.y + row.h) return row.cell;
    }
    return null;
  }

  _cssY(evt) {
    const rect = this.canvas.getBoundingClientRect();
    return evt.clientY - rect.top;
  }

  _onClick(e) {
    const cell = this._hitTest(this._cssY(e));
    if (!cell || cell.degree === null) return;
    this.app.grid.toggleCell(cell.moria);
    this.refresh();
  }

  _onRightClick(e) {
    e.preventDefault();
    const cell = this._hitTest(this._cssY(e));
    if (!cell || cell.degree === null) return;
    this.app.showAccidentalPopup(cell, e.clientX, e.clientY);
  }

  _onDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  }

  _onDrop(e) {
    e.preventDefault();
    const cell = this._hitTest(this._cssY(e));
    if (!cell) return;

    let data;
    try { data = JSON.parse(e.dataTransfer.getData('application/json')); }
    catch { return; }

    if (data.type === 'pthora') {
      this.app.grid.applyPthora(cell.moria, data.genus, data.degree);
      this.refresh();
    } else if (data.type === 'shading') {
      if (cell.degree === null) return;
      this.app.grid.applyShading(cell.moria, data.shading);
      this.refresh();
    }
  }
}
