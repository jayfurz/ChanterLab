//! Additive voice synthesizer for native hosts.
//!
//! A port of `web/audio/synth_worklet.js`: eight-partial additive voices with
//! the same voicings, envelopes and velocity smoothing, plus a metronome
//! click. The control thread talks to it through a lock-free single-producer
//! queue ([`Synth::send`]); the audio thread calls [`Synth::render`], which
//! never allocates, locks or blocks.

use core::cell::UnsafeCell;
use core::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

const K: usize = 8;
const MAX_VOICES: usize = 32;
/// Notes scheduled ahead of time and not yet started.
const MAX_PENDING: usize = 128;
const ATTACK_S: f32 = 0.005;
const RELEASE_S: f32 = 0.08;
const VEL_RAMP_S: f32 = 0.02;
const CLICK_DECAY_S: f32 = 0.035;
const QUEUE_LEN: usize = 256;
/// Headroom so a few simultaneous full-velocity voices stay under the clipper's knee.
const MIX_GAIN: f32 = 0.5;

/// Harmonic weights per voicing: (keyboard voice, ison drone). Normalised at use.
const VOICINGS: [([f32; K], [f32; K]); 6] = [
    // Sine
    (
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ),
    // Organ: 1 / k^1.2
    (
        [1.0, 0.4353, 0.2676, 0.1895, 0.1450, 0.1165, 0.0968, 0.0825],
        [1.0, 0.75, 0.55, 0.38, 0.26, 0.17, 0.11, 0.07],
    ),
    // Reed
    (
        [1.0, 0.30, 0.85, 0.25, 0.65, 0.20, 0.45, 0.15],
        [1.0, 0.40, 0.75, 0.30, 0.55, 0.20, 0.35, 0.12],
    ),
    // Flute
    (
        [1.0, 0.25, 0.08, 0.04, 0.02, 0.01, 0.005, 0.002],
        [1.0, 0.30, 0.10, 0.04, 0.02, 0.01, 0.005, 0.002],
    ),
    // String
    (
        [1.0, 0.85, 0.70, 0.55, 0.45, 0.35, 0.25, 0.18],
        [1.0, 0.90, 0.75, 0.60, 0.48, 0.36, 0.26, 0.18],
    ),
    // Triangle (the practice accompaniment): odd partials at 1 / k².
    (
        [1.0, 0.0, 0.1111, 0.0, 0.04, 0.0, 0.0204, 0.0],
        [1.0, 0.0, 0.1111, 0.0, 0.04, 0.0, 0.0204, 0.0],
    ),
];

fn normalised(weights: [f32; K]) -> [f32; K] {
    let sum: f32 = weights.iter().sum();
    weights.map(|w| w / sum)
}

/// A control-thread request. `id` is any caller-chosen key (the app uses the
/// cell's moria); it pairs a `NoteOn` with its `NoteOff`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Cmd {
    NoteOn {
        id: i32,
        hz: f32,
        velocity: f32,
    },
    NoteOff {
        id: i32,
    },
    /// Change the pitch of every sounding voice with this id (grid retune).
    Retune {
        id: i32,
        hz: f32,
    },
    AllNotesOff,
    /// Sustained drone. `volume <= 0` releases it.
    Ison {
        hz: f32,
        volume: f32,
    },
    /// Index into the voicing table: Sine, Organ, Reed, Flute, String, Triangle.
    Voicing(u8),
    /// Start a note at sample `start` of the synth's clock (see
    /// [`Synth::frames`]) and release it `frames` samples later. A start in
    /// the past sounds at once. `voicing` indexes the voicing table.
    NoteAt {
        hz: f32,
        velocity: f32,
        start: u64,
        frames: u32,
        voicing: u8,
    },
    /// Drop every scheduled note and release those already sounding.
    ClearScheduled,
    Master(f32),
    /// One metronome tick.
    Click {
        hz: f32,
        volume: f32,
    },
    /// Sample-accurate metronome. `bpm <= 0` stops it; starting it ticks at
    /// once. The first beat of each `beats_per_bar` is accented (0 = no accent).
    Metronome {
        bpm: f32,
        volume: f32,
        beats_per_bar: u8,
    },
}

#[derive(Clone, Copy, PartialEq)]
enum Stage {
    Dead,
    Attack,
    Sustain,
    Release,
    /// Percussive: exponential decay from full level, no sustain.
    Decay,
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Key,
    Ison,
    Click,
    /// A scheduled note; releases itself at `off_at`.
    Seq,
}

