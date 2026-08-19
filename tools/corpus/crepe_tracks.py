#!/usr/bin/env python3
"""Noise-robust audio front-end for the tape corpus: optional ffmpeg afftdn
denoise -> torchcrepe f0 (neural, resists the fifth/octave autocorrelation
errors the static causes) -> voice_segment_ref segmentation rules.

Usage: crepe_tracks.py in.(m4a|wav) outdir [--no-denoise] [--device cuda|cpu]
  -> outdir/voice_notes.json, cents_track.npy, rms_track.npy, audio_16k.wav
"""
import json, os, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mcr'))
from mcrlib import segment_from_tracks

def main():
    inp, outdir = sys.argv[1], sys.argv[2]
    denoise = '--no-denoise' not in sys.argv
    dev = sys.argv[sys.argv.index('--device') + 1] if '--device' in sys.argv else 'cpu'
    os.makedirs(outdir, exist_ok=True)
    wav = os.path.join(outdir, 'audio_16k.wav')
    af = 'highpass=f=65,afftdn=nr=20:nf=-32,' if denoise else ''
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', inp,
                    '-af', af + 'aresample=16000', '-ac', '1', wav], check=True)
    import torch, torchcrepe, wave
    w = wave.open(wav, 'rb')
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    w.close()
    audio = torch.tensor(x)[None]
    hop = 160                                  # 10 ms @ 16 kHz
    f0, per = torchcrepe.predict(audio, 16000, hop, 70.0, 500.0, 'full',
                                 batch_size=512, device=dev, return_periodicity=True)
    per = torchcrepe.filter.median(per, 5)
    f0 = torchcrepe.filter.median(f0, 5)
    f0, per = f0[0].numpy(), per[0].numpy()
    # rms at the same hop
    nfr = len(f0)
    rms = np.array([float(np.sqrt(np.mean(x[i * hop:i * hop + 640] ** 2)))
                    for i in range(nfr)])
    voiced = (per > 0.45) & (rms > 0.004)
    cents = np.where(voiced, 1200 * np.log2(np.maximum(f0, 1) / 55.0), np.nan)
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    vn = segment_from_tracks(cents, db)
    np.save(os.path.join(outdir, 'cents_track.npy'), cents)
    np.save(os.path.join(outdir, 'rms_track.npy'), rms)
    json.dump(vn, open(os.path.join(outdir, 'voice_notes.json'), 'w'))
    print(f"{len(vn)} notes, {nfr} frames, voiced {100 * voiced.mean():.0f}% -> {outdir}")

if __name__ == '__main__':
    main()
