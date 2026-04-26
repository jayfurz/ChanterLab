// ExerciseMode — local practice drills scored from live pitch events.

const EXERCISES = [
  {
    id: 'match-ni',
    title: 'Match Ni',
    presetIdx: 0,
    tolerance: 4,
    steps: [
      { label: 'Hold Ni', degree: 'Ni', octave: 0, holdMs: 4000 },
    ],
  },
  {
    id: 'diatonic-ascent',
    title: 'Diatonic Ascent',
    presetIdx: 0,
    tolerance: 4,
    steps: [
      { label: 'Ni',  degree: 'Ni',  octave: 0, holdMs: 1400 },
      { label: 'Pa',  degree: 'Pa',  octave: 0, holdMs: 1400 },
      { label: 'Vou', degree: 'Vou', octave: 0, holdMs: 1400 },
      { label: 'Ga',  degree: 'Ga',  octave: 0, holdMs: 1400 },
      { label: 'Di',  degree: 'Di',  octave: 0, holdMs: 1400 },
      { label: 'Ke',  degree: 'Ke',  octave: 0, holdMs: 1400 },
      { label: 'Zo',  degree: 'Zo',  octave: 0, holdMs: 1400 },
      { label: "Ni'", degree: 'Ni',  octave: 1, holdMs: 1600 },
    ],
  },
  {
    id: 'diatonic-descent',
    title: 'Diatonic Descent',
    presetIdx: 0,
    tolerance: 4,
    steps: [
      { label: "Ni'", degree: 'Ni',  octave: 1, holdMs: 1400 },
      { label: 'Zo',  degree: 'Zo',  octave: 0, holdMs: 1400 },
      { label: 'Ke',  degree: 'Ke',  octave: 0, holdMs: 1400 },
      { label: 'Di',  degree: 'Di',  octave: 0, holdMs: 1400 },
      { label: 'Ga',  degree: 'Ga',  octave: 0, holdMs: 1400 },
      { label: 'Vou', degree: 'Vou', octave: 0, holdMs: 1400 },
      { label: 'Pa',  degree: 'Pa',  octave: 0, holdMs: 1400 },
      { label: 'Ni',  degree: 'Ni',  octave: 0, holdMs: 1600 },
    ],
  },
  {
    id: 'hard-chromatic-pa',
    title: 'Hard Chromatic Pa',
    presetIdx: 1,
    tolerance: 4,
    steps: [
      { label: 'Pa',  degree: 'Pa',  octave: 0, holdMs: 1800 },
      { label: 'Vou', degree: 'Vou', octave: 0, holdMs: 1800 },
      { label: 'Ga',  degree: 'Ga',  octave: 0, holdMs: 1800 },
      { label: 'Di',  degree: 'Di',  octave: 0, holdMs: 1800 },
      { label: 'Ga',  degree: 'Ga',  octave: 0, holdMs: 1800 },
      { label: 'Vou', degree: 'Vou', octave: 0, holdMs: 1800 },
      { label: 'Pa',  degree: 'Pa',  octave: 0, holdMs: 1800 },
    ],
  },
];

const RANGE_OPTIONS = [
  { value: 110, label: 'Bass - Ni A2' },
  { value: 130.81, label: 'Baritone - Ni C3' },
  { value: 155.56, label: 'Tenor - Ni Eb3' },
  { value: 220, label: 'Female low - Ni A3' },
  { value: 261.63, label: 'Female mid - Ni C4' },
  { value: 311.13, label: 'Female high - Ni Eb4' },
];

const EMPTY_STEP_STATS = () => ({
  voicedMs: 0,
  inTuneMs: 0,
  absErrorMs: 0,
  signedErrorMs: 0,
  samples: 0,
  bestAbsError: null,
});

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function formatMs(ms) {
  return `${Math.max(0, Math.ceil(ms / 1000))}s`;
}

function scoreLabel(score) {
  if (score >= 90) return 'Excellent';
  if (score >= 75) return 'Passing';
  if (score >= 55) return 'Developing';
  return 'Needs reps';
}

function nearestOctaveMoriaDelta(delta) {
  if (!Number.isFinite(delta)) return delta;
  while (delta > 36) delta -= 72;
  while (delta < -36) delta += 72;
  return delta;
}

