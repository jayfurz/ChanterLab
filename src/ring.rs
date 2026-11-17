//! Lock-free single-producer single-consumer ring of audio samples.
//!
//! Recording taps the audio threads through these: a render or capture
//! callback pushes without ever blocking, and a writer thread drains at its
//! leisure. When the writer falls behind, new samples are dropped (and
//! counted) rather than overwriting what it has not read yet.

use core::cell::UnsafeCell;
use core::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

pub struct Ring {
    data: Box<[UnsafeCell<f32>]>,
    head: AtomicUsize,
    tail: AtomicUsize,
    dropped: AtomicU64,
}

// SAFETY: one thread pushes and one pops; they touch disjoint slots, handed
// over through the atomics.
unsafe impl Sync for Ring {}
unsafe impl Send for Ring {}

impl Ring {
    /// A ring holding up to `capacity` samples.
    pub fn new(capacity: usize) -> Self {
        Self {
            data: (0..capacity.max(1) + 1)
                .map(|_| UnsafeCell::new(0.0))
                .collect(),
            head: AtomicUsize::new(0),
            tail: AtomicUsize::new(0),
            dropped: AtomicU64::new(0),
        }
    }

    /// Samples waiting to be read.
    pub fn len(&self) -> usize {
        let n = self.data.len();
        (self.tail.load(Ordering::Acquire) + n - self.head.load(Ordering::Acquire)) % n
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Samples the producer had to drop because the ring was full.
    pub fn dropped(&self) -> u64 {
        self.dropped.load(Ordering::Relaxed)
    }

    /// Producer: append as much of `samples` as fits. Returns how many were stored.
    pub fn push(&self, samples: &[f32]) -> usize {
        let n = self.data.len();
        let tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);
        let free = (head + n - tail - 1) % n;
        let count = samples.len().min(free);
        for (i, &sample) in samples[..count].iter().enumerate() {
            // SAFETY: slots between tail and head belong to the producer.
            unsafe { *self.data[(tail + i) % n].get() = sample };
        }
        self.tail.store((tail + count) % n, Ordering::Release);
        if count < samples.len() {
            self.dropped
                .fetch_add((samples.len() - count) as u64, Ordering::Relaxed);
        }
        count
    }

    /// Consumer: move up to `out.len()` samples into `out`. Returns how many.
    pub fn pop(&self, out: &mut [f32]) -> usize {
        let n = self.data.len();
        let head = self.head.load(Ordering::Relaxed);
        let available = (self.tail.load(Ordering::Acquire) + n - head) % n;
        let count = out.len().min(available);
        for (i, slot) in out[..count].iter_mut().enumerate() {
            // SAFETY: slots between head and tail belong to the consumer.
            *slot = unsafe { *self.data[(head + i) % n].get() };
        }
        self.head.store((head + count) % n, Ordering::Release);
        count
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_order_across_the_wrap() {
        let ring = Ring::new(8);
        let mut out = [0.0; 8];
        let mut next = 0.0;
        let mut expect = 0.0;
        for _ in 0..50 {
            let block: Vec<f32> = (0..5).map(|i| next + i as f32).collect();
            assert_eq!(ring.push(&block), 5);
            next += 5.0;
            let got = ring.pop(&mut out);
            assert_eq!(got, 5);
            for value in &out[..got] {
                assert_eq!(*value, expect);
                expect += 1.0;
            }
        }
        assert!(ring.is_empty());
    }

    #[test]
    fn a_full_ring_drops_new_samples_and_counts_them() {
        let ring = Ring::new(4);
        assert_eq!(ring.push(&[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), 4);
        assert_eq!(ring.dropped(), 2);
        let mut out = [0.0; 8];
        assert_eq!(ring.pop(&mut out), 4);
        assert_eq!(&out[..4], &[1.0, 2.0, 3.0, 4.0]);
    }

    #[test]
    fn two_threads_lose_nothing() {
        let ring = std::sync::Arc::new(Ring::new(1024));
        let producer = {
            let ring = ring.clone();
            std::thread::spawn(move || {
                let mut sent = 0u32;
                while sent < 200_000 {
                    let block: Vec<f32> =
                        (sent..(sent + 64).min(200_000)).map(|v| v as f32).collect();
                    let stored = ring.push(&block);
                    sent += stored as u32;
                    if stored == 0 {
                        std::thread::yield_now();
                    }
                }
            })
        };
        let mut expect = 0u32;
        let mut out = [0.0; 256];
        while expect < 200_000 {
            let got = ring.pop(&mut out);
            for value in &out[..got] {
                assert_eq!(*value, expect as f32);
                expect += 1;
            }
        }
        producer.join().unwrap();
    }
}
