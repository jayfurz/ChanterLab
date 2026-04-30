# Glyph Atlas Testing Guide

The glyph atlas is a hidden visual QA page for the chant glyph cluster catalog.
It is not part of the public app navigation.

Open it from this worktree server:

```text
http://127.0.0.1:8432/glyph-atlas.html
```

If a mobile browser appears stale, add a cache-busting query:

```text
http://127.0.0.1:8432/glyph-atlas.html?v=phase6q
```

Filter to one atlas group with `category`, for example:

```text
http://127.0.0.1:8432/glyph-atlas.html?v=phase6q&category=Timing%20Signs
http://127.0.0.1:8432/glyph-atlas.html?v=phase6q&category=Attachment%20Examples
http://127.0.0.1:8432/glyph-atlas.html?v=phase6q&category=Martyria%20Checkpoints
```

Do not use port `8765` for this workflow.

## What To Inspect

- Each cell should show a centered Neanes glyph or glyph cluster inside the grid box.
- No glyph should be clipped by the grid box.
- Duration signs should sit close above the base glyph at roughly dot scale.
- Gorgon-family signs should sit close above the base glyph without collision.
- Precomposed oligon, petasti, and kentimata cluster glyphs should render as single main glyphs.
- Martyria cells should render as checkpoint clusters, with note and mode-sign components.

## Screenshot Commands

Desktop:

```bash
chromium --headless --disable-gpu --window-size=1440,1100 --virtual-time-budget=3000 --screenshot=/tmp/glyph-atlas-desktop.png 'http://127.0.0.1:8432/glyph-atlas.html'
```

Mobile:

```bash
chromium --headless --disable-gpu --window-size=390,844 --virtual-time-budget=3000 --screenshot=/tmp/glyph-atlas-mobile.png 'http://127.0.0.1:8432/glyph-atlas.html'
```

The atlas uses the catalog and renderer under `web/score/`, so broken catalog
metadata should show up both in tests and in these screenshots.