export class ExerciseMode {
  constructor(container, app, opts = {}) {
    this.el = container;
    this.app = app;
    this._selectPreset = opts.selectPreset || null;

    this.exercise = EXERCISES[0];
    this.running = false;
    this.started = false;
    this.finished = false;
    this.stepIdx = 0;
    this.lastEventAt = null;
    this.stepStats = [];
    this.history = this._loadHistory();

    this._exerciseSelect = container.querySelector('#exercise-select');
    this._rangeSelect = container.querySelector('#exercise-range-select');
    this._startBtns = Array.from(document.querySelectorAll('[data-exercise-action="start"]'));
    this._resetBtns = Array.from(document.querySelectorAll('[data-exercise-action="reset"]'));
    this._copyBtns = Array.from(document.querySelectorAll('[data-exercise-action="copy"]'));
    this._setupSummaryEl = container.querySelector('#exercise-setup-summary');
    this._targetEl = container.querySelector('#exercise-target');
    this._hintEl = container.querySelector('#exercise-hint');
    this._progressFillEl = container.querySelector('#exercise-progress-fill');
    this._progressTextEl = container.querySelector('#exercise-progress-text');
    this._scoreEl = container.querySelector('#exercise-score');
    this._detailsEl = container.querySelector('#exercise-details');

    this._buildOptions();
    this._buildRangeOptions();
    this._wire();
    this._resetState();
    this._applySelectedRange();
    this._render();
  }

  refresh() {
    if (!this.running) this._render();
  }

  syncReferenceNiHz(hz) {
    if (!this._rangeSelect || this.running) return;
    const fixedOption = RANGE_OPTIONS.find(option => Math.abs(option.value - hz) < 0.005);
    this._rangeSelect.value = fixedOption ? String(fixedOption.value) : 'custom';
  }

  handlePitch(msg) {
    if (!this.running || this.finished) return;
    const now = performance.now();
    const dt = this.lastEventAt === null ? 0 : clamp(now - this.lastEventAt, 0, 250);
    this.lastEventAt = now;
    if (dt <= 0) return;

    const target = this._currentTarget();
    if (!target || !msg.gate_open || !Number.isFinite(msg.detected_hz) || msg.detected_hz <= 0) {
      this._render();
      return;
    }

    const stats = this.stepStats[this.stepIdx];
    const error = nearestOctaveMoriaDelta(72 * Math.log2(msg.detected_hz / target.targetHz));
    const absError = Math.abs(error);
    stats.voicedMs += dt;
    stats.samples += 1;
    stats.absErrorMs += absError * dt;
    stats.signedErrorMs += error * dt;
    stats.bestAbsError = stats.bestAbsError === null
      ? absError
      : Math.min(stats.bestAbsError, absError);
    if (absError <= this.exercise.tolerance) {
      stats.inTuneMs += dt;
    }

    if (stats.voicedMs >= target.step.holdMs) {
      this._advanceStep();
    } else {
      this._render(target, error);
    }
  }

  _buildOptions() {
    if (!this._exerciseSelect) return;
    // Keep the static HTML options as an iOS Safari fallback. Rebuild only if
    // markup is missing or stale.
    if (this._exerciseSelect.options.length === EXERCISES.length) return;
    this._exerciseSelect.innerHTML = '';
    for (const ex of EXERCISES) {
      const opt = document.createElement('option');
      opt.value = ex.id;
      opt.textContent = ex.title;
      this._exerciseSelect.appendChild(opt);
    }
  }

  _buildRangeOptions() {
    if (!this._rangeSelect) return;
    this._rangeSelect.innerHTML = '';
    for (const option of RANGE_OPTIONS) {
      const el = document.createElement('option');
      el.value = String(option.value);
      el.textContent = option.label;
      if (option.value === 130.81) el.selected = true;
      this._rangeSelect.appendChild(el);
    }
    const custom = document.createElement('option');
    custom.value = 'custom';
    custom.textContent = 'Use current Reference Ni';
    this._rangeSelect.appendChild(custom);
  }

  _wire() {
    this._exerciseSelect.addEventListener('change', () => {
      this.exercise = EXERCISES.find(ex => ex.id === this._exerciseSelect.value) || EXERCISES[0];
      this._resetState();
      this._render();
    });

    this._rangeSelect.addEventListener('change', () => {
      this._applySelectedRange();
      this._render();
    });

    this._startBtns.forEach(btn => btn.addEventListener('click', () => this._toggle()));

    this._resetBtns.forEach(btn => btn.addEventListener('click', () => this.reset()));

    this._copyBtns.forEach(btn => btn.addEventListener('click', () => this.copyReport()));
  }

  _toggle() {
    if (this.running) {
      this.running = false;
      this._render();
      return;
    }
    this._start();
  }

  reset() {
    this._resetState();
    this._render();
  }

  copyReport() {
    return this._copyReport();
  }

  _start() {
    if (this._selectPreset && Number.isInteger(this.exercise.presetIdx)) {
      this._selectPreset(this.exercise.presetIdx);
    }
    this._applySelectedRange();
    this.running = true;
    this.started = true;
    this.finished = false;
    this.lastEventAt = null;
    this._render();
  }

