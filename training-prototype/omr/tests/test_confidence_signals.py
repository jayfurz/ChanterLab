"""TRUST-02 confidence-vector contract tests (rights-safe, no PDFs)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OMR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(OMR_DIR))

import confidence_signals as cs
import vector_extract as ve


SIGNAL_NAMES = {
    "measure_consistency",
    "voice_topology",
    "staff_system_detection",
    "glyph_coverage",
    "pitch_and_accidentals",
    "ties_and_beams",
    "whole_rest_normalization",
    "divisi",
    "lyrics",
    "event_drops_and_duplicates",
    "page_selection",
    "override_status",
}


def _report():
    return {
        "stats": {
            "measures": 10,
            "measures_with_consistent_beat_sums": 9,
            "multivoice_measures": 8,
            "systems": 4,
            "single_staff_systems": 1,
            "staves_per_system_mode": 2,
            "music_glyphs_total": 98,
            "unmapped_music_glyphs": 2,
            "ties_detected": 3,
            "slurs_detected": 4,
            "curves_unmatched": 5,
            "curves_within_one_event": 1,
            "beam_quads_with_lt2_stems": 2,
            "whole_measure_rests_resized": 2,
            "whole_measure_rests_without_reference": 1,
            "divisi_notes_to_voice2": 2,
            "divisi_columns_merged": 3,
            "divisi_events_dropped": 4,
            "parenthesized_optional_notes_skipped": 1,
            "lyric_syllables_attached": 18,
            "lyric_tokens_unmatched": 2,
            "above_staff_lyric_lines": 1,
            "lyric_hyphen_merged_melisma": 2,
            "lyric_lines_shared_across_voices": 3,
            "lyric_lines_filtered_role_label": 1,
            "lyric_lines_filtered_rubric": 2,
            "grace_or_cue_heads_skipped": 3,
            "ambiguous_events_routed": 4,
            "unison_events_duplicated": 5,
            "single_stem_chords_split": 6,
            "stacked_wholes_split": 7,
            "shared_measures_degraded": 1,
        },
        "warning_counts": {
            "divisi.subset_search_failed": 2,
            "event.notehead_dropped": 3,
            "event.stemless_notehead_kept": 4,
            "measure.voice_beat_disagreement": 1,
            "pitch.mixed_key_signature": 2,
            "pitch.off_grid_notehead": 3,
            "pitch.unmatched_accidental": 4,
            "rhythm.unmatched_augmentation_dot": 5,
            "rhythm.unmatched_flag": 6,
            "staff.missing_clef": 1,
            "staff.no_barlines": 2,
            "staff.unbracketed_group": 3,
            "staff.unexpected_count": 4,
            "voice.shared_balance_failed": 2,
        },
        "voices": ["S", "A", "T", "B"],
        "lyric_verses": 2,
    }


def _context():
    return {
        "page_selection": {
            "mode": "auto",
            "page_count": 4,
            "selected_pages": [1, 3],
            "selectable_page_count": 2,
            "kind_counts": {"western": 2, "byzantine": 1, "text": 1},
        },
        "policy": {
            "reference": "legacy-measure-integrity-v1",
            "minimum_measure_consistency_ratio": 0.9,
        },
    }


def test_vector_has_versioned_stable_shape_and_separate_policy():
    vector = cs.build(_report(), _context())

    assert vector["schema_version"] == 1
    assert vector["reference"] == "omr-confidence-vector-v1"
    assert set(vector["signals"]) == SIGNAL_NAMES
    assert vector["policy"] == _context()["policy"]
    assert all(set(signal) == {"ratio", "evidence"}
               for signal in vector["signals"].values())


def test_ratios_are_raw_evidence_not_acceptance_decisions():
    vector = cs.build(_report(), _context())
    signals = vector["signals"]

    assert signals["measure_consistency"]["ratio"] == 0.9
    assert signals["glyph_coverage"]["ratio"] == 0.98
    assert signals["lyrics"]["ratio"] == 0.9
    assert signals["page_selection"]["ratio"] == 0.5
    changed_policy = _context()
    changed_policy["policy"]["minimum_measure_consistency_ratio"] = 0.99
    changed = cs.build(_report(), changed_policy)
    assert changed["signals"] == signals


def test_every_requested_failure_dimension_maps_to_typed_evidence():
    signals = cs.build(_report(), _context())["signals"]

    assert signals["pitch_and_accidentals"]["evidence"] == {
        "off_grid_noteheads": 3,
        "unmatched_accidentals": 4,
        "mixed_key_signatures": 2,
    }
    assert signals["ties_and_beams"]["evidence"]["unmatched_flags"] == 6
    assert signals["whole_rest_normalization"]["evidence"] == {
        "resized_measure_count": 2,
        "without_reference_count": 1,
    }
    assert signals["divisi"]["evidence"]["subset_search_failures"] == 2
    assert signals["lyrics"]["evidence"]["lines_shared_across_voices"] == 3
    assert signals["lyrics"]["evidence"]["lines_filtered_as_non_lyrics"] == 3
    assert signals["event_drops_and_duplicates"]["evidence"]["noteheads_dropped"] == 3
    assert signals["staff_system_detection"]["evidence"]["missing_clefs"] == 1
    assert signals["voice_topology"]["evidence"]["shared_balance_failures"] == 2


def test_missing_evidence_is_explicit_zero_or_null():
    vector = cs.build({"stats": {}, "warning_counts": {}})

    assert vector["policy"] is None
    assert vector["signals"]["measure_consistency"]["ratio"] is None
    assert vector["signals"]["glyph_coverage"]["ratio"] is None
    assert vector["signals"]["page_selection"]["evidence"] == {
        "available": False,
        "mode": None,
        "page_count": 0,
        "selected_page_count": 0,
        "selectable_page_count": 0,
        "kind_counts": {},
    }
    assert vector["signals"]["override_status"]["evidence"] == {"applied": False}


def test_report_warning_codes_are_counted_without_changing_prose():
    report = ve.Report()
    report.warn("pitch.unmatched_accidental", "human-readable detail")
    report.warn("pitch.unmatched_accidental", "another detail")

    body = report.as_dict()
    assert body["warnings"] == ["human-readable detail", "another detail"]
    assert body["warning_counts"] == {"pitch.unmatched_accidental": 2}
    with pytest.raises(ValueError, match="unsupported confidence warning code"):
        report.warn("invented.warning", "detail")


def test_lyric_contamination_filters_emit_raw_counters():
    def token(text, x0, y):
        return {
            "text": text,
            "x0": x0,
            "x1": x0 + 8,
            "cx": x0 + 4,
            "y": y,
            "size": 9,
            "italic": False,
        }

    report = ve.Report()
    band = [
        token("Priest:", 0, 10),
        token("Wisdom", 12, 10),
        token("Copyright", 0, 20),
        token("2026", 14, 20),
    ]

    assert ve._drop_non_lyric_lines(band, report) == []
    assert report.stats["lyric_lines_filtered_role_label"] == 1
    assert report.stats["lyric_lines_filtered_kill_token"] == 1


def test_override_marker_is_additive_and_deterministic():
    report = _report()
    report["confidence"] = cs.build(report, _context())

    first = cs.mark_override_applied(report)
    second = cs.mark_override_applied(first)
    assert second["confidence"]["signals"]["override_status"]["evidence"] == {
        "applied": True,
    }
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_page_context_is_compact_and_deterministic():
    pages = [
        {"page": 1, "kind": "western", "selectable": True},
        {"page": 2, "kind": "byzantine", "selectable": False},
        {"page": 3, "kind": "western", "selectable": True},
    ]

    assert cs.page_selection_context(pages, [1, 3], "auto") == {
        "mode": "auto",
        "page_count": 3,
        "selected_pages": [1, 3],
        "selectable_page_count": 2,
        "kind_counts": {"byzantine": 1, "western": 2},
    }
