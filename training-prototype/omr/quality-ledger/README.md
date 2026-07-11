# Private Quality Ledger Journal

`ledger.json` is private mutable review state. It is ignored by Git and is
included in the private corpus backup set. Do not put reviewer names, email
addresses, local filesystem paths, score text, or source-PDF excerpts in it.

Use opaque actor and evidence references only. A candidate copies this journal
at creation time, then sealing reconciles it with the candidate catalog and
writes an immutable `trust/quality-ledger.json` snapshot inside the release.
That snapshot is never served by the web application.

See `../QUALITY_LEDGER_SCHEMA.md` for the format and transition rules.
