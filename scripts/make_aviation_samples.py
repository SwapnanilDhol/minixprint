#!/usr/bin/env python3
"""Render each aviation job from tests/fixtures/aviation into docs/samples/aviation_*.png."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from aviation_fakes import make_ctx  # noqa: E402

from minixprint.jobs import discover  # noqa: E402

OUT = os.path.join(ROOT, "docs", "samples")
os.makedirs(OUT, exist_ok=True)

CONTACT = {"hex": "04022c", "flight": "ETH3751", "registration": "ET-AVB", "type": "B77L",
           "type_name": "Boeing 777F", "origin": "MAA", "dest": "ADD", "origin_city": "Chennai",
           "dest_city": "Addis Ababa", "alt_baro": 39000, "gs": 490, "track": 270,
           "lat": 12.95, "lon": 79.6, "squawk": "7700", "is_military": True,
           "reasons": ["WATCHLIST"]}

SAMPLES = {
    "aviation_overhead": ("aviation.overhead", {"contact": CONTACT}, {}),
    "aviation_metar": ("aviation.metar", {}, {}),
    "aviation_runway": ("aviation.runway", {}, {}),
    "aviation_now": ("aviation.now", {}, {}),
    "aviation_digest": ("aviation.digest", {}, {}),
}

if __name__ == "__main__":
    jobs = discover()
    for name, (job, params, kw) in SAMPLES.items():
        img = jobs[job](params, make_ctx(**kw))
        img.save(os.path.join(OUT, name + ".png"))
        print(name, img.size)