#[derive(Clone, Copy)]
struct Voice {
    kind: Kind,
    id: i32,
    hz: f32,
    velocity: f32,
    target_velocity: f32,
    amps: [f32; K],
    phases: [f32; K],
    env: f32,
    stage: Stage,
    age: u64,
    /// Clock sample at which a scheduled note releases.
    off_at: u64,
}

impl Voice {
    const DEAD: Voice = Voice {
        kind: Kind::Key,
        id: 0,
        hz: 0.0,
        velocity: 0.0,
        target_velocity: 0.0,
        amps: [0.0; K],
        phases: [0.0; K],
        env: 0.0,
        stage: Stage::Dead,
        age: 0,
        off_at: u64::MAX,
    };

    fn sounding(&self) -> bool {
        matches!(self.stage, Stage::Attack | Stage::Sustain)
    }
}

struct State {
    sample_rate: f32,
    voices: [Voice; MAX_VOICES],
    voicing: usize,
    master: f32,
    target_master: f32,
    clock: u64,
    metro: Option<Metro>,
    /// Samples rendered since the synth was created.
    now: u64,
    pending: [Pending; MAX_PENDING],
    pending_len: usize,
}

#[derive(Clone, Copy)]
struct Pending {
    hz: f32,
    velocity: f32,
    start: u64,
    frames: u32,
    voicing: u8,
}

struct Metro {
    interval: f64,
    /// Samples until the next tick (fractional so tempo does not drift).
    until_next: f64,
    volume: f32,
    beats_per_bar: u8,
    beat: u8,
}

const CLICK_HZ: f32 = 1000.0;
const CLICK_ACCENT_HZ: f32 = 1500.0;

/// Single-producer single-consumer ring of commands.
struct Queue {
    slots: [UnsafeCell<Cmd>; QUEUE_LEN],
    head: AtomicUsize,
    tail: AtomicUsize,
}

impl Queue {
    fn new() -> Self {
        Self {
            slots: core::array::from_fn(|_| UnsafeCell::new(Cmd::AllNotesOff)),
            head: AtomicUsize::new(0),
            tail: AtomicUsize::new(0),
        }
    }

    /// Producer side. Returns false when full (the command is dropped).
    fn push(&self, cmd: Cmd) -> bool {
        let tail = self.tail.load(Ordering::Relaxed);
        let next = (tail + 1) % QUEUE_LEN;
        if next == self.head.load(Ordering::Acquire) {
            return false;
        }
        // SAFETY: only the single producer writes this slot, and the consumer
        // does not read it until `tail` is published below.
        unsafe { *self.slots[tail].get() = cmd };
        self.tail.store(next, Ordering::Release);
        true
    }

    /// Consumer side.
    fn pop(&self) -> Option<Cmd> {
        let head = self.head.load(Ordering::Relaxed);
        if head == self.tail.load(Ordering::Acquire) {
            return None;
        }
        // SAFETY: the producer finished writing this slot before publishing `tail`.
        let cmd = unsafe { *self.slots[head].get() };
        self.head.store((head + 1) % QUEUE_LEN, Ordering::Release);
        Some(cmd)
    }
}

/// The synthesizer. One thread may call [`send`](Self::send) while another
/// calls [`render`](Self::render); neither side may be shared further.
pub struct Synth {
    queue: Queue,
    frames: AtomicU64,
    state: UnsafeCell<State>,
}

// SAFETY: `queue` is a lock-free SPSC ring and `state` is touched only by the
// single rendering thread, per the contract on `Synth`.
unsafe impl Sync for Synth {}
unsafe impl Send for Synth {}

impl Synth {
    pub fn new(sample_rate: f32) -> Self {
        Self {
            queue: Queue::new(),
            frames: AtomicU64::new(0),
            state: UnsafeCell::new(State {
                sample_rate,
                voices: [Voice::DEAD; MAX_VOICES],
                voicing: 1,
                master: 0.8,
                target_master: 0.8,
                clock: 0,
                metro: None,
                now: 0,
                pending: [Pending {
                    hz: 0.0,
                    velocity: 0.0,
                    start: 0,
                    frames: 0,
                    voicing: 0,
                }; MAX_PENDING],
                pending_len: 0,
            }),
        }
    }

    /// Queue a command from the control thread. Returns false if the queue is full.
    pub fn send(&self, cmd: Cmd) -> bool {
        self.queue.push(cmd)
    }

