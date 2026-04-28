export const SCORE_PRACTICE_ENABLED_DEFAULT = false;

const DEFAULT_LOOKAHEAD_MS = 6000;
const DEFAULT_PX_PER_SECOND = 90;
const DEFAULT_CROSSHAIR_X = 0.28;
const DEFAULT_TOLERANCE_MORIA = 4;
const FEATURE_STORAGE_KEY = 'chanterlab_score_practice_enabled';

export function scorePracticeFeatureEnabled({
  location = globalThis.location,
  storage = globalThis.localStorage,
} = {}) {
  const params = new URLSearchParams(location?.search ?? '');
  const queryValue = params.get('scorePractice') ?? params.get('score-practice');
  if (queryValue !== null) return ['1', 'true', 'yes', 'on'].includes(queryValue.toLowerCase());

  try {
    return ['1', 'true', 'yes', 'on'].includes(
      String(storage?.getItem?.(FEATURE_STORAGE_KEY) ?? '').toLowerCase()
    );
  } catch {
    return false;
  }
}

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
        active: target.startMs <= nowMs && nowMs < target.endMs,
        visible: x + width >= 0 && x <= cssW,
      };
    })
    .filter(target => target.visible);
}

export function scorePracticeLeadInScoreMs(viewport, options = {}) {
  const playbackRate = playbackRateFromOptions(options);
  const leadInMs = Number(options.leadInMs);
  return Number.isFinite(leadInMs) && leadInMs > 0 ? leadInMs * playbackRate : 0;
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
    this._statusEl = options.statusEl ?? null;
    this._lastPitchScore = null;
    this._ro = null;
    if (this.canvas && typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this.paint());
      this._ro.observe(this.canvas);
    }
  }

  setCompiledScore(compiled) {
    this.state = createScorePracticeState(compiled, { enabled: this.enabled });
    this.nowMs = this._initialNowMs();
    this._lastPitchScore = null;
    this.paint();
    this._renderStatus();
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
    this._renderStatus();
  }

  setTiming(options = {}) {
    const wasRunning = this.isRunning();
    const now = performanceNow();
    this._options = {
      ...this._options,
      ...options,
    };
    if (wasRunning) {
      this._startedAt = now - this.nowMs / this._playbackRate();
    }
    this.paint();
    this._renderStatus();
  }

  isRunning() {
    return this._rafId !== null;
  }

  start(now = performanceNow()) {
    if (!this.enabled || this._rafId !== null) return;
    const playbackRate = this._playbackRate();
    this._startedAt = now - this.nowMs / playbackRate;
    const tick = timestamp => {
      this._rafId = requestAnimationFrame(tick);
      const nextScoreMs = (timestamp - this._startedAt) * playbackRate;
      this.nowMs = Math.min(
        this.state.totalDurationMs,
        Math.max(this._initialNowMs(), nextScoreMs)
      );
      this.paint();
      this._renderStatus();
      if (this.nowMs >= this.state.totalDurationMs) {
        if (this._options.loop && this.state.totalDurationMs > 0) {
          this.nowMs = this._initialNowMs();
          this._startedAt = timestamp - this.nowMs / playbackRate;
        } else {
          this.stop();
        }
      }
    };
    this._rafId = requestAnimationFrame(tick);
    this._renderStatus();
  }

  stop() {
    if (this._rafId === null) return;
    cancelAnimationFrame(this._rafId);
    this._rafId = null;
  }

  seek(ms) {
    this.nowMs = Math.max(this._initialNowMs(), Math.min(ms, this.state.totalDurationMs));
    this.paint();
    this._renderStatus();
  }

  restart() {
    this.stop();
    this.seek(this._initialNowMs());
    this.start();
  }

  _playbackRate() {
    return playbackRateFromOptions(this._options);
  }

  _viewportWidth() {
    const dpr = globalThis.devicePixelRatio || 1;
    const rect = this.canvas?.getBoundingClientRect?.();
    if (Number.isFinite(rect?.width) && rect.width > 0) return rect.width;
    if (Number.isFinite(this.canvas?.width) && this.canvas.width > 0) return this.canvas.width / dpr;
    return 1;
  }

  _initialNowMs() {
    return -scorePracticeLeadInScoreMs({ width: this._viewportWidth() }, this._options);
  }

  handlePitch(msg) {
    if (!this.enabled) return null;
    this._lastPitchScore = scorePitchAtTime(this.state, msg, this.nowMs, {
      toleranceMoria: this._options.toleranceMoria,
    });
    this._renderStatus();
    return this._lastPitchScore;
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

  _renderStatus() {
    if (!this._statusEl || !this.enabled) return;
    const active = activeScoreTargetAt(this.state, this.nowMs);
    const elapsed = formatClock(this.nowMs);
    const total = formatClock(this.state.totalDurationMs);
    const countdownSeconds = this.nowMs < 0
      ? Math.ceil((-this.nowMs / this._playbackRate()) / 1000)
      : 0;
    const lyricLabel = active?.lyric?.kind === 'start' && active.lyric.text !== active.degree
      ? active.lyric.text
      : '';
    const targetLabel = active?.type === 'note'
      ? `${active.degree}${lyricLabel ? ` · ${lyricLabel}` : ''}`
      : active?.type === 'rest'
        ? 'Rest'
        : 'Ready';
    const pitch = this._lastPitchScore;
    const pitchLabel = pitch?.expectedSilence
      ? (pitch.voiced ? 'singing through rest' : 'silent')
      : Number.isFinite(pitch?.errorMoria)
        ? `${pitch.inTune ? 'in tune' : 'adjust'} ${pitch.errorMoria >= 0 ? '+' : ''}${pitch.errorMoria.toFixed(1)}m`
        : 'waiting';

    const clockLabel = countdownSeconds > 0
      ? `starts in ${countdownSeconds}`
      : `${elapsed}/${total}`;
    this._statusEl.textContent = `${this.state.title} · ${clockLabel} · ${targetLabel} · ${pitchLabel}`;
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

  paintLeadInCountdown(ctx, viewport, options);

  for (const target of targets) {
    if (target.type === 'rest') {
      ctx.fillStyle = target.active ? 'rgba(190, 198, 208, 0.50)' : 'rgba(160, 170, 180, 0.30)';
      ctx.fillRect(target.x, target.y, target.width, target.height);
      continue;
    }

    ctx.fillStyle = target.active ? 'rgba(120, 240, 173, 0.88)' : 'rgba(83, 192, 240, 0.75)';
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

function paintLeadInCountdown(ctx, viewport, options) {
  if (!(viewport.nowMs < 0)) return;
  const rate = Number.isFinite(options.playbackRate) && options.playbackRate > 0
    ? options.playbackRate
    : 1;
  const seconds = Math.ceil((-viewport.nowMs / rate) / 1000);
  const crosshairX = viewport.width * (options.crosshairX ?? DEFAULT_CROSSHAIR_X);
  const label = seconds > 0 ? String(seconds) : 'Go';

  ctx.save();
  ctx.fillStyle = 'rgba(8, 12, 18, 0.72)';
  ctx.strokeStyle = 'rgba(120, 240, 173, 0.45)';
  ctx.lineWidth = 1;
  const w = 58;
  const h = 44;
  const x = Math.max(8, Math.min(viewport.width - w - 8, crosshairX - w / 2));
  const y = 72;
  fillRoundedRect(ctx, x, y, w, h, 6);
  ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
  ctx.fillStyle = '#dff8ec';
  ctx.font = 'bold 24px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, x + w / 2, y + h / 2);
  ctx.restore();
}

function fillRoundedRect(ctx, x, y, w, h, r) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
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
  ctx.fill();
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

function positiveNumberOr(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function playbackRateFromOptions(options) {
  return positiveNumberOr(options?.playbackRate, 1);
}

function performanceNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function formatClock(ms) {
  const totalSeconds = Math.max(0, Math.floor((ms ?? 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}
