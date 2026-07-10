#!/usr/bin/env python3
"""score_extraction.py — OMR bake-off judge.

Scores a candidate MusicXML (from oemer / Audiveris / vector_extract) against
the hand-encoded ground truth (ground_truth/*.json — sounding pitches,
durations in quarter beats, per SATB voice, per measure).

Metrics:
  * per-voice note recall / precision      (LCS alignment on MIDI sequence)
  * duration accuracy among matched notes  (|dur - gt| < 1/64 beat)
  * voice-assignment accuracy              (GT notes recovered in the right part)
  * global pitch recall / precision        (voice-agnostic multiset — how much
                                            music was found at all, useful for
                                            voice-collapsed outputs)
  * measure integrity                      (measures recovered vs GT; GT
                                            measure lengths reproduced)

Usage:
  .venv/bin/python score_extraction.py ground_truth/trisagion_p2_gt.json \
      out/vector/trisagion_p2_vector.musicxml --label vector
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter

STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
VOICES = ["S", "A", "T", "B"]


def midi_of(step, octave, alter):
    return 12 * (octave + 1) + STEP_SEMITONE[step] + alter


def parse_gt(path):
    gt = json.load(open(path))
    out = {}
    for v, data in gt["voices"].items():
        seq = []
        for mi, measure in enumerate(data["measures"]):
            for pitch, beats in measure:
                step = pitch[0]
                rest = pitch[1:]
                alter = 0
                if rest.startswith("#"):
                    alter, rest = 1, rest[1:]
                elif rest.startswith("b"):
                    alter, rest = -1, rest[1:]
                elif rest.startswith("n"):
                    alter, rest = 0, rest[1:]
                octave = int(rest)
                seq.append({"midi": midi_of(step, octave, alter),
                            "beats": float(beats), "measure": mi + 1})
        out[v] = seq
    n_measures = max(len(d["measures"]) for d in gt["voices"].values())
    m_sums = []
    for mi in range(n_measures):
        sums = {v: round(sum(b for _, b in gt["voices"][v]["measures"][mi]), 4)
                for v in gt["voices"]}
        m_sums.append(sums)
    return out, n_measures, m_sums


def parse_candidate(path, max_measures=None):
    """MusicXML (partwise) -> parts: [{name, notes:[{midi,beats,measure}...],
    measure_sums:{m:beats}}]. Honors key signature + measure accidental
    memory when <alter> is absent (defensive against sloppy exporters)."""
    tree = ET.parse(path)
    root = tree.getroot()
    names = {}
    for sp in root.iter("score-part"):
        pn = sp.find("part-name")
        names[sp.get("id")] = (pn.text or "").strip() if pn is not None else ""
    parts = []
    for part in root.iter("part"):
        divisions = 1
        fifths = 0
        notes = []
        measure_sums = {}
        for mi, measure in enumerate(part.findall("measure")):
            mnum = mi + 1
            if max_measures and mnum > max_measures:
                break
            memory = {}
            cursor = 0.0
            max_cursor = 0.0
            for el in measure:
                if el.tag == "attributes":
                    d = el.find("divisions")
                    if d is not None:
                        divisions = int(d.text)
                    f = el.find("key/fifths")
                    if f is not None:
                        fifths = int(f.text)
                elif el.tag == "backup":
                    cursor -= float(el.find("duration").text) / divisions
                elif el.tag == "forward":
                    cursor += float(el.find("duration").text) / divisions
                elif el.tag == "note":
                    dur_el = el.find("duration")
                    beats = float(dur_el.text) / divisions if dur_el is not None else 0.0
                    is_chord = el.find("chord") is not None
                    pitch = el.find("pitch")
                    if pitch is not None:
                        step = pitch.find("step").text.strip()
                        octave = int(pitch.find("octave").text)
                        alt_el = pitch.find("alter")
                        if alt_el is not None:
                            alter = int(round(float(alt_el.text)))
                            memory[(step, octave)] = alter
                        else:
                            acc = el.find("accidental")
                            if acc is not None:
                                alter = {"sharp": 1, "flat": -1,
                                         "natural": 0}.get(acc.text.strip(), 0)
                                memory[(step, octave)] = alter
                            elif (step, octave) in memory:
                                alter = memory[(step, octave)]
                            else:
                                keymap = {}
                                if fifths > 0:
                                    for s in SHARP_ORDER[:fifths]:
                                        keymap[s] = 1
                                elif fifths < 0:
                                    for s in FLAT_ORDER[:-fifths]:
                                        keymap[s] = -1
                                alter = keymap.get(step, 0)
                        notes.append({"midi": midi_of(step, octave, alter),
                                      "beats": beats, "measure": mnum})
                    if not is_chord:
                        cursor += beats
                        max_cursor = max(max_cursor, cursor)
            measure_sums[mnum] = round(max_cursor, 4)
        parts.append({"id": part.get("id"),
                      "name": names.get(part.get("id"), part.get("id")),
                      "notes": notes, "measure_sums": measure_sums})
    return parts


def lcs_pairs(a, b):
    """LCS on midi values; returns list of (i, j) matched index pairs."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    pairs = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def score(gt_path, xml_path, label, max_measures=None):
    gt, n_gt_measures, gt_sums = parse_gt(gt_path)
    if max_measures is None:
        max_measures = n_gt_measures
    parts = parse_candidate(xml_path, max_measures=max_measures)

    # assign candidate parts to GT voices (maximize LCS, greedy over all pairs)
    scores = []
    for pi, p in enumerate(parts):
        cand_seq = [n["midi"] for n in p["notes"]]
        for v in VOICES:
            if v not in gt:
                continue
            pairs = lcs_pairs(cand_seq, [n["midi"] for n in gt[v]])
            scores.append((len(pairs), pi, v))
    scores.sort(reverse=True)
    assign = {}
    used_p, used_v = set(), set()
    for sc, pi, v in scores:
        if pi in used_p or v in used_v or sc == 0:
            continue
        assign[v] = pi
        used_p.add(pi)
        used_v.add(v)

    result = {"label": label, "xml": xml_path,
              "candidate_parts": len(parts),
              "part_names": [p["name"] for p in parts],
              "per_voice": {}, "assigned": {v: parts[pi]["name"]
                                            for v, pi in assign.items()}}

    total_gt = sum(len(gt[v]) for v in gt)
    total_matched = 0
    total_dur_ok = 0
    total_cand_assigned = 0
    for v in gt:
        gt_seq = gt[v]
        if v not in assign:
            result["per_voice"][v] = {"recall": 0.0, "precision": 0.0,
                                      "dur_acc": 0.0, "gt_notes": len(gt_seq),
                                      "cand_notes": 0, "matched": 0}
            continue
        p = parts[assign[v]]
        pairs = lcs_pairs([n["midi"] for n in p["notes"]],
                          [n["midi"] for n in gt_seq])
        matched = len(pairs)
        dur_ok = sum(1 for (ci, gi) in pairs
                     if abs(p["notes"][ci]["beats"] - gt_seq[gi]["beats"]) < 1 / 64)
        result["per_voice"][v] = {
            "recall": round(matched / len(gt_seq), 4),
            "precision": round(matched / len(p["notes"]), 4) if p["notes"] else 0.0,
            "dur_acc": round(dur_ok / matched, 4) if matched else 0.0,
            "gt_notes": len(gt_seq), "cand_notes": len(p["notes"]),
            "matched": matched}
        total_matched += matched
        total_dur_ok += dur_ok
        total_cand_assigned += len(p["notes"])

    result["voice_note_recall"] = round(total_matched / total_gt, 4)
    result["voice_note_precision"] = (round(total_matched / total_cand_assigned, 4)
                                      if total_cand_assigned else 0.0)
    result["dur_acc_overall"] = (round(total_dur_ok / total_matched, 4)
                                 if total_matched else 0.0)

    # global voice-agnostic pitch multiset (was the music found at all?)
    gt_pitches = Counter()
    for v in gt:
        gt_pitches.update(n["midi"] for n in gt[v])
    cand_pitches = Counter()
    for p in parts:
        cand_pitches.update(n["midi"] for n in p["notes"])
    inter = sum((gt_pitches & cand_pitches).values())
    result["global_pitch_recall"] = round(inter / sum(gt_pitches.values()), 4)
    result["global_pitch_precision"] = (round(inter / sum(cand_pitches.values()), 4)
                                        if cand_pitches else 0.0)

    # measure integrity: measures recovered + GT measure-length agreement
    n_cand_meas = max((max(p["measure_sums"], default=0) for p in parts),
                      default=0)
    result["measures_recovered"] = n_cand_meas
    result["gt_measures"] = n_gt_measures
    ok = 0
    for v, pi in assign.items():
        p = parts[pi]
        for mi in range(1, n_gt_measures + 1):
            want = gt_sums[mi - 1].get(v)
            got = p["measure_sums"].get(mi)
            if want is not None and got is not None and abs(want - got) < 1e-6:
                ok += 1
    denom = len(assign) * n_gt_measures
    result["measure_len_match_pct"] = round(100 * ok / denom, 1) if denom else 0.0
    return result


