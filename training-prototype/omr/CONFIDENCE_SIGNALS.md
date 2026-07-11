# OMR Confidence Vector v1

Reference: `omr-confidence-vector-v1`

The confidence vector is additive private report evidence. It does not claim
that a transcription is correct, and it does not replace human verification.
The existing `measure_integrity_pct` field and 90% acceptance gate remain in
force until a separately reviewed policy change says otherwise.

## Contract

Every successful `pipeline.py` report contains:

```json
{
  "warning_counts": {
    "pitch.unmatched_accidental": 2
  },
  "confidence": {
    "schema_version": 1,
    "reference": "omr-confidence-vector-v1",
    "policy": {
      "reference": "legacy-measure-integrity-v1",
      "minimum_measure_consistency_ratio": 0.9
    },
    "signals": {
      "measure_consistency": {
        "ratio": 0.98,
        "evidence": {
          "measure_count": 100,
          "consistent_measure_count": 98,
          "inconsistent_measure_count": 2,
          "multivoice_measure_count": 100
        }
      }
    }
  }
}
```

Each signal always has exactly `ratio` and `evidence`. A ratio is present only
where the numerator and denominator have an honest mechanical meaning. `null`
means the engine reports evidence but does not pretend to know a calibrated
probability. Missing observations are explicit zeroes or `null`, not absent
fields.

`policy` is deliberately outside `signals`. Changing a threshold cannot change
the raw vector, and adding a signal cannot silently change acceptance status.
Direct `vector_extract.run()` calls have `policy: null`; the canonical pipeline
records the legacy gate it actually applied.

## Signals

| Signal | Ratio | Raw evidence |
|---|---|---|
| `measure_consistency` | consistent / total measures | measure totals and multivoice count |
| `voice_topology` | `null` | voices, ambiguous routing, unison duplication, chord/whole splits, degraded reconciliation |
| `staff_system_detection` | `null` | system/staff topology, missing clefs/barlines, unexpected staff groups |
| `glyph_coverage` | mapped / mapped-plus-unmapped music glyphs | mapped and unmapped counts |
| `pitch_and_accidentals` | `null` | off-grid heads, unmatched accidentals, mixed key signatures |
| `ties_and_beams` | `null` | ties/slurs, unmatched curves/flags, incomplete beam quads |
| `whole_rest_normalization` | `null` | resized rests and cases lacking a reference voice |
| `divisi` | `null` | voice-2 notes, merged columns, drops, subset failures, optional-note exclusions |
| `lyrics` | attached / attached-plus-unmatched tokens | syllables, unmatched tokens, verses, above-staff lines, shared-line borrowing, filtered contamination/rubrics, melisma merges |
| `event_drops_and_duplicates` | `null` | dropped/kept/skipped note events, unmatched dots, divisi drops, unison duplication |
| `page_selection` | selected / total PDF pages | selection mode/pages, selectable count, notation-kind counts |
| `override_status` | `null` | whether an authoritative override was applied |

Ratios describe extractor coverage or agreement, not transcription accuracy.
For example, a high lyric attachment ratio cannot prove that the words were
recognized correctly, and a high glyph-coverage ratio cannot prove that a
mapped symbol was assigned to the correct voice.

## Stable Warning Codes

Human-readable `warnings` remain unchanged. `warning_counts` provides the
stable machine-readable identity for distribution comparisons and review
clustering:

- `divisi.secondary_stream_dropped`
- `divisi.subset_search_failed`
- `event.notehead_dropped`
- `event.stemless_notehead_kept`
- `glyph.unmapped_coverage`
- `measure.staff_length_disagreement`
- `measure.voice_beat_disagreement`
- `pitch.mixed_key_signature`
- `pitch.off_grid_notehead`
- `pitch.unmatched_accidental`
- `rhythm.unmatched_augmentation_dot`
- `rhythm.unmatched_flag`
- `staff.missing_clef`
- `staff.no_barlines`
- `staff.single_staff_soprano`
- `staff.unbracketed_group`
- `staff.unexpected_count`
- `voice.reconciliation_degraded`
- `voice.shared_balance_failed`

New warning codes require a code change and focused test. Unknown codes fail at
the reporting boundary instead of silently creating a new distribution bucket.

## Compatibility And Policy

- MusicXML emission, `measure_integrity_pct`, pipeline exit codes, ingest
  statuses, the manifest shape, and the public release marker are unchanged.
- Existing report consumers may ignore the additive `warning_counts` and
  `confidence` fields.
- Quality Ledger Schema v1 continues to reference
  `legacy-measure-integrity-v1`. The immutable report hash binds the complete
  vector. Changing the ledger reference itself requires a separately reviewed
  ledger-schema compatibility decision.
- A future acceptance/review policy must be versioned outside this vector and
  evaluated against a staged catalog diff. TRUST-02 does not choose thresholds.
