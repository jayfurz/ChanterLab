# overrides/ — hand-authored piece corrections

Drop a full-replacement MusicXML file here as `<stem>.musicxml` (same stem as
the manifest `id` / the file in `out/ingest/`) and it **wins over the
extractor**. On the next ingest run the override is copied over
`out/ingest/<stem>.musicxml` (what the app serves) and the piece is
force-accepted into the manifest, bypassing the integrity and voice-collapse
guards — a human edit is authoritative.

## Why this exists

Editing `out/ingest/<stem>.musicxml` directly works instantly (live tree), but
the next `ingest_catalog.py --redo` re-extracts and clobbers it. Files placed
here survive `--redo`: extraction runs first, then the override is re-stamped
on top.

## Edit loop

```
# 1. copy the extractor's output as your starting point
cp out/ingest/<stem>.musicxml overrides/<stem>.musicxml

# 2. edit overrides/<stem>.musicxml  (plain MusicXML — see below)

# 3. apply it (no network, no re-extraction, ~seconds):
.venv/bin/python ingest_catalog.py --report-only
```

`--report-only` copies every override into `out/ingest/`, rebuilds the
manifest, and the change is live (chanterlab serves the working tree).

A malformed edit is **refused** — the file is parsed first, so a typo can't
blank a piece; you'll see `[override] SKIP <fn>: not valid XML`.

## What the XML looks like

Standard `partwise` MusicXML. Four `<part>`s (P1=Soprano, P2=Alto, P3=Tenor,
P4=Bass), each a list of `<measure>`s. A note is:

```xml
<note>
  <pitch><step>A</step><octave>4</octave></pitch>   <!-- <alter>1</alter> = sharp, -1 = flat -->
  <duration>4</duration>                              <!-- in <divisions> per quarter -->
  <type>quarter</type>                                <!-- half, eighth, 16th ... -->
  <lyric number="1"><syllabic>begin</syllabic><text>Ho</text></lyric>
</note>
```

- `<duration>` is in divisions (see the measure's `<divisions>`; commonly 2 =
  eighth-note resolution, so a quarter is `2`). Every voice in a measure must
  sum to the same beat count or OSMD renders it ragged.
- A rest is `<note><rest/><duration>…</duration></note>`.
- A chord note adds `<chord/>` before `<pitch>` (stacked on the previous note).
- `<syllabic>` is `single | begin | middle | end`; a hyphen renders between
  `begin/middle/end` syllables of one word.

Small fixes (a wrong pitch, a merged syllable, a stray lyric) are a one-line
edit. Structural surgery (re-barring, re-voicing) is more work but still just
XML — open it in MuseScore, fix visually, export MusicXML back here if you
prefer a GUI.

## Copyright

Overrides are derived from the same copyrighted source PDFs as the extracted
XML. This directory is **gitignored** and included in the private corpus
archive — never committed to the public repo (same policy as `out/ingest/`).
