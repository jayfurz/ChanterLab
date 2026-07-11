#!/usr/bin/env python3
"""Build the additive TRUST-02 confidence-vector report contract.

Signals contain observations and ratios only. Acceptance policy remains a
separate top-level object so adding evidence cannot silently change whether a
score is accepted or sent to review.
"""
from __future__ import annotations

from collections import Counter


SCHEMA_VERSION = 1
REFERENCE = "omr-confidence-vector-v1"
WARNING_CODES = frozenset({
    "divisi.secondary_stream_dropped",
    "divisi.subset_search_failed",
    "event.notehead_dropped",
    "event.stemless_notehead_kept",
    "glyph.unmapped_coverage",
    "measure.staff_length_disagreement",
    "measure.voice_beat_disagreement",
    "pitch.mixed_key_signature",
    "pitch.off_grid_notehead",
    "pitch.unmatched_accidental",
    "rhythm.unmatched_augmentation_dot",
    "rhythm.unmatched_flag",
    "staff.missing_clef",
    "staff.no_barlines",
    "staff.single_staff_soprano",
    "staff.unbracketed_group",
    "staff.unexpected_count",
    "voice.reconciliation_degraded",
    "voice.shared_balance_failed",
})


def _count(values: dict, key: str) -> int:
    value = values.get(key, 0)
    return int(value) if isinstance(value, (int, float)) else 0


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _page_evidence(context: dict) -> tuple[float | None, dict]:
    page = context.get("page_selection")
    if not isinstance(page, dict):
        return None, {
            "available": False,
            "mode": None,
            "page_count": 0,
            "selected_page_count": 0,
            "selectable_page_count": 0,
            "kind_counts": {},
        }
    page_count = int(page.get("page_count", 0))
    selected = list(page.get("selected_pages") or [])
    selectable = int(page.get("selectable_page_count", 0))
    kinds = page.get("kind_counts") if isinstance(page.get("kind_counts"), dict) else {}
    return _ratio(len(selected), page_count), {
        "available": True,
        "mode": page.get("mode"),
        "page_count": page_count,
        "selected_page_count": len(selected),
        "selected_pages": selected,
        "selectable_page_count": selectable,
        "kind_counts": {str(k): int(v) for k, v in sorted(kinds.items())},
    }


