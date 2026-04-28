export const SCORE_PRACTICE_ENABLED_DEFAULT = false;

const DEFAULT_LOOKAHEAD_MS = 6000;
const DEFAULT_PX_PER_SECOND = 90;
const DEFAULT_CROSSHAIR_X = 0.28;
const DEFAULT_TOLERANCE_MORIA = 4;

export function createScorePracticeState(compiled, options = {}) {
  const timeline = Array.isArray(compiled?.timeline) ? compiled.timeline : [];
  const targets = timeline
    .filter(event => event.type === 'note' || event.type === 'rest')
    .map(event => ({
      type: event.type,
      startMs: event.startMs,
      endMs: event.startMs + event.durationMs,
      durationMs: event.durationMs,
      durationBeats: event.durationBeats,
      sourceEventIndex: event.sourceEventIndex,
      ...(event.type === 'note'
        ? {
            degree: event.degree,
            moria: event.effectiveMoria ?? event.moria,
            lyric: event.lyric,
            display: event.display,
          }
        : {}),
    }));

  return {
    enabled: options.enabled ?? SCORE_PRACTICE_ENABLED_DEFAULT,
    title: compiled?.score?.title ?? 'Untitled Score',
    totalDurationMs: compiled?.totalDurationMs ?? targets.at(-1)?.endMs ?? 0,
    targets,
    tempoChanges: compiled?.tempoChanges ?? [],
    checkpoints: compiled?.checkpoints ?? [],
    phraseBreaks: compiled?.phraseBreaks ?? [],
    isonEvents: compiled?.isonEvents ?? [],
    pthoraEvents: compiled?.pthoraEvents ?? [],
    diagnostics: compiled?.diagnostics ?? [],
  };
}

export function activeScoreTargetAt(state, atMs) {
  if (!state || !Number.isFinite(atMs)) return undefined;
  return state.targets.find(target => target.startMs <= atMs && atMs < target.endMs);
}

export function scorePitchAtTime(state, pitchEvent, atMs, options = {}) {
  const target = activeScoreTargetAt(state, atMs);
  if (!target || target.type !== 'note') {
    return {
      active: !!target,
      target,
      expectedSilence: target?.type === 'rest',
      voiced: !!pitchEvent?.gate_open,
      inTune: false,
      errorMoria: undefined,
    };
  }

  const voiced = !!pitchEvent?.gate_open;
  const rawMoria = Number.isFinite(pitchEvent?.raw_moria)
    ? pitchEvent.raw_moria
    : pitchEvent?.moria;
  const errorMoria = voiced && Number.isFinite(rawMoria)
    ? nearestOctaveMoriaDelta(rawMoria - target.moria)
    : undefined;
  const tolerance = Number.isFinite(options.toleranceMoria)
    ? options.toleranceMoria
    : DEFAULT_TOLERANCE_MORIA;

  return {
    active: true,
    target,
    expectedSilence: false,
    voiced,
    errorMoria,
    inTune: Number.isFinite(errorMoria) && Math.abs(errorMoria) <= tolerance,
  };
}

export function layoutScorePracticeTargets(state, rowMap, viewport, options = {}) {
  const cssW = Math.max(1, viewport?.width ?? 1);
  const cssH = Math.max(1, viewport?.height ?? 1);
  const nowMs = viewport?.nowMs ?? 0;
  const lookaheadMs = options.lookaheadMs ?? DEFAULT_LOOKAHEAD_MS;
  const pxPerSecond = options.pxPerSecond ?? DEFAULT_PX_PER_SECOND;
  const crosshairX = cssW * (options.crosshairX ?? DEFAULT_CROSSHAIR_X);
  const rowLookup = buildRowLookup(rowMap, cssH);

  return state.targets
    .filter(target => target.endMs >= nowMs && target.startMs <= nowMs + lookaheadMs)
    .map(target => {
      const x = crosshairX + ((target.startMs - nowMs) / 1000) * pxPerSecond;
      const width = Math.max(4, (target.durationMs / 1000) * pxPerSecond);
      const row = target.type === 'note' ? rowLookup(target.moria) : undefined;
      const y = target.type === 'note' ? row?.centerY ?? cssH / 2 : cssH - 16;
      const height = target.type === 'note' ? Math.max(6, Math.min(row?.height ?? 12, 18)) : 8;

      return {
        ...target,
        x,
        y,
        width,
        height,
        visible: x + width >= 0 && x <= cssW,
      };
    })
    .filter(target => target.visible);
}

