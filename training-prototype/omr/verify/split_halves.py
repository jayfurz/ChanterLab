#!/usr/bin/env python3
"""Split each verify/out/*.png comparison into overlapping left/right halves
so the audit can be read at ~full resolution."""
import glob
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))

pats = sys.argv[1:] or ["*"]
for pat in pats:
    for fn in sorted(glob.glob(os.path.join(HERE, "out", pat + ".png"))):
        base = os.path.splitext(fn)[0]
        if base.endswith("_L") or base.endswith("_R"):
            continue
        img = Image.open(fn)
        w, h = img.size
        img.crop((0, 0, int(w * 0.56), h)).save(base + "_L.png")
        img.crop((int(w * 0.44), 0, w, h)).save(base + "_R.png")
print("done")