def build(report: dict, context: dict | None = None) -> dict:
    """Return a deterministic vector from one extractor report.

    Missing counters are explicit zeroes. This keeps older synthetic fixtures
    readable while making every new report share the same signal shape.
    """
    context = context or {}
    stats = report.get("stats") if isinstance(report.get("stats"), dict) else {}
    warnings = (
        report.get("warning_counts")
        if isinstance(report.get("warning_counts"), dict)
        else {}
    )
    voices = list(report.get("voices") or [])

    measures = _count(stats, "measures")
    consistent = _count(stats, "measures_with_consistent_beat_sums")
    glyphs = _count(stats, "music_glyphs_total")
    unmapped = _count(stats, "unmapped_music_glyphs")
    attached = _count(stats, "lyric_syllables_attached")
    unmatched_lyrics = _count(stats, "lyric_tokens_unmatched")
    page_ratio, page_evidence = _page_evidence(context)

    signals = {
        "measure_consistency": {
            "ratio": _ratio(consistent, measures),
            "evidence": {
                "measure_count": measures,
                "consistent_measure_count": consistent,
                "inconsistent_measure_count": max(0, measures - consistent),
                "multivoice_measure_count": _count(stats, "multivoice_measures"),
            },
        },
        "voice_topology": {
            "ratio": None,
            "evidence": {
                "voices": voices,
                "voice_count": len(voices),
                "ambiguous_events_routed": _count(stats, "ambiguous_events_routed"),
                "unison_events_duplicated": _count(stats, "unison_events_duplicated"),
                "single_stem_chords_split": _count(stats, "single_stem_chords_split"),
                "stacked_wholes_split": _count(stats, "stacked_wholes_split"),
                "shared_measures_degraded": _count(stats, "shared_measures_degraded"),
                "shared_balance_failures": _count(warnings, "voice.shared_balance_failed"),
            },
        },
        "staff_system_detection": {
            "ratio": None,
            "evidence": {
                "system_count": _count(stats, "systems"),
                "single_staff_system_count": _count(stats, "single_staff_systems"),
                "staves_per_system_mode": stats.get("staves_per_system_mode"),
                "unbracketed_staff_groups": _count(warnings, "staff.unbracketed_group"),
                "missing_clefs": _count(warnings, "staff.missing_clef"),
                "systems_without_barlines": _count(warnings, "staff.no_barlines"),
                "unexpected_staff_counts": _count(warnings, "staff.unexpected_count"),
            },
        },
        "glyph_coverage": {
            "ratio": _ratio(glyphs, glyphs + unmapped),
            "evidence": {
                "mapped_music_glyph_count": glyphs,
                "unmapped_music_glyph_count": unmapped,
            },
        },
        "pitch_and_accidentals": {
            "ratio": None,
            "evidence": {
                "off_grid_noteheads": _count(warnings, "pitch.off_grid_notehead"),
                "unmatched_accidentals": _count(warnings, "pitch.unmatched_accidental"),
                "mixed_key_signatures": _count(warnings, "pitch.mixed_key_signature"),
            },
        },
        "ties_and_beams": {
            "ratio": None,
            "evidence": {
                "ties_detected": _count(stats, "ties_detected"),
                "slurs_detected": _count(stats, "slurs_detected"),
                "curves_unmatched": _count(stats, "curves_unmatched"),
                "curves_within_one_event": _count(stats, "curves_within_one_event"),
                "unmatched_flags": _count(warnings, "rhythm.unmatched_flag"),
                "beam_quads_with_lt2_stems": _count(stats, "beam_quads_with_lt2_stems"),
            },
        },
        "whole_rest_normalization": {
            "ratio": None,
            "evidence": {
                "resized_measure_count": _count(stats, "whole_measure_rests_resized"),
                "without_reference_count": _count(
                    stats, "whole_measure_rests_without_reference"
                ),
            },
        },
        "divisi": {
            "ratio": None,
            "evidence": {
                "notes_to_voice2": _count(stats, "divisi_notes_to_voice2"),
                "columns_merged": _count(stats, "divisi_columns_merged"),
                "events_dropped": _count(stats, "divisi_events_dropped"),
                "subset_search_failures": _count(warnings, "divisi.subset_search_failed"),
                "optional_notes_skipped": _count(
                    stats, "parenthesized_optional_notes_skipped"
                ),
            },
        },
        "lyrics": {
            "ratio": _ratio(attached, attached + unmatched_lyrics),
            "evidence": {
                "syllables_attached": attached,
                "tokens_unmatched": unmatched_lyrics,
                "verse_count": int(report.get("lyric_verses") or 0),
                "above_staff_line_count": _count(stats, "above_staff_lyric_lines"),
                "hyphenated_melismas_merged": _count(
                    stats, "lyric_hyphen_merged_melisma"
                ),
                "lines_shared_across_voices": _count(
                    stats, "lyric_lines_shared_across_voices"
                ),
                "lines_filtered_as_non_lyrics": sum(
                    _count(stats, key) for key in (
                        "lyric_lines_filtered_bracketed",
                        "lyric_lines_filtered_direction",
                        "lyric_lines_filtered_footnote",
                        "lyric_lines_filtered_kill_token",
                        "lyric_lines_filtered_nonlexical",
                        "lyric_lines_filtered_oversized",
                        "lyric_lines_filtered_role_label",
                        "lyric_lines_filtered_rubric",
                    )
                ),
            },
        },
        "event_drops_and_duplicates": {
            "ratio": None,
            "evidence": {
                "noteheads_dropped": _count(warnings, "event.notehead_dropped"),
                "grace_or_cue_heads_skipped": _count(
                    stats, "grace_or_cue_heads_skipped"
                ),
                "parenthesized_optional_notes_skipped": _count(
                    stats, "parenthesized_optional_notes_skipped"
                ),
                "stemless_noteheads_kept": _count(
                    warnings, "event.stemless_notehead_kept"
                ),
                "unmatched_augmentation_dots": _count(
                    warnings, "rhythm.unmatched_augmentation_dot"
                ),
                "divisi_events_dropped": _count(stats, "divisi_events_dropped"),
                "unison_events_duplicated": _count(stats, "unison_events_duplicated"),
            },
        },
        "page_selection": {
            "ratio": page_ratio,
            "evidence": page_evidence,
        },
        "override_status": {
            "ratio": None,
            "evidence": {"applied": bool(context.get("override_applied", False))},
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "reference": REFERENCE,
        "policy": context.get("policy"),
        "signals": signals,
    }


def mark_override_applied(report: dict) -> dict:
    """Set the additive override signal on an already-generated report."""
    confidence = report.get("confidence")
    if not isinstance(confidence, dict) or confidence.get("reference") != REFERENCE:
        confidence = build(report)
        report["confidence"] = confidence
    confidence["signals"]["override_status"]["evidence"]["applied"] = True
    return report


def page_selection_context(page_infos: list[dict], selected_pages: list[int], mode: str) -> dict:
    """Return compact, non-prose page evidence for the report vector."""
    return {
        "mode": mode,
        "page_count": len(page_infos),
        "selected_pages": list(selected_pages),
        "selectable_page_count": sum(1 for page in page_infos if page.get("selectable")),
        "kind_counts": dict(Counter(page.get("kind", "unknown") for page in page_infos)),
    }
