#!/usr/bin/env python3
"""Build a parallagi (sung-solfege) syllable dataset from one recording.

Pipeline:
  audio (m4a/mp3/wav) --ffmpeg--> mono 16k s16 wav
                      --tools/mcr/segment_tracks.py--> note events + cents track
  whisper JSON (word timestamps) --> normalized Greek words
  each note event -> max-time-overlap whisper word -> degree lexicon lookup

Outputs in --outdir:
  audio_16k.wav        (converted audio, reused if already present)
  tracks/              (segment_tracks.py outputs: voice_notes.json, *.npy)
  events.jsonl         rows: {t0,t1,syllable,degree,cents,word,overlap}
  summary.json         coverage %, per-syllable counts, paths

Usage:
  python3 parallagi_dataset.py --audio REC.m4a --whisper REC.json --outdir OUT
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

MCR_DIR = Path(__file__).resolve().parent.parent / "mcr"

# ---------------------------------------------------------------- classes ---
# 8-way: the seven diatonic degree names plus the melisma/repeat syllable ne.
CLASSES = ["ni", "pa", "vou", "ga", "di", "ke", "zo", "ne"]
DEGREE = {"ni": 0, "pa": 1, "vou": 2, "ga": 3, "di": 4, "ke": 5, "zo": 6,
          "ne": -1}

GREEK_VOWELS = set("αεηιουω")
LATIN_VOWELS = set("aeiou")


def normalize_greek(w: str) -> str:
    """Lowercase, strip diacritics, final sigma -> sigma, letters only."""
    w = unicodedata.normalize("NFD", w)
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    w = w.lower().replace("ς", "σ")  # final sigma
    return "".join(c for c in w if c.isalpha())


def build_lexicon():
    """normalized form -> class name. Tolerant: common whisper misspellings,
    real-Greek-word confusions (kai/nai/pou/gia/ti), Latin transliterations."""
    raw = {
        "pa":  ["πα", "μπα", "πας", "pa", "ba", "pah"],
        "vou": ["βου", "βο", "μπου", "που", "βους", "vou", "vu", "bou", "bu",
                "voo"],
        "ga":  ["γα", "γκα", "για", "γας", "ga", "gha", "ya", "gah"],
        "di":  ["δι", "δη", "δει", "δυ", "ντι", "τι", "τη", "di", "dee", "di",
                "ti", "thi"],
        "ke":  ["κε", "και", "γκε", "κες", "ke", "kai", "keh", "ce"],
        "zo":  ["ζω", "ζο", "ζως", "σω", "zo", "zoh", "so"],
        "ni":  ["νη", "νι", "νει", "νυ", "ni", "nee", "ny"],
        "ne":  ["νε", "ναι", "νες", "ne", "nai", "neh"],
    }
    lex = {}
    for cls, forms in raw.items():
        for f in forms:
            lex[normalize_greek(f)] = cls
    return lex


def collapse_runs(w: str) -> str:
    return re.sub(r"(.)\1+", r"\1", w)


def lookup(word: str, lex) -> str | None:
    """Exact -> collapsed-repeats -> lexicon-prefix + pure-vowel tail."""
    n = normalize_greek(word)
    if not n:
        return None
    if n in lex:
        return lex[n]
    c = collapse_runs(n)
    if c in lex:
        return lex[c]
    for form in sorted(lex, key=len, reverse=True):
        if len(form) >= 2 and n.startswith(form):
            tail = set(n[len(form):])
            if tail and tail <= (GREEK_VOWELS | LATIN_VOWELS):
                return lex[form]
    return None


# ---------------------------------------------------------------- whisper ---
def load_whisper_words(path):
    """Tolerant reader for whisper/faster-whisper/whisperx JSON layouts.
    Returns [(t0, t1, raw_word), ...] sorted by t0."""
    d = json.load(open(path, encoding="utf-8"))
    out = []

    def eat(wlist):
        for w in wlist:
            if not isinstance(w, dict):
                continue
            txt = w.get("word", w.get("text", ""))
            t0, t1 = w.get("start"), w.get("end")
            if txt and t0 is not None and t1 is not None and t1 > t0:
                out.append((float(t0), float(t1), txt.strip()))

    if isinstance(d, dict):
        if isinstance(d.get("words"), list):
            eat(d["words"])
        for seg in d.get("segments", []) or []:
            if isinstance(seg, dict) and isinstance(seg.get("words"), list):
                eat(seg["words"])
    elif isinstance(d, list):  # bare list of segments or words
        eat(d)
        for seg in d:
            if isinstance(seg, dict) and isinstance(seg.get("words"), list):
                eat(seg["words"])
    out.sort(key=lambda x: x[0])
    return out


# ------------------------------------------------------------------ audio ---
def ensure_wav(audio: Path, outdir: Path) -> Path:
    """Return a mono 16 kHz s16 wav for `audio`, converting if needed."""
    wav = outdir / "audio_16k.wav"
    if wav.exists() and wav.stat().st_size > 44:
        return wav
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
           str(audio), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
           str(wav)]
    subprocess.run(cmd, check=True)
    return wav


def run_segmenter(wav: Path, tracks: Path) -> Path:
    notes = tracks / "voice_notes.json"
    if not notes.exists():
        subprocess.run([sys.executable, str(MCR_DIR / "segment_tracks.py"),
                        str(wav), str(tracks)], check=True)
    return notes


# ------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--whisper", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--pad", type=float, default=0.10,
                    help="pad (s) added to each word interval before overlap")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    wav = ensure_wav(Path(args.audio), outdir)
    notes_path = run_segmenter(wav, outdir / "tracks")
    notes = json.load(open(notes_path))
    words = load_whisper_words(args.whisper)

    lex = build_lexicon()
    events, counts = [], {c: 0 for c in CLASSES}
    n_lex_words = sum(1 for _, _, w in words if lookup(w, lex))

    for t0, t1, cents, _gap in notes:
        best, best_ov = None, 0.0
        for w0, w1, wtxt in words:
            if w0 - args.pad >= t1:
                break
            ov = min(t1, w1 + args.pad) - max(t0, w0 - args.pad)
            if ov > best_ov:
                best_ov, best = ov, wtxt
        cls = lookup(best, lex) if best else None
        if cls is None:
            continue
        counts[cls] += 1
        events.append({"t0": t0, "t1": t1, "syllable": cls,
                       "degree": DEGREE[cls], "cents": cents,
                       "word": best, "overlap": round(best_ov, 3)})

    with open(outdir / "events.jsonl", "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    summary = {
        "recording": Path(args.audio).stem,
        "audio": str(Path(args.audio).resolve()),
        "wav": str(wav.resolve()),
        "whisper": str(Path(args.whisper).resolve()),
        "n_note_events": len(notes),
        "n_matched_events": len(events),
        "coverage_pct": round(100.0 * len(events) / max(1, len(notes)), 1),
        "n_whisper_words": len(words),
        "n_lexicon_words": n_lex_words,
        "lexicon_size": len(lex),
        "per_syllable": counts,
    }
    json.dump(summary, open(outdir / "summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
