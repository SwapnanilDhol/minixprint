#!/usr/bin/env python3
"""Copy docs/samples/<job>.png into minixprint/server/static/thumbs/ for the dashboard's Fun tiles.

Sample files are looked up as ``<job>.png`` then ``<job with . -> _>.png`` (e.g. aviation_metar.png).
Run after scripts/make_*_samples.py. Jobs without a sample get a glyph tile in the UI.
"""
import os
import shutil
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from minixprint.jobs import discover  # noqa: E402

SAMPLES = os.path.join(ROOT, "docs", "samples")
OUT = os.path.join(ROOT, "minixprint", "server", "static", "thumbs")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in sorted(discover()):
        for cand in (name, name.replace(".", "_")):
            src = os.path.join(SAMPLES, cand + ".png")
            if os.path.exists(src):
                shutil.copy(src, os.path.join(OUT, name + ".png"))
                print("thumb", name)
                break
        else:
            print("no sample for", name)
