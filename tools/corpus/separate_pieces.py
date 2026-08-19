#!/usr/bin/env python3
"""Separate an hour-long Vasilikos service tape into pieces using its Whisper
transcript (Greek, word timestamps).

Method
  - flatten whisper words; silence gaps (> --gap s, default 2.5) between
    consecutive words are boundary candidates -> micro-chunks
  - per-word Byzantine degree-lexicon test (pa vou ga di ke zo ni, incl.
    whisper spelling variants and run-together tokens via DP decomposition);
    sliding-window smoothed fraction detects parallagi<->melos transitions
    that lack a long pause and splits chunks there
  - chunks classified parallagi / melos / speech / other by lexicon fraction
    and duration (speech = frac ~0 AND short: spoken hymn announcement),
    then same-kind neighbours closer than --merge-gap s are merged
  - output pieces.json; with --cut also per-piece mono 16-bit wavs via ffmpeg

Usage:
  separate_pieces.py AUDIO [TRANSCRIPT.json] [--cut] [--out DIR]
                     [--gap 2.5] [--merge-gap 8.0] [--pad 0.35]
  separate_pieces.py --selftest         # synthetic whisper-JSON fixture

TRANSCRIPT defaults to /mnt/data/chant-corpus/transcripts/<stem>.json.
Output defaults to /mnt/data/chant-corpus/pieces/<stem>/pieces.json.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata

PIECES_ROOT = "/mnt/data/chant-corpus/pieces"
TRANSCRIPTS_ROOT = "/mnt/data/chant-corpus/transcripts"

# ---------------------------------------------------------------- lexicon ---
# Byzantine parallagi degree names as Whisper tends to spell them (Greek,
# accents stripped downstream).  NOTE: TASK C keeps its own copy of this
# logic by design -- do not refactor into a shared import.
DEGREE_SYLLABLES = (
    "πα",        # pa
    "βου",  # vou
    "μπου",  # bou (whisper variant of vou)
    "γα",        # ga
    "γκα",  # gka (whisper variant of ga)
    "δι",        # di
    "ντι",  # nti (whisper variant of di)
    "κε",        # ke
    "και",  # kai (whisper often writes ke as the word 'and')
    "ζω",        # zo
    "ζο",        # zo variant
    "νη",        # ni (eta)
    "νι",        # ni (iota)
)
_GREEK_RE = re.compile(r"[^α-ω]")
_VOWELS = set("αεηιουω")


def normalize_token(raw):
    """Lowercase, strip accents/diacritics and non-Greek-letter chars,
    collapse letter runs of >=3 (sung elongation 'paaa' -> 'pa')."""
    s = unicodedata.normalize("NFD", raw.strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ς", "σ")  # final sigma
    s = _GREEK_RE.sub("", s)
    return re.sub(r"(.)\1{2,}", r"\1", s)


def is_degree_token(norm):
    """True if the normalized token decomposes fully into degree syllables
    (catches run-together 'pavouga')."""
    n = len(norm)
    if n < 2:
        return False
    ok = [False] * (n + 1)
    ok[0] = True
    for i in range(1, n + 1):
        for syl in DEGREE_SYLLABLES:
            L = len(syl)
            if i >= L and ok[i - L] and norm[i - L:i] == syl:
                ok[i] = True
                break
    return ok[n]


def is_neutral_token(norm):
    """Pure-vowel vocalise ('a', 'e', 'ou') -- ignored by the detector."""
    return len(norm) == 0 or all(c in _VOWELS for c in norm)


# ----------------------------------------------------------- whisper JSON ---
def load_words(transcript_path):
    """Flatten a whisper(-like) JSON into [{'w','t0','t1'}], sorted by time.
    Accepts openai-whisper / faster-whisper / whisperx shapes."""
    with open(transcript_path) as f:
        doc = json.load(f)
    raw = []
    if isinstance(doc, dict) and doc.get("segments"):
        for seg in doc["segments"]:
            for w in seg.get("words") or []:
                raw.append(w)
    if not raw and isinstance(doc, dict) and doc.get("words"):
        raw = doc["words"]
    words = []
    for w in raw:
        text = w.get("word", w.get("text", ""))
        t0 = w.get("start", w.get("t0"))
        t1 = w.get("end", w.get("t1"))
        if t0 is None or t1 is None or not str(text).strip():
            continue
        words.append({"w": str(text).strip(), "t0": float(t0), "t1": float(t1)})
    words.sort(key=lambda x: x["t0"])
    return words


# -------------------------------------------------------------- detection ---
def annotate(words):
    for w in words:
        n = normalize_token(w["w"])
        w["neutral"] = is_neutral_token(n)
        w["deg"] = (not w["neutral"]) and is_degree_token(n)
    return words


def smoothed_labels(words, half_window=6, thresh=0.45):
    """Per counted (non-neutral) word: sliding-window degree fraction and
    boolean label.  Returns list of (word_index, frac, label)."""
    counted = [i for i, w in enumerate(words) if not w["neutral"]]
    out = []
    for k, i in enumerate(counted):
        lo, hi = max(0, k - half_window), min(len(counted), k + half_window + 1)
        window = counted[lo:hi]
        frac = sum(1 for j in window if words[j]["deg"]) / len(window)
        out.append((i, frac, frac >= thresh))
    return out


def split_chunk_on_transition(words, chunk, min_run=8):
    """Split a chunk (list of word indices) where the smoothed degree label
    flips and stays flipped for >= min_run counted words (parallagi->melos
    with only a short breath between)."""
    sub = [words[i] for i in chunk]
    lab = smoothed_labels(sub)
    if len(lab) < 2 * min_run:
        return [chunk]
    runs = []  # (label, [positions into lab])
    for pos, (_, _, L) in enumerate(lab):
        if runs and runs[-1][0] == L:
            runs[-1][1].append(pos)
        else:
            runs.append((L, [pos]))
    # absorb short runs into their longer neighbour
    runs = [r for r in runs]
    merged = []
    for r in runs:
        if merged and (len(r[1]) < min_run or merged[-1][0] == r[0]):
            merged[-1] = (merged[-1][0], merged[-1][1] + r[1])
        elif not merged and len(r[1]) < min_run:
            merged.append(r)  # leading short run; next merge absorbs it
        else:
            merged.append(r)
    if merged and len(merged) >= 2 and len(merged[0][1]) < min_run:
        merged[1] = (merged[1][0], merged[0][1] + merged[1][1])
        merged = merged[1:]
    if len(merged) < 2:
        return [chunk]
    pieces, start = [], 0
    for r in merged[:-1]:
        cut_lab_pos = r[1][-1]          # last counted word of this run
        cut_word = lab[cut_lab_pos][0]  # index into sub
        pieces.append(chunk[start:cut_word + 1])
        start = cut_word + 1
    pieces.append(chunk[start:])
    return [p for p in pieces if p]


def classify(words, chunk, speech_max_dur=20.0,
             parallagi_min_frac=0.45, melos_max_frac=0.15):
    idx = [i for i in chunk if not words[i]["neutral"]]
    t0, t1 = words[chunk[0]]["t0"], words[chunk[-1]]["t1"]
    dur = t1 - t0
    frac = (sum(1 for i in idx if words[i]["deg"]) / len(idx)) if idx else 0.0
    if frac >= parallagi_min_frac:
        kind = "parallagi"
    elif frac <= melos_max_frac:
        kind = "speech" if dur <= speech_max_dur else "melos"
    else:
        kind = "other"
    return {"t0": round(t0, 2), "t1": round(t1, 2), "kind": kind,
            "head_text": " ".join(words[i]["w"] for i in chunk[:8]),
            "n_words": len(chunk), "lex_frac": round(frac, 3)}


def separate(words, gap=2.5, merge_gap=8.0, speech_max_dur=20.0):
    words = annotate(words)
    # 1. split at silence gaps
    chunks, cur = [], [0]
    for i in range(1, len(words)):
        if words[i]["t0"] - words[i - 1]["t1"] > gap:
            chunks.append(cur)
            cur = []
        cur.append(i)
    if cur:
        chunks.append(cur)
    # 2. absorb tiny chunks into the previous one
    absorbed = []
    for c in chunks:
        dur = words[c[-1]]["t1"] - words[c[0]]["t0"]
        if absorbed and (len(c) < 3 or dur < 1.5):
            absorbed[-1] += c
        else:
            absorbed.append(c)
    # 3. split chunks that change character mid-stream
    chunks = [p for c in absorbed for p in split_chunk_on_transition(words, c)]
    # 4. classify
    segs = [classify(words, c, speech_max_dur=speech_max_dur) for c in chunks]
    # 5. merge same-kind neighbours across short gaps
    merged = []
    for s, c in zip(segs, chunks):
        if merged and merged[-1][0]["kind"] == s["kind"] \
                and s["t0"] - merged[-1][0]["t1"] < merge_gap:
            prev_s, prev_c = merged[-1]
            merged[-1] = (classify(words, prev_c + c,
                                   speech_max_dur=speech_max_dur), prev_c + c)
            # keep original kind if re-classification wobbled on the merge
            merged[-1][0]["kind"] = prev_s["kind"]
        else:
            merged.append((s, c))
    return [s for s, _ in merged]


# ------------------------------------------------------------------ ffmpeg --
def cut_pieces(audio, segments, outdir, pad=0.35):
    written = []
    for i, s in enumerate(segments, 1):
        name = "%03d_%s.wav" % (i, s["kind"])
        out = os.path.join(outdir, name)
        t0 = max(0.0, s["t0"] - pad)
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "%.3f" % t0,
               "-to", "%.3f" % (s["t1"] + pad), "-i", audio,
               "-ac", "1", "-acodec", "pcm_s16le", out]
        subprocess.run(cmd, check=True)
        s["wav"] = name
        written.append(out)
    return written


# ---------------------------------------------------------------- fixture ---
def synthetic_fixture():
    """Whisper-shaped JSON exercising every rule: 2x (announcement,
    parallagi, melos); one 3.2s breath inside parallagi #1 (must merge
    back); parallagi #2 -> melos #2 separated by only 1.0s (must split via
    the sliding-window transition detector)."""
    deg = ["πα", "βου", "γα",
           "δι", "κε", "ζω", "νη"]
    hymn = ("Κύριε εκέκραξα "
            "προς σε εισάκουσόν "
            "μου πρόσχες τη "
            "φωνή της δεήσεώς "
            "μου και εν τω "
            "κεκραγέναι με").split()
    ann = ("Ήχος πρώτος "
           "Κύριε εκέκραξα "
           "εις τον ήχον").split()

    words, t = [], 0.5

    def emit(tokens, wdur, gap_after=0.0, internal=None):
        nonlocal t
        for k, tok in enumerate(tokens):
            words.append({"word": " " + tok, "start": round(t, 2),
                          "end": round(t + wdur, 2), "probability": 0.9})
            t += wdur + 0.15
            if internal and k == internal[0]:
                t += internal[1]
        t += gap_after

    emit(ann, 0.35, gap_after=4.0)                                   # speech 1
    emit((deg * 12)[:80], 0.65, gap_after=5.0, internal=(40, 3.2))   # parallagi 1 (+breath)
    emit((hymn * 6)[:100], 1.05, gap_after=6.0)                      # melos 1
    emit(ann, 0.35, gap_after=3.0)                                   # speech 2
    emit((deg * 6)[:40], 0.65, gap_after=1.0)                        # parallagi 2, SHORT gap
    emit((hymn * 4)[:70], 1.05)                                      # melos 2
    return {"text": "", "language": "el",
            "segments": [{"id": 0, "start": 0.0, "end": t, "text": "",
                          "words": words}]}


def run_selftest(outdir):
    os.makedirs(outdir, exist_ok=True)
    fix = os.path.join(outdir, "fixture_whisper.json")
    with open(fix, "w") as f:
        json.dump(synthetic_fixture(), f, ensure_ascii=False)
    segs = separate(load_words(fix))
    got = [s["kind"] for s in segs]
    want = ["speech", "parallagi", "melos", "speech", "parallagi", "melos"]
    ok = got == want
    out = {"fixture": fix, "expected": want, "got": got, "pass": ok,
           "segments": segs}
    with open(os.path.join(outdir, "pieces.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if ok else 1


# -------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", nargs="?", help="recording (mp3/m4a/wav)")
    ap.add_argument("transcript", nargs="?",
                    help="whisper JSON (default: transcripts/<stem>.json)")
    ap.add_argument("--cut", action="store_true",
                    help="also extract per-piece wavs with ffmpeg")
    ap.add_argument("--out", help="output dir (default pieces/<stem>/)")
    ap.add_argument("--gap", type=float, default=2.5,
                    help="silence gap boundary candidate, s")
    ap.add_argument("--merge-gap", type=float, default=8.0,
                    help="max gap merged between same-kind chunks, s")
    ap.add_argument("--speech-max-dur", type=float, default=20.0,
                    help="max duration of a spoken announcement, s")
    ap.add_argument("--pad", type=float, default=0.35, help="cut padding, s")
    ap.add_argument("--selftest", action="store_true",
                    help="validate on a synthetic whisper-JSON fixture")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(run_selftest(args.out or
                              os.path.join(PIECES_ROOT, "_selftest")))
    if not args.audio:
        ap.error("audio required (or --selftest)")
    stem = os.path.splitext(os.path.basename(args.audio))[0]
    transcript = args.transcript or os.path.join(TRANSCRIPTS_ROOT,
                                                 stem + ".json")
    if not os.path.exists(transcript):
        sys.exit("transcript not found: %s" % transcript)
    outdir = args.out or os.path.join(PIECES_ROOT, stem)
    os.makedirs(outdir, exist_ok=True)

    words = load_words(transcript)
    if not words:
        sys.exit("no timed words in %s" % transcript)
    segs = separate(words, gap=args.gap, merge_gap=args.merge_gap,
                    speech_max_dur=args.speech_max_dur)
    if args.cut:
        cut_pieces(args.audio, segs, outdir, pad=args.pad)
    doc = {"audio": os.path.abspath(args.audio),
           "transcript": os.path.abspath(transcript),
           "n_words": len(words),
           "params": {"gap": args.gap, "merge_gap": args.merge_gap,
                      "speech_max_dur": args.speech_max_dur},
           "segments": segs}
    path = os.path.join(outdir, "pieces.json")
    with open(path, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(path)
    for i, s in enumerate(segs, 1):
        print("%3d %9.1f %9.1f %-10s %.2f  %s"
              % (i, s["t0"], s["t1"], s["kind"], s["lex_frac"],
                 s["head_text"][:60]))


if __name__ == "__main__":
    main()
