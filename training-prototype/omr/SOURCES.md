# OMR sources & reproduction

## Source scores (Antiochian Sacred Music Library)

Freely published by the Antiochian Orthodox Christian Archdiocese Department of
Sacred Music. Library: https://www.antiochian.org/sacred-music-library
Used here for research/prototyping. Composer credit and © belong to the
respective composers/publishers (these carry "Music Copyright © Tendershoot
Music 2022, used with permission" in the score footer). Do not redistribute;
this directory is for local OMR evaluation only.

| File | Piece | Composer | URL |
|---|---|---|---|
| `pdfs/01_trisagion_lozowchuk_satb.pdf` | Trisagion Hymn (4-part) | Oleksa Lozowchuk | https://antiochianprodsa.blob.core.windows.net/musiclibrary/01_trisagion_lozowchuk_satb.pdf |
| `pdfs/02_cherubichymn_lozowchuk_adapted_satb.pdf` | Cherubic Hymn (4-part) | Oleksa Lozowchuk | https://antiochianprodsa.blob.core.windows.net/musiclibrary/02_cherubichymn_lozowchuk_adapted_satb.pdf |
| `pdfs/03_anaphora_lozowchuk_satb.pdf` | Anaphora (4-part) | Oleksa Lozowchuk | https://antiochianprodsa.blob.core.windows.net/musiclibrary/03_anaphora_lozowchuk_satb.pdf |

### How the library was accessed (for a future catalog ingester)

The site is an Angular SPA backed by a REST API on the same origin:

- OAuth2 client-credentials token: `POST https://www.antiochian.org/connect/token`
  (`grant_type=client_credentials`, public client id `antiochian_api`; the
  client id/secret are shipped in the SPA bundle `main-*.js`).
- Full catalog (≈3,800 items, each with a direct blob PDF URL in
  `descriptionHtml`): `GET /api/antiochian/MusicLibraryListItems` (Bearer token).
- Arrangement types include `4-part, Full choir, Choral` — the SATB filter.

PDFs were fetched from Azure blob storage with a descriptive User-Agent, 1.5 s
apart (polite). No auth needed for the blob URLs themselves.

> **Not committed to git.** The source PDFs, rendered pages, `oemer` output,
> and the OMR-derived `content/trisagion_omr.musicxml` are `.gitignore`d
> because they are copyrighted (used with permission for local research only)
> and the project brief forbids committing copyrighted editions. Regenerate
> them locally with the steps below. The hand-made `content/control_satb.musicxml`
> is original and *is* committed.

## OMR tooling

- Tool: [`oemer`](https://github.com/BreezeWhite/oemer) (deep-learning OMR,
  ONNX U-Net segmentation → symbol assembly → MusicXML).
- Env: Python 3.11 venv at `omr/.venv` (uv). CPU inference
  (`onnxruntime`, not `-gpu`; the box's GPUs were held by other work and
  oemer's models are small enough for CPU).
- One compatibility patch was required: `oemer/bbox.py::find_lines` assumed the
  OpenCV < 5 `HoughLinesP` output shape `(N,1,4)`; OpenCV 5 returns `(N,4)`.
  Patched to `np.ravel(line)`. (Applied in-venv only.)

### Reproduce

```sh
cd training-prototype/omr
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python oemer onnxruntime pymupdf
# render a music page to PNG (skip the title page)
pdftoppm -png -r 300 pdfs/01_trisagion_lozowchuk_satb.pdf pages/01_trisagion
# apply the OpenCV-5 find_lines patch (see note above), then:
CUDA_VISIBLE_DEVICES="" .venv/bin/oemer pages/01_trisagion-2.png -o out
```

## Audiveris (bake-off reference OMR — fallback path for scans)

User-level install (no sudo), done 2026-07-02 for the bake-off
(docs/choir-training-roadmap.md §3.4):

- Temurin JDK 21 tarball → `/mnt/data/tools/jdk21`
- Audiveris 5.10.2 Linux .deb, unpacked (dpkg-deb -x) → `/mnt/data/tools/audiveris`
- Tesseract language data → `/mnt/data/tools/tessdata`

```sh
JAVA_HOME=/mnt/data/tools/jdk21 PATH="/mnt/data/tools/jdk21/bin:$PATH" \
TESSDATA_PREFIX=/mnt/data/tools/tessdata \
/mnt/data/tools/audiveris/bin/Audiveris -batch -export \
    -output out/audiveris pdfs/*.pdf
# .mxl outputs are zip containers; the root .xml inside is the MusicXML.
```

Results on this corpus: perfect on 4-staff pages, but 2-staff choral
reductions come out as 2 parts × 2 internal voices (not S/A/T/B) — see the
bake-off table. ~20–45 s per piece on CPU.
