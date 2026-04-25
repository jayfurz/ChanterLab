// ScaleLadder — canvas-based scale degree visualizer.
// Paints cells top-to-bottom: high moria at top.

// degree field in JSON is either a string variant name or null.
const DEGREE_INDEX = { Ni: 0, Pa: 1, Vou: 2, Ga: 3, Di: 4, Ke: 5, Zo: 6 };
const DEGREE_H = 26;
const NONDEG_H = 12;
const CONCERT_NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
const DEGREE_ACCENTS = ['#65d6ff', '#6fc7ff', '#74d3b7', '#8bc2ff', '#c3a5ff', '#ffca6f', '#ff8ea0'];

// Pthora region colors (cycled by region_idx).
const REGION_COLORS = [
  null,               // region 0 = base, no tint
  'rgba(83,192,240,0.12)',
  'rgba(233,69,96,0.12)',
  'rgba(80,200,120,0.12)',
  'rgba(200,160,60,0.12)',
  'rgba(160,80,200,0.12)',
];

function concertPitchParts(hz) {
  if (!Number.isFinite(hz) || hz <= 0) return null;

  const exactMidi = 69 + 12 * Math.log2(hz / 440);
  let midi = Math.ceil(exactMidi - 0.5);
  let cents = Math.round((exactMidi - midi) * 100);

  if (cents <= -50) {
    midi -= 1;
    cents += 100;
  } else if (cents > 50) {
    midi += 1;
    cents -= 100;
  }

  const noteName = CONCERT_NOTE_NAMES[((midi % 12) + 12) % 12];
  const octave = Math.floor(midi / 12) - 1;
  const sign = cents >= 0 ? '+' : '';
  return {
    note: `${noteName}${octave}`,
    cents: `${sign}${cents}c`,
  };
}

function roundedRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h - radius);
  ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
  ctx.lineTo(x + radius, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.closePath();
}

function fillRoundedRect(ctx, x, y, w, h, r) {
  roundedRect(ctx, x, y, w, h, r);
  ctx.fill();
}

export class ScaleLadder {
  constructor(canvas, app) {
    this.canvas = canvas;
    this.app = app;
    this._cells = [];
    this._rowMap = []; // [{cell, y, h}] top-to-bottom
    this._activeCells = new Set(); // moria values of currently playing cells
    // Voice pitch detection state.
    this._detectedCell    = null; // moria or null
    this._detectedNeighbor = null; // moria or null
    this._detectedNeighborVel = 0; // 0..1

    this._ro = new ResizeObserver(() => this._onResize());
    this._ro.observe(canvas);

    // Drop hover preview state.
    this._hoverCell = null;

    canvas.addEventListener('click', e => this._onClick(e));
    canvas.addEventListener('contextmenu', e => this._onRightClick(e));
    canvas.addEventListener('chanterlab:palette-drop', e => this._onPaletteDrop(e));
    canvas.addEventListener('chanterlab:palette-hover', e => this._onPaletteHover(e));

    // Long-press → accidental popup. Parallel path to right-click, not gated
    // by pointerType so trackpad users can use whichever feels natural.
    canvas.addEventListener('pointerdown', e => this._onPointerDown(e));
  }

  /** Highlight cells that are currently playing (from keyboard). */
  setActiveCells(moriaSet) {
    this._activeCells = moriaSet;
    this._paint();
  }

  /**
   * Show the voice-detected pitch on the ladder.
   * moria / neighborMoria: cell moria values, or null to clear.
   * neighborVel: proportional closeness of the neighbor (0..1).
   */
  setDetectedCell(moria, neighborMoria, neighborVel) {
    this._detectedCell     = moria;
    this._detectedNeighbor = neighborMoria;
    this._detectedNeighborVel = neighborVel ?? 0;
    this._paint();
  }

  /** Expose the row layout so other components (e.g. Singscope) can align. */
  get rowMap() { return this._rowMap; }

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
    this.app.singscope?.setRowMap(this._rowMap);
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
    ctx.fillStyle = '#111a31';
    ctx.fillRect(0, 0, cssW, cssH);

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
      const degreeIdx = isDeg ? DEGREE_INDEX[cell.degree] ?? 0 : 0;
      const accent = DEGREE_ACCENTS[degreeIdx % DEGREE_ACCENTS.length];

      // Region background tint.
      const regionColor = REGION_COLORS[cell.region_idx % REGION_COLORS.length];
      if (regionColor) {
        ctx.fillStyle = regionColor;
        ctx.fillRect(0, ry, cssW, h);
      }