    /// Render mono audio into `out`, overwriting it. Audio thread only.
    pub fn render(&self, out: &mut [f32]) {
        // SAFETY: only the rendering thread reaches `state` (see `Synth` docs).
        let state = unsafe { &mut *self.state.get() };
        while let Some(cmd) = self.queue.pop() {
            state.apply(cmd);
        }
        state.render(out);
        self.frames.store(state.now, Ordering::Release);
    }

    /// The synth's clock: samples rendered so far, as of the last completed
    /// render call. Any thread. `NoteAt` start times are on this clock.
    pub fn frames(&self) -> u64 {
        self.frames.load(Ordering::Acquire)
    }
}

impl State {
    fn apply(&mut self, cmd: Cmd) {
        match cmd {
            Cmd::NoteOn { id, hz, velocity } => {
                self.release_where(|v| v.kind == Kind::Key && v.id == id);
                let amps = normalised(VOICINGS[self.voicing].0);
                self.start(Kind::Key, id, hz, velocity, amps, Stage::Attack);
            }
            Cmd::NoteOff { id } => self.release_where(|v| v.kind == Kind::Key && v.id == id),
            Cmd::Retune { id, hz } => {
                for v in self.voices.iter_mut() {
                    if v.kind == Kind::Key && v.id == id && v.stage != Stage::Dead {
                        v.hz = hz;
                    }
                }
            }
            Cmd::AllNotesOff => self.release_where(|v| v.kind == Kind::Key),
            Cmd::Ison { hz, volume } => {
                if volume <= 0.0 || hz <= 0.0 {
                    self.release_where(|v| v.kind == Kind::Ison);
                    return;
                }
                // Same drone pitch: retarget the level so no new attack is heard.
                if let Some(v) = self
                    .voices
                    .iter_mut()
                    .find(|v| v.kind == Kind::Ison && v.sounding() && (v.hz - hz).abs() < 1e-3)
                {
                    v.target_velocity = volume;
                    return;
                }
                self.release_where(|v| v.kind == Kind::Ison);
                let amps = normalised(VOICINGS[self.voicing].1);
                self.start(Kind::Ison, 0, hz, volume, amps, Stage::Attack);
            }
            Cmd::Voicing(index) => {
                let index = index as usize;
                if index >= VOICINGS.len() || index == self.voicing {
                    return;
                }
                self.voicing = index;
                // Re-voice a live drone so the change is audible immediately.
                let live = self
                    .voices
                    .iter()
                    .find(|v| v.kind == Kind::Ison && v.sounding())
                    .map(|v| (v.hz, v.target_velocity));
                if let Some((hz, volume)) = live {
                    self.release_where(|v| v.kind == Kind::Ison);
                    let amps = normalised(VOICINGS[index].1);
                    self.start(Kind::Ison, 0, hz, volume, amps, Stage::Attack);
                }
            }
            Cmd::Master(level) => self.target_master = level.clamp(0.0, 1.5),
            Cmd::NoteAt {
                hz,
                velocity,
                start,
                frames,
                voicing,
            } => {
                // A full schedule drops the note rather than disturb the rest.
                if self.pending_len < MAX_PENDING && hz > 0.0 {
                    self.pending[self.pending_len] = Pending {
                        hz,
                        velocity,
                        start,
                        frames,
                        voicing,
                    };
                    self.pending_len += 1;
                }
            }
            Cmd::ClearScheduled => {
                self.pending_len = 0;
                self.release_where(|v| v.kind == Kind::Seq);
            }
            Cmd::Click { hz, volume } => {
                let mut amps = [0.0; K];
                amps[0] = 1.0;
                self.start(Kind::Click, 0, hz, volume, amps, Stage::Decay);
            }
            Cmd::Metronome {
                bpm,
                volume,
                beats_per_bar,
            } => {
                if bpm.is_nan() || bpm <= 0.0 {
                    self.metro = None;
                    return;
                }
                let interval = 60.0 * self.sample_rate as f64 / bpm.clamp(10.0, 400.0) as f64;
                match self.metro.as_mut() {
                    // Tempo or level change while running: keep the beat phase.
                    Some(m) => {
                        m.until_next = m.until_next.min(interval);
                        m.interval = interval;
                        m.volume = volume;
                        m.beats_per_bar = beats_per_bar;
                    }
                    None => {
                        self.metro = Some(Metro {
                            interval,
                            until_next: 0.0,
                            volume,
                            beats_per_bar,
                            beat: 0,
                        })
                    }
                }
            }
        }
    }

