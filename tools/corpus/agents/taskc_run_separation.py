#!/usr/bin/env python3
"""TASK C driver: run separate_pieces.py over the single-file hour-long
Vasilikos service recordings (dry run or --cut), then summarize pieces.json.

Usage:
  taskc_run_separation.py [--cut] [--only SUBSTR]
Run from the chant-annotator repo root.
"""
import argparse
import json
import os
import subprocess
import sys

SEP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "separate_pieces.py")
PIECES_ROOT = "/mnt/data/chant-corpus/pieces"

RECORDINGS = [
    "/mnt/data/chant-corpus/raw/vasilikos/Mode Plagal 1st/Mode Plagal 1st Hymns of Compunction.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 2/Theophany Double Canon.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 4/Mode 4 cherubic hymn  phokaeos.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 2/Mode 2 Theophany Double Canon Vasilikos.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 4/Mode 4 Eothinon Melos Vasilikos.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 2/Mode 2 doxology nativity vasilikos + oinoussai.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 3/mode 3 meeting of the lord canon vasilikos.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 3/Mode 3 Cherubic Hymn Phokaeos.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 2/Mode 2 Anastasimatarion 1 Vespers.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 4/Mode 4 Anastasimatarion 1 Vespers.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 3/mode 3 Anastasimatarion 1 vespers vasilikos.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode Plagal 2nd/Mode Plagal 2nd Anastasimatarion 1 Vespers.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/Mode Grave Anastasimatarion 1 Vespers.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode Plagal 4th/Mode Plagal 4th Anastasimatarion 1 Vespers.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode 1/Mode 1 Anastasimatarion 1 Vespers Vasilikos.mp3",
    "/mnt/data/chant-corpus/raw/vasilikos/Unknown Album/Prosomia 8 and exoposteilaria.m4a",
    "/mnt/data/chant-corpus/raw/vasilikos/Mode Grave/Mode Grave Anastasimatarion Vespers and Orthros.mp3",
]


def summarize(stem):
    pj = os.path.join(PIECES_ROOT, stem, "pieces.json")
    if not os.path.exists(pj):
        return None
    data = json.load(open(pj))
    pieces = data["segments"]
    kinds = {}
    durs = []
    tiny = 0
    huge = 0
    for p in pieces:
        k = p.get("kind", "?")
        dur = float(p["t1"]) - float(p["t0"])
        kinds[k] = kinds.get(k, 0) + 1
        durs.append((k, dur))
        if k in ("parallagi", "melos"):
            if dur < 30:
                tiny += 1
            if dur > 480:
                huge += 1
    total = sum(d for _, d in durs)
    sung = sum(d for k, d in durs if k in ("parallagi", "melos"))
    return {
        "stem": stem,
        "n": len(pieces),
        "kinds": kinds,
        "total_s": round(total, 1),
        "sung_s": round(sung, 1),
        "tiny_lt30s": tiny,
        "huge_gt8min": huge,
        "seq": [(k, round(d / 60, 2)) for k, d in durs],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args()
    for audio in RECORDINGS:
        stem = os.path.splitext(os.path.basename(audio))[0]
        if args.only and args.only.lower() not in stem.lower():
            continue
        cmd = [sys.executable, SEP, audio]
        if args.cut:
            cmd.append("--cut")
        r = subprocess.run(cmd, capture_output=True, text=True)
        status = "ok" if r.returncode == 0 else "FAIL rc=%d" % r.returncode
        print("== %s [%s]" % (stem, status))
        if r.returncode != 0:
            print(r.stdout[-1500:])
            print(r.stderr[-1500:])
            continue
        s = summarize(stem)
        print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
