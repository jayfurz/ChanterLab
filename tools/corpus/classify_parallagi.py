#!/usr/bin/env python3
"""Label a parallagi recording's note events with the trained syllable CNN —
the bootstrap for tapes where whisper produced nothing. Emits the same
events.jsonl shape as parallagi_dataset.py, so parallagi_align.py runs
unchanged downstream (its joint pitch+sequence DTW tolerates classifier
noise the same way it tolerates ASR noise).

Usage: classify_parallagi.py --audio X.wav --outdir DIR [--min-prob 0.35]
"""
import argparse, json, os, subprocess, sys
import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mcr'))
from train_parallagi import CLASSES, ParallagiCNN, load_wav, logmel, patch

DEGREE = {'ni': 0, 'pa': 1, 'vou': 2, 'ga': 3, 'di': 4, 'ke': 5, 'zo': 6, 'ne': 0}
MODEL = os.environ.get('PAR_CNN', '/mnt/data/chant-corpus/models/parallagi_cnn.pt')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--audio', required=True)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--min-prob', type=float, default=0.35)
    a = ap.parse_args()
    os.makedirs(os.path.join(a.outdir, 'tracks'), exist_ok=True)
    wav16 = os.path.join(a.outdir, 'tracks', 'audio_16k.wav')
    if not os.path.exists(wav16):
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', a.audio,
                        '-ac', '1', '-ar', '16000', wav16], check=True)
    vn_path = os.path.join(a.outdir, 'tracks', 'voice_notes.json')
    if not os.path.exists(vn_path):
        wav44 = os.path.join(a.outdir, 'tracks', 'audio_44k.wav')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', a.audio,
                        '-ac', '1', '-ar', '44100', wav44], check=True)
        subprocess.run([sys.executable, os.path.join(os.path.dirname(
            os.path.abspath(__file__)), '..', 'mcr', 'segment_tracks.py'),
            wav44, os.path.join(a.outdir, 'tracks')], check=True)
    vn = json.load(open(vn_path))
    x, sr = load_wav(wav16)
    mel = logmel(x, sr)
    ckpt = torch.load(MODEL, map_location='cpu', weights_only=False)
    net = ParallagiCNN()
    net.load_state_dict(ckpt['state_dict'] if 'state_dict' in ckpt else ckpt)
    net.eval()
    rows = []
    with torch.no_grad():
        for v in vn:
            t_c = (v[0] + v[1]) / 2
            p = patch(mel, t_c)
            logits = net(torch.tensor(p)[None, None].float())
            prob = torch.softmax(logits, 1)[0].numpy()
            i = int(prob.argmax())
            if prob[i] < a.min_prob:
                continue
            syl = CLASSES[i]
            rows.append({'t0': v[0], 't1': v[1], 'syllable': syl,
                         'degree': DEGREE[syl], 'cents': v[2],
                         'word': None, 'overlap': round(float(prob[i]), 3),
                         'source': 'cnn'})
    with open(os.path.join(a.outdir, 'events.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    print(f"{len(rows)}/{len(vn)} events labeled by CNN -> {a.outdir}")

if __name__ == '__main__':
    main()