  _applySelectedRange() {
    if (!this._rangeSelect || this._rangeSelect.value === 'custom') return;
    const hz = Number(this._rangeSelect.value);
    if (!Number.isFinite(hz) || hz <= 0) return;
    if (this.app.setReferenceNiHz) this.app.setReferenceNiHz(hz);
  }

  _resetState() {
    this.running = false;
    this.started = false;
    this.finished = false;
    this.stepIdx = 0;
    this.lastEventAt = null;
    this.stepStats = this.exercise.steps.map(() => EMPTY_STEP_STATS());
  }

  _advanceStep() {
    if (this.stepIdx + 1 < this.exercise.steps.length) {
      this.stepIdx += 1;
      this.lastEventAt = null;
      this._render();
      return;
    }

    this.running = false;
    this.finished = true;
    this._saveResult();
    this._render();
  }

  _currentTarget() {
    const step = this.exercise.steps[this.stepIdx];
    if (!step) return null;
    const cells = this._cells();
    const octaveFloor = step.octave * 72;
    const matchesAtOrAboveOctave = cells
      .filter(cell => cell.enabled && cell.degree === step.degree)
      .map(cell => ({
        cell,
        effectiveMoria: this._effectiveMoria(cell),
      }))
      .filter(match => match.effectiveMoria >= octaveFloor)
      .sort((a, b) => a.effectiveMoria - b.effectiveMoria);
    const fallbackMatches = matchesAtOrAboveOctave.length > 0
      ? matchesAtOrAboveOctave
      : cells
          .filter(cell => cell.enabled && cell.degree === step.degree)
          .map(cell => ({
            cell,
            effectiveMoria: this._effectiveMoria(cell),
          }))
          .sort((a, b) => Math.abs(a.effectiveMoria - octaveFloor) - Math.abs(b.effectiveMoria - octaveFloor));
    const matchInfo = fallbackMatches[0] || null;
    const match = matchInfo?.cell || null;
    if (!match) return null;
    const targetMoria = matchInfo.effectiveMoria;
    return {
      step,
      cell: match,
      effectiveMoria: targetMoria,
      targetHz: this.app.grid.moriaToHz
        ? this.app.grid.moriaToHz(targetMoria)
        : this.app.refNiHz * Math.pow(2, targetMoria / 72),
    };
  }

  _effectiveMoria(cell) {
    return Number.isFinite(cell.effective_moria)
      ? cell.effective_moria
      : cell.moria + (cell.accidental || 0);
  }

  _cells() {
    try {
      return JSON.parse(this.app.grid.cellsJson());
    } catch {
      return [];
    }
  }

  _overall() {
    const totalVoiced = this.stepStats.reduce((sum, s) => sum + s.voicedMs, 0);
    const totalInTune = this.stepStats.reduce((sum, s) => sum + s.inTuneMs, 0);
    const totalAbs = this.stepStats.reduce((sum, s) => sum + s.absErrorMs, 0);
    const totalSigned = this.stepStats.reduce((sum, s) => sum + s.signedErrorMs, 0);
    const inTunePct = totalVoiced > 0 ? totalInTune / totalVoiced * 100 : 0;
    const avgAbsError = totalVoiced > 0 ? totalAbs / totalVoiced : null;
    const avgSignedError = totalVoiced > 0 ? totalSigned / totalVoiced : null;
    const score = totalVoiced > 0
      ? Math.round(clamp(inTunePct - Math.max(0, (avgAbsError === null ? 0 : avgAbsError) - 1) * 4, 0, 100))
      : 0;
    return { totalVoiced, inTunePct, avgAbsError, avgSignedError, score };
  }

