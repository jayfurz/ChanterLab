# release_descriptor test fixture

Entirely synthetic, hand-made data — not derived from any Antiochian Sacred
Music Library PDF or any other copyrighted source. Mirrors the shape of a
real `omr_dir` (catalog, ingest state, manifest, per-piece MusicXML/report,
overrides + tombstone) small enough to exercise
`release_descriptor.build_release_descriptor()` deterministically in CI,
where no real local catalog exists.

**Path conventions match production exactly, confirmed by direct inspection
of the real local catalog at `/mnt/data/code/byzorgan-web/training-prototype/omr`**
(not derivable from source reading alone — this is what caught the original
path-doubling bug in an earlier version of this fixture): `manifest.json`
and `ingest_state.json` `musicxml` fields carry the full `out/ingest/<id>.musicxml`
prefix (relative to `omr_dir`, not to `out/ingest/` itself), `pdf` fields
carry `pdfs/ingest/<id>.pdf`, and `pdfs/survey/catalog.json` is a flat JSON
array (the raw upstream API response body, not wrapped in an envelope).

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