    /// Start every scheduled note that is due and return how many samples
    /// remain until the next one.
    fn start_due_notes(&mut self) -> Option<u64> {
        let now = self.now;
        let mut next: Option<u64> = None;
        let mut i = 0;
        while i < self.pending_len {
            let p = self.pending[i];
            if p.start > now {
                next = Some(next.map_or(p.start - now, |n| n.min(p.start - now)));
                i += 1;
                continue;
            }
            self.pending_len -= 1;
            self.pending[i] = self.pending[self.pending_len];
            let voicing = (p.voicing as usize).min(VOICINGS.len() - 1);
            let slot = self.start(
                Kind::Seq,
                0,
                p.hz,
                p.velocity,
                normalised(VOICINGS[voicing].0),
                Stage::Attack,
            );
            self.voices[slot].off_at = now + p.frames as u64;
        }
        next
    }

    /// Render `out`, splitting it at metronome ticks and scheduled note starts
    /// so each lands on its sample.
    fn render(&mut self, out: &mut [f32]) {
        let mut done = 0;
        while done < out.len() {
            let mut take = out.len() - done;
            let now = self.now;
            for v in self.voices.iter_mut() {
                if v.kind == Kind::Seq && v.sounding() {
                    if v.off_at <= now {
                        v.stage = Stage::Release;
                    } else {
                        take = take.min((v.off_at - now).min(usize::MAX as u64) as usize);
                    }
                }
            }
            if let Some(until) = self.start_due_notes() {
                take = take.min(until.min(usize::MAX as u64) as usize);
            }
            let mut tick = None;
            if let Some(m) = self.metro.as_mut() {
                if m.until_next < 1.0 {
                    let accent = m.beats_per_bar > 0 && m.beat == 0;
                    tick = Some((if accent { CLICK_ACCENT_HZ } else { CLICK_HZ }, m.volume));
                    m.until_next += m.interval;
                    m.beat = if m.beats_per_bar > 0 {
                        (m.beat + 1) % m.beats_per_bar
                    } else {
                        0
                    };
                }
                take = take.min(m.until_next.floor().max(1.0) as usize);
                m.until_next -= take as f64;
            }
            if let Some((hz, volume)) = tick {
                self.apply(Cmd::Click { hz, volume });
            }
            self.render_span(&mut out[done..done + take]);
            done += take;
            self.now += take as u64;
        }
    }

    fn release_where(&mut self, pred: impl Fn(&Voice) -> bool) {
        for v in self.voices.iter_mut() {
            if v.sounding() && pred(v) {
                v.stage = Stage::Release;
            }
        }
    }

    fn start(
        &mut self,
        kind: Kind,
        id: i32,
        hz: f32,
        velocity: f32,
        amps: [f32; K],
        stage: Stage,
    ) -> usize {
        // Steal order: a free slot, else the oldest releasing voice, else the oldest key.
        let slot = self
            .voices
            .iter()
            .position(|v| v.stage == Stage::Dead)
            .or_else(|| self.oldest(|v| matches!(v.stage, Stage::Release | Stage::Decay)))
            .or_else(|| self.oldest(|v| matches!(v.kind, Kind::Key | Kind::Seq)))
            .unwrap_or(0);
        self.clock += 1;
        self.voices[slot] = Voice {
            kind,
            id,
            hz,
            velocity,
            target_velocity: velocity,
            amps,
            phases: [0.0; K],
            env: if stage == Stage::Decay { 1.0 } else { 0.0 },
            stage,
            age: self.clock,
            off_at: u64::MAX,
        };
        slot
    }

    fn oldest(&self, pred: impl Fn(&Voice) -> bool) -> Option<usize> {
        self.voices
            .iter()
            .enumerate()
            .filter(|(_, v)| pred(v))
            .min_by_key(|(_, v)| v.age)
            .map(|(i, _)| i)
    }

