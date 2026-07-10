# release_descriptor test fixture

Entirely synthetic, hand-made data — not derived from any Antiochian Sacred
Music Library PDF or any other copyrighted source. Mirrors the shape of a
real `omr_dir` (catalog, ingest state, manifest, per-piece MusicXML/report,
overrides + tombstone) small enough to exercise
`release_descriptor.build_release_descriptor()` deterministically in CI,
where no real local catalog exists.

- `fixture_piece_a` — a synthetic `accepted` item, present in `manifest.json`
  with a real (tiny, hand-made) `.musicxml` and `.report.json`.
- `fixture_piece_b` — a synthetic `review` item (deliberately excluded from
  `manifest.json`, matching `ingest_catalog.py`'s real behavior — only
  `accepted` items are ever written to the manifest) to prove
  `input.source_inventory` covers *all* state records, not just published
  ones.
- `overrides/fixture_override_example.musicxml` — a synthetic hand-edited
  override, unrelated to either piece above (overrides are independent of
  manifest/state entries in the real system).
- `overrides/RETIRED` — a synthetic tombstone entry.

See `../test_release_descriptor.py` for how this fixture is used.