def fmt(result):
    lines = [f"=== {result['label']} — {result['xml']}"]
    lines.append(f"  parts: {result['candidate_parts']} "
                 f"{result['part_names']} -> assigned {result['assigned']}")
    for v in VOICES:
        if v in result["per_voice"]:
            pv = result["per_voice"][v]
            lines.append(f"  {v}: recall {pv['recall']:.2%}  precision "
                         f"{pv['precision']:.2%}  dur-acc {pv['dur_acc']:.2%}  "
                         f"({pv['matched']}/{pv['gt_notes']} GT notes, "
                         f"{pv['cand_notes']} candidate)")
    lines.append(f"  voice-aware:   recall {result['voice_note_recall']:.2%}  "
                 f"precision {result['voice_note_precision']:.2%}  "
                 f"dur-acc {result['dur_acc_overall']:.2%}")
    lines.append(f"  voice-blind:   pitch recall {result['global_pitch_recall']:.2%}  "
                 f"precision {result['global_pitch_precision']:.2%}")
    lines.append(f"  measures: {result['measures_recovered']} recovered vs "
                 f"{result['gt_measures']} GT; per-voice measure-length match "
                 f"{result['measure_len_match_pct']}%")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gt")
    ap.add_argument("xml")
    ap.add_argument("--label", default="candidate")
    ap.add_argument("--json", help="write result JSON here")
    args = ap.parse_args()
    result = score(args.gt, args.xml, args.label)
    print(fmt(result))
    if args.json:
        json.dump(result, open(args.json, "w"), indent=2)


if __name__ == "__main__":
    main()