  _render(target = this._currentTarget(), liveError = null) {
    const step = target ? target.step : this.exercise.steps[this.stepIdx];
    const stats = this.stepStats[this.stepIdx] || EMPTY_STEP_STATS();
    const progress = step ? clamp(stats.voicedMs / step.holdMs, 0, 1) : 0;
    const overall = this._overall();
    const last = this.history[this.exercise.id];

    if (this._exerciseSelect) this._exerciseSelect.value = this.exercise.id;
    this._startBtns.forEach(btn => {
      btn.textContent = this.running ? 'Pause' : this.finished ? 'Run Again' : 'Start';
    });
    this._copyBtns.forEach(btn => { btn.disabled = !this.finished; });

    const targetText = this.finished
      ? 'Complete'
      : `${step ? step.label : '-'} (${this.stepIdx + 1}/${this.exercise.steps.length})`;
    if (this._targetEl) this._targetEl.textContent = targetText;

    let hintText;
    if (!target && !this.finished) {
      hintText = 'Target note is not enabled in the current grid.';
    } else if (this.running && liveError !== null) {
      const dir = liveError > 0.2 ? 'lower' : liveError < -0.2 ? 'lift' : 'hold';
      hintText = `${dir}: ${liveError >= 0 ? '+' : ''}${liveError.toFixed(1)} moria`;
    } else if (this.finished) {
      hintText = `${scoreLabel(overall.score)}. ${overall.score}/100`;
    } else {
      hintText = `Sing ${step ? step.label : 'the target'} until the bar fills. Tolerance: +/-${this.exercise.tolerance} moria.`;
    }
    if (this._hintEl) this._hintEl.textContent = hintText;

    if (this._progressFillEl) this._progressFillEl.style.width = `${Math.round(progress * 100)}%`;
    const progressText = this.finished
      ? 'done'
      : `${formatMs(stats.voicedMs)} / ${formatMs(step ? step.holdMs : 0)}`;
    if (this._progressTextEl) this._progressTextEl.textContent = progressText;

    const scoreText = overall.totalVoiced > 0 || this.finished
      ? `${overall.score}/100`
      : last ? `best ${last.score}/100` : '--';
    if (this._scoreEl) this._scoreEl.textContent = scoreText;

    const avg = overall.avgAbsError === null ? '--' : `${overall.avgAbsError.toFixed(1)} m`;
    const inTune = overall.totalVoiced > 0 ? `${Math.round(overall.inTunePct)}%` : '--';
    const detailsText = `In tune ${inTune} · avg error ${avg}`;
    if (this._detailsEl) this._detailsEl.textContent = detailsText;
    if (this._setupSummaryEl) {
      this._setupSummaryEl.textContent = this.finished
        ? `${scoreLabel(overall.score)} - ${detailsText}`
        : `Center HUD shows ${targetText}. ${detailsText}`;
    }

    this.app.noteIndicator?.setExerciseState({
      exerciseTitle: this.exercise.title,
      targetText,
      stepText: this.finished ? 'Done' : `${this.stepIdx + 1} / ${this.exercise.steps.length}`,
      hintText,
      progress,
      progressText,
      scoreText,
      detailsText,
      running: this.running,
      started: this.started,
      finished: this.finished,
      canCopy: this.finished,
      hasTarget: Boolean(target),
    });
  }

  _report() {
    const overall = this._overall();
    return {
      exercise: this.exercise.title,
      completed_at: new Date().toISOString(),
      score: overall.score,
      in_tune_pct: Math.round(overall.inTunePct),
      avg_abs_moria: overall.avgAbsError === null ? null : Number(overall.avgAbsError.toFixed(2)),
      avg_signed_moria: overall.avgSignedError === null ? null : Number(overall.avgSignedError.toFixed(2)),
      steps: this.exercise.steps.map((step, idx) => {
        const stats = this.stepStats[idx];
        const avgAbs = stats.voicedMs > 0 ? stats.absErrorMs / stats.voicedMs : null;
        const inTune = stats.voicedMs > 0 ? stats.inTuneMs / stats.voicedMs * 100 : 0;
        return {
          label: step.label,
          in_tune_pct: Math.round(inTune),
          avg_abs_moria: avgAbs === null ? null : Number(avgAbs.toFixed(2)),
          best_abs_moria: stats.bestAbsError === null ? null : Number(stats.bestAbsError.toFixed(2)),
          voiced_seconds: Number((stats.voicedMs / 1000).toFixed(1)),
        };
      }),
    };
  }

  _saveResult() {
    const report = this._report();
    const previous = this.history[this.exercise.id];
    if (!previous || report.score >= previous.score) {
      this.history[this.exercise.id] = {
        score: report.score,
        completed_at: report.completed_at,
      };
      localStorage.setItem('chanterlab_exercise_history', JSON.stringify(this.history));
    }
  }

  _loadHistory() {
    try {
      return JSON.parse(localStorage.getItem('chanterlab_exercise_history') || '{}');
    } catch {
      return {};
    }
  }

  async _copyReport() {
    const text = JSON.stringify(this._report(), null, 2);
    try {
      await navigator.clipboard.writeText(text);
      if (this._detailsEl) this._detailsEl.textContent = 'Report copied.';
      if (this._setupSummaryEl) this._setupSummaryEl.textContent = 'Report copied.';
      this.app.noteIndicator?.setMessage('Report copied.');
    } catch {
      console.log(text);
      if (this._detailsEl) this._detailsEl.textContent = 'Report printed to console.';
      if (this._setupSummaryEl) this._setupSummaryEl.textContent = 'Report printed to console.';
      this.app.noteIndicator?.setMessage('Report printed to console.');
    }
  }
}