export class ScorePracticePrototype {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas?.getContext?.('2d') ?? null;
    this.enabled = options.enabled ?? SCORE_PRACTICE_ENABLED_DEFAULT;
    this.state = createScorePracticeState(null, { enabled: this.enabled });
    this.rowMap = [];
    this.nowMs = 0;
    this._rafId = null;
    this._startedAt = 0;
    this._options = options;
  }

  setCompiledScore(compiled) {
    this.state = createScorePracticeState(compiled, { enabled: this.enabled });
    this.nowMs = 0;
    this.paint();
  }

  setRowMap(rowMap) {
    this.rowMap = Array.isArray(rowMap) ? rowMap : [];
    this.paint();
  }

  setEnabled(enabled) {
    this.enabled = !!enabled;
    this.state.enabled = this.enabled;
    if (!this.enabled) this.stop();
    else this.paint();
  }

  start(now = performanceNow()) {
    if (!this.enabled || this._rafId !== null) return;
    this._startedAt = now - this.nowMs;
    const tick = timestamp => {
      this._rafId = requestAnimationFrame(tick);
      this.nowMs = Math.min(
        this.state.totalDurationMs,
        Math.max(0, timestamp - this._startedAt)
      );
      this.paint();
    };
    this._rafId = requestAnimationFrame(tick);
  }

  stop() {
    if (this._rafId === null) return;
    cancelAnimationFrame(this._rafId);
    this._rafId = null;
  }

  seek(ms) {
    this.nowMs = Math.max(0, Math.min(ms, this.state.totalDurationMs));
    this.paint();
  }

  paint() {
    if (!this.ctx || !this.canvas || !this.enabled) return;
    const dpr = globalThis.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect?.() ?? {
      width: this.canvas.width / dpr,
      height: this.canvas.height / dpr,
    };
    const cssW = Math.max(1, rect.width);
    const cssH = Math.max(1, rect.height);
    if (this.canvas.width !== Math.round(cssW * dpr)) this.canvas.width = Math.round(cssW * dpr);
    if (this.canvas.height !== Math.round(cssH * dpr)) this.canvas.height = Math.round(cssH * dpr);

    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.ctx.clearRect(0, 0, cssW, cssH);
    paintScorePracticeTargets(this.ctx, this.state, this.rowMap, {
      width: cssW,
      height: cssH,
      nowMs: this.nowMs,
    }, this._options);
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
  }
}

export function paintScorePracticeTargets(ctx, state, rowMap, viewport, options = {}) {
  const targets = layoutScorePracticeTargets(state, rowMap, viewport, options);
  const crosshairX = viewport.width * (options.crosshairX ?? DEFAULT_CROSSHAIR_X);

  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.42)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(crosshairX, 0);
  ctx.lineTo(crosshairX, viewport.height);
  ctx.stroke();

  for (const target of targets) {
    if (target.type === 'rest') {
      ctx.fillStyle = 'rgba(160, 170, 180, 0.30)';
      ctx.fillRect(target.x, target.y, target.width, target.height);
      continue;
    }

    ctx.fillStyle = 'rgba(83, 192, 240, 0.75)';
    ctx.fillRect(target.x, target.y - target.height / 2, target.width, target.height);
    const label = target.display?.generatedGlyphName ?? target.degree;
    if (label) {
      ctx.fillStyle = 'rgba(238, 246, 250, 0.92)';
      ctx.font = '11px system-ui, sans-serif';
      ctx.fillText(label, target.x, Math.max(12, target.y - target.height));
    }
    if (target.lyric?.kind === 'start' && target.lyric.text) {
      ctx.fillStyle = 'rgba(238, 246, 250, 0.78)';
      ctx.font = '11px system-ui, sans-serif';
      ctx.fillText(target.lyric.text, target.x, Math.min(viewport.height - 4, target.y + 18));
    }
  }
  ctx.restore();
}

function buildRowLookup(rowMap, cssH) {
  const rows = Array.isArray(rowMap) ? rowMap : [];
  const last = rows.at(-1);
  const ladderH = last ? last.y + last.h : cssH;
  const scale = ladderH > 0 ? cssH / ladderH : 1;

  return moria => {
    if (!rows.length || !Number.isFinite(moria)) return undefined;
    let best = rows[0];
    let bestDist = Infinity;
    for (const row of rows) {
      const rowMoria = cellEffectiveMoria(row.cell);
      const dist = Math.abs(rowMoria - moria);
      if (dist < bestDist) {
        best = row;
        bestDist = dist;
      }
    }
    return {
      row: best,
      centerY: (best.y + best.h / 2) * scale,
      height: best.h * scale,
    };
  };
}

function cellEffectiveMoria(cell) {
  if (!cell) return 0;
  if (Number.isFinite(cell.effective_moria)) return cell.effective_moria;
  return (cell.moria ?? 0) + (cell.accidental ?? 0);
}

function nearestOctaveMoriaDelta(delta) {
  if (!Number.isFinite(delta)) return delta;
  while (delta > 36) delta -= 72;
  while (delta < -36) delta += 72;
  return delta;
}

function performanceNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}