    fn render_span(&mut self, out: &mut [f32]) {
        out.fill(0.0);
        let sr = self.sample_rate;
        let attack_inc = 1.0 / (ATTACK_S * sr);
        let release_inc = 1.0 / (RELEASE_S * sr);
        let vel_step = 1.0 / (VEL_RAMP_S * sr);
        let click_decay = (-1.0 / (CLICK_DECAY_S * sr)).exp();
        let nyquist = sr * 0.5;

        for v in self.voices.iter_mut() {
            if v.stage == Stage::Dead {
                continue;
            }
            // Partials at or above Nyquist would alias; drop them for this block.
            let partials = (1..=K).take_while(|k| v.hz * (*k as f32) < nyquist).count();
            for sample in out.iter_mut() {
                match v.stage {
                    Stage::Attack => {
                        v.env += attack_inc;
                        if v.env >= 1.0 {
                            v.env = 1.0;
                            v.stage = Stage::Sustain;
                        }
                    }
                    Stage::Release => {
                        v.env -= release_inc;
                        if v.env <= 0.0 {
                            v.stage = Stage::Dead;
                            break;
                        }
                    }
                    Stage::Decay => {
                        v.env *= click_decay;
                        if v.env < 1e-4 {
                            v.stage = Stage::Dead;
                            break;
                        }
                    }
                    Stage::Sustain | Stage::Dead => {}
                }
                let dv = v.target_velocity - v.velocity;
                if dv > vel_step {
                    v.velocity += vel_step;
                } else if dv < -vel_step {
                    v.velocity -= vel_step;
                } else {
                    v.velocity = v.target_velocity;
                }

                let mut s = 0.0;
                for k in 0..partials {
                    s += v.amps[k] * (core::f32::consts::TAU * v.phases[k]).sin();
                    v.phases[k] += v.hz * (k as f32 + 1.0) / sr;
                    if v.phases[k] >= 1.0 {
                        v.phases[k] -= v.phases[k].floor();
                    }
                }
                *sample += s * v.velocity * v.env;
            }
        }

        let master_step = 1.0 / (VEL_RAMP_S * sr);
        for sample in out.iter_mut() {
            let dm = self.target_master - self.master;
            self.master += dm.clamp(-master_step, master_step);
            *sample = soft_clip(*sample * self.master * MIX_GAIN);
        }
    }
}

/// Transparent below ±0.8, then a smooth knee that never exceeds ±1.
fn soft_clip(x: f32) -> f32 {
    const KNEE: f32 = 0.8;
    let a = x.abs();
    if a <= KNEE {
        return x;
    }
    let over = (a - KNEE) / (1.0 - KNEE);
    x.signum() * (KNEE + (1.0 - KNEE) * (over / (1.0 + over)))
}

#[cfg(test)]
mod tests {
    use super::*;

    const SR: f32 = 48_000.0;

    fn render(synth: &Synth, frames: usize) -> Vec<f32> {
        let mut out = vec![0.0; frames];
        for block in out.chunks_mut(256) {
            synth.render(block);
        }
        out
    }

    fn peak(samples: &[f32]) -> f32 {
        samples.iter().fold(0.0, |m, s| m.max(s.abs()))
    }

    /// Zero crossings per second, a cheap fundamental estimate for a sine.
    fn crossings_hz(samples: &[f32]) -> f32 {
        let n = samples
            .windows(2)
            .filter(|w| w[0] <= 0.0 && w[1] > 0.0)
            .count();
        n as f32 * SR / samples.len() as f32
    }

    #[test]
    fn silent_until_a_note_starts() {
        let synth = Synth::new(SR);
        assert_eq!(peak(&render(&synth, 4800)), 0.0);
    }

    #[test]
    fn note_on_sounds_at_pitch_and_note_off_decays_to_silence() {
        let synth = Synth::new(SR);
        synth.send(Cmd::Voicing(0));
        synth.send(Cmd::NoteOn {
            id: 0,
            hz: 220.0,
            velocity: 0.8,
        });
        let held = render(&synth, 48_000);
        assert!(peak(&held) > 0.2);
        assert!((crossings_hz(&held) - 220.0).abs() < 2.0);

        synth.send(Cmd::NoteOff { id: 0 });
        render(&synth, 9600); // > release time
        assert_eq!(peak(&render(&synth, 4800)), 0.0);
    }

    #[test]
    fn retune_moves_a_held_note() {
        let synth = Synth::new(SR);
        synth.send(Cmd::Voicing(0));
        synth.send(Cmd::NoteOn {
            id: 12,
            hz: 220.0,
            velocity: 0.8,
        });
        render(&synth, 4800);
        synth.send(Cmd::Retune { id: 12, hz: 330.0 });
        assert!((crossings_hz(&render(&synth, 48_000)) - 330.0).abs() < 2.0);
    }