      // Cell fill.
      const isActive   = this._activeCells.has(cell.moria);
      const isDetected = cell.moria === this._detectedCell;
      const isNeighbor = cell.moria === this._detectedNeighbor;
      const rowX = 1;
      const rowY = ry + 0.75;
      const rowW = cssW - 2;
      const rowH = Math.max(1, h - 1.5);
      if (isActive) {
        const grad = ctx.createLinearGradient(rowX, 0, rowX + rowW, 0);
        grad.addColorStop(0, '#2e7abe');
        grad.addColorStop(1, '#214b7f');
        ctx.fillStyle = grad;
        fillRoundedRect(ctx, rowX, rowY, rowW, rowH, 3);
      } else if (isDetected) {
        const grad = ctx.createLinearGradient(rowX, 0, rowX + rowW, 0);
        grad.addColorStop(0, '#9a6415');
        grad.addColorStop(1, '#623c08');
        ctx.fillStyle = grad;
        fillRoundedRect(ctx, rowX, rowY, rowW, rowH, 3);
      } else if (isNeighbor && this._detectedNeighborVel > 0) {
        // Half-lit neighbor: amber tinted proportional to velocity.
        const alpha = Math.round(this._detectedNeighborVel * 180).toString(16).padStart(2, '0');
        ctx.fillStyle = `#8a5200${alpha}`;
        fillRoundedRect(ctx, rowX, rowY, rowW, rowH, 3);
      } else if (isDeg && cell.enabled) {
        const grad = ctx.createLinearGradient(rowX, 0, rowX + rowW, 0);
        grad.addColorStop(0, '#214a78');
        grad.addColorStop(0.65, '#1c3a62');
        grad.addColorStop(1, '#162c4f');
        ctx.fillStyle = grad;
        fillRoundedRect(ctx, rowX, rowY, rowW, rowH, 3);
      } else if (isDeg) {
        ctx.fillStyle = '#12243a';
        fillRoundedRect(ctx, rowX, rowY, rowW, rowH, 3);
      }

      if (isDeg) {
        ctx.fillStyle = cell.enabled ? accent : '#33445a';
        fillRoundedRect(ctx, rowX + 1, rowY + 2, 3, Math.max(1, rowH - 4), 2);

        if (cell.enabled) {
          ctx.fillStyle = 'rgba(255,255,255,0.055)';
          ctx.fillRect(rowX + 5, rowY + 1, rowW - 7, Math.max(1, rowH * 0.42));
        }
      }

      // Hover preview border during palette drag.
      if (this._hoverCell && this._hoverCell.moria === cell.moria) {
        ctx.strokeStyle = '#53c0f0';
        ctx.lineWidth = 2.5;
        ctx.strokeRect(0.5, ry, cssW, h);
      }

      // Separator line.
      ctx.strokeStyle = isDeg ? '#293a58' : '#202842';
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(0, ry + h);
      ctx.lineTo(cssW, ry + h);
      ctx.stroke();

      if (!isDeg) continue;

      // Degree label.
      const name = cell.degree ?? '?';
      ctx.textBaseline = 'middle';
      ctx.font = `700 ${Math.max(10, Math.round(11 * scale))}px 'Segoe UI', system-ui, sans-serif`;
      ctx.fillStyle = (isActive || isDetected) ? '#ffffff' : (cell.enabled ? accent : '#52657a');
      ctx.fillText(name, 9, ry + h / 2);

      // Reference pitch labels.
      const hz = this.app.grid.moriaToHz(cell.moria + cell.accidental);
      const pitch = concertPitchParts(hz);
      const hzStr = hz.toFixed(1);
      const pitchX = cssW - 4;
      const hzFontSize = Math.max(7, Math.round(8 * scale));
      const noteFontSize = Math.max(10, Math.round(12 * scale));
      const centsFontSize = Math.max(7, Math.round(8 * scale));
      const noteColor = (isActive || isDetected) ? '#ffffff' : (cell.enabled ? '#d8f1ff' : '#536273');
      const metaColor = cell.enabled ? '#91acc2' : '#3e4b5c';

      ctx.textAlign = 'right';
      if (pitch && h >= 20) {
        const noteY = ry + h / 2 - 4 * scale;
        const hzY = ry + h / 2 + 7 * scale;
        ctx.font = `${centsFontSize}px monospace`;
        ctx.fillStyle = metaColor;
        const centsW = ctx.measureText(pitch.cents).width;
        ctx.fillText(pitch.cents, pitchX, noteY);
        ctx.font = `700 ${noteFontSize}px 'Segoe UI', system-ui, sans-serif`;
        ctx.fillStyle = noteColor;
        ctx.fillText(pitch.note, pitchX - centsW - 4, noteY);
        ctx.font = `${hzFontSize}px monospace`;
        ctx.fillStyle = metaColor;
        ctx.fillText(`${hzStr} Hz`, pitchX, hzY);
      } else if (pitch) {
        ctx.font = `${centsFontSize}px monospace`;
        ctx.fillStyle = metaColor;
        const meta = `${pitch.cents} ${hzStr}`;
        const metaW = ctx.measureText(meta).width;
        ctx.fillText(meta, pitchX, ry + h / 2);
        ctx.font = `700 ${noteFontSize}px 'Segoe UI', system-ui, sans-serif`;
        ctx.fillStyle = noteColor;
        ctx.fillText(pitch.note, pitchX - metaW - 5, ry + h / 2);
      } else {
        ctx.font = `${hzFontSize}px monospace`;
        ctx.fillStyle = metaColor;
        ctx.fillText(hzStr, pitchX, ry + h / 2);
      }
      ctx.textAlign = 'left';
      ctx.textBaseline = 'alphabetic';