    #[test]
    fn ison_sustains_across_key_releases() {
        let synth = Synth::new(SR);
        synth.send(Cmd::Ison {
            hz: 130.81,
            volume: 0.5,
        });
        synth.send(Cmd::NoteOn {
            id: 1,
            hz: 261.6,
            velocity: 0.8,
        });
        render(&synth, 4800);
        synth.send(Cmd::AllNotesOff);
        render(&synth, 9600);
        assert!(peak(&render(&synth, 4800)) > 0.05, "drone must survive");
        synth.send(Cmd::Ison {
            hz: 0.0,
            volume: 0.0,
        });
        render(&synth, 9600);
        assert_eq!(peak(&render(&synth, 4800)), 0.0);
    }

    #[test]
    fn click_is_short() {
        let synth = Synth::new(SR);
        synth.send(Cmd::Click {
            hz: 1500.0,
            volume: 0.8,
        });
        assert!(peak(&render(&synth, 480)) > 0.1);
        render(&synth, 24_000);
        assert_eq!(peak(&render(&synth, 4800)), 0.0);
    }

    #[test]
    fn metronome_ticks_on_the_sample_grid() {
        let synth = Synth::new(SR);
        synth.send(Cmd::Metronome {
            bpm: 120.0,
            volume: 0.8,
            beats_per_bar: 4,
        });
        let out = render(&synth, 2 * 48_000 + 100);
        // A tick is the first loud sample after a stretch of silence.
        let mut onsets = vec![];
        let mut quiet = 1000;
        for (i, s) in out.iter().enumerate() {
            if s.abs() > 0.02 {
                if quiet >= 1000 {
                    onsets.push(i);
                }
                quiet = 0;
            } else {
                quiet += 1;
            }
        }
        assert_eq!(onsets.len(), 5, "{onsets:?}");
        for (n, onset) in onsets.iter().enumerate() {
            assert!(onset.abs_diff(n * 24_000) <= 16, "tick {n} at {onset}");
        }

        synth.send(Cmd::Metronome {
            bpm: 0.0,
            volume: 0.0,
            beats_per_bar: 0,
        });
        render(&synth, 24_000);
        assert_eq!(peak(&render(&synth, 48_000)), 0.0);
    }

    #[test]
    fn scheduled_notes_start_and_stop_on_their_samples() {
        let synth = Synth::new(SR);
        render(&synth, 1000);
        assert_eq!(synth.frames(), 1000);
        synth.send(Cmd::NoteAt {
            hz: 440.0,
            velocity: 0.8,
            start: 5000,
            frames: 9600,
            voicing: 0,
        });
        let out = render(&synth, 30_000); // clock 1000..31000
        let first = out.iter().position(|s| s.abs() > 1e-4).unwrap() + 1000;
        assert!((5000..5004).contains(&first), "started at {first}");
        // Released at 14600, silent after the 80 ms release.
        let last = out.iter().rposition(|s| s.abs() > 1e-4).unwrap() + 1000;
        assert!(
            (14_600 + 3700..14_600 + 3845).contains(&last),
            "ended at {last}"
        );
        assert!((crossings_hz(&out[4000..13_600]) - 440.0).abs() < 3.0);
    }

    #[test]
    fn clearing_the_schedule_silences_pending_and_sounding_notes() {
        let synth = Synth::new(SR);
        for (i, start) in [0u64, 48_000].into_iter().enumerate() {
            synth.send(Cmd::NoteAt {
                hz: 220.0 * (i + 1) as f32,
                velocity: 0.8,
                start,
                frames: 96_000,
                voicing: 5,
            });
        }
        assert!(peak(&render(&synth, 4800)) > 0.1);
        synth.send(Cmd::ClearScheduled);
        render(&synth, 9600);
        assert_eq!(peak(&render(&synth, 96_000)), 0.0);
    }

    #[test]
    fn output_never_exceeds_full_scale() {
        let synth = Synth::new(SR);
        for id in 0..40 {
            synth.send(Cmd::NoteOn {
                id,
                hz: 110.0 + 13.0 * id as f32,
                velocity: 1.0,
            });
        }
        synth.send(Cmd::Master(1.5));
        assert!(peak(&render(&synth, 48_000)) <= 1.0);
    }

    #[test]
    fn a_full_queue_drops_instead_of_blocking() {
        let synth = Synth::new(SR);
        let accepted = (0..QUEUE_LEN * 2)
            .filter(|&i| synth.send(Cmd::NoteOff { id: i as i32 }))
            .count();
        assert_eq!(accepted, QUEUE_LEN - 1);
        render(&synth, 256);
        assert!(synth.send(Cmd::AllNotesOff));
    }
}