      // Accidental badge.
      if (cell.accidental !== 0) {
        const sign = cell.accidental > 0 ? '+' : '';
        const badge = `${sign}${cell.accidental}`;
        ctx.font = `bold ${Math.round(9 * scale)}px monospace`;
        ctx.textBaseline = 'middle';
        const bw = ctx.measureText(badge).width;
        ctx.fillStyle = 'rgba(233,69,96,0.22)';
        fillRoundedRect(ctx, cssW / 2 - bw / 2 - 6, ry + h / 2 - 7, bw + 12, 14, 7);
        ctx.fillStyle = '#ff6d86';
        ctx.fillText(badge, cssW / 2 - bw / 2, ry + h / 2);
        ctx.textBaseline = 'alphabetic';
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
      const barW = Math.min((interval / 24) * cssW * 0.72, cssW * 0.72);
      const barH = Math.max(2, Math.min(gapH * 0.28, 5));
      const barX = (cssW - barW) / 2;
      ctx.fillStyle = color + '22';
      fillRoundedRect(ctx, barX - 7, midY - barH / 2 - 3, barW + 14, barH + 6, 5);
      ctx.fillStyle = color + '72';
      fillRoundedRect(ctx, barX, midY - barH / 2, barW, barH, barH / 2);

      // Interval number, centered in the gap.
      if (gapH >= 7) {
        const fontSize = Math.max(7, Math.round(9 * scale));
        ctx.font = `bold ${fontSize}px monospace`;
        const label = String(interval);
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = '#111a31cc';
        fillRoundedRect(ctx, cssW / 2 - tw / 2 - 5, midY - fontSize / 2 - 2, tw + 10, fontSize + 4, 5);
        ctx.fillStyle = color;
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
    if (this._suppressNextClick) {
      this._suppressNextClick = false;
      e.stopPropagation();
      return;
    }
    const cell = this._hitTest(this._cssY(e));
    if (!cell || cell.degree === null) return;
    this.app.grid.toggleCell(cell.moria);
    this.app.gridChanged();
  }

  _onRightClick(e) {
    e.preventDefault();
    const cell = this._hitTest(this._cssY(e));
    if (!cell || cell.degree === null) return;
    this.app.showAccidentalPopup(cell, e.clientX, e.clientY);
  }

  _onPointerDown(e) {
    const startX = e.clientX;
    const startY = e.clientY;
    const startCell = this._hitTest(this._cssY(e));
    if (!startCell || startCell.degree === null) return;

    let fired = false;
    const timer = setTimeout(() => {
      fired = true;
      this.app.showAccidentalPopup(startCell, startX, startY);
    }, 500);

    const finish = () => {
      clearTimeout(timer);
      this.canvas.removeEventListener('pointermove', onMove);
      this.canvas.removeEventListener('pointerup', finish);
      this.canvas.removeEventListener('pointercancel', finish);
      if (fired) {
        // Suppress the synthetic click that follows pointerup so we don't
        // (a) toggle the cell in _onClick, or (b) let the document-level
        // "click outside → hide popup" handler hide the popup we just opened.
        this._suppressNextClick = true;
        setTimeout(() => { this._suppressNextClick = false; }, 400);
      }
    };
    const onMove = me => {
      if (fired) return;
      const dx = me.clientX - startX;
      const dy = me.clientY - startY;
      if (dx * dx + dy * dy > 36) finish();  // 6px threshold
    };
    this.canvas.addEventListener('pointermove', onMove);
    this.canvas.addEventListener('pointerup', finish);
    this.canvas.addEventListener('pointercancel', finish);
  }

  _onPaletteDrop(e) {
    const { payload, clientY } = e.detail;
    const rect = this.canvas.getBoundingClientRect();
    const cell = this._hitTest(clientY - rect.top);
    if (!cell) return;
    this.app.applySymbolPayloadToCell?.(payload, cell);
  }

  _onPaletteHover(e) {
    const { clientY, leaving } = e.detail;
    if (leaving) {
      this._hoverCell = null;
    } else {
      const rect = this.canvas.getBoundingClientRect();
      this._hoverCell = this._hitTest(clientY - rect.top);
    }
    this._paint();
  }
}
