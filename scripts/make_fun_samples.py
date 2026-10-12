#!/usr/bin/env python3
"""Render each fun job into docs/samples/<job>.png (network mocked with the Open-Meteo fixture)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)

from minixprint.jobs import DEFAULT_SETTINGS, JobContext, discover  # noqa: E402

OUT = os.path.join(ROOT, "docs", "samples")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "open-meteo.json")


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        with open(FIXTURE) as fh:
            return json.load(fh)


class _Http:
    def get(self, *a, **kw):
        return _Resp()


SAMPLES = {
    "puzzle.sudoku": {"difficulty": "medium", "seed": 2024, "with_solution": True},
    "puzzle.maze": {"size": 31, "seed": 2024},
    "puzzle.wordsearch": {"theme": "aviation", "seed": 2024},
    "fortune": {"seed": 2024},
    "morning": {"seed": 2024, "todos": ["Water the plants", "Print the boarding pass",
                                        "Call the electrician about the hallway light"],
                "notes": "1911: the first official airmail flight takes off in Allahabad."},
    "system.status": {},
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    ctx = JobContext(settings=dict(DEFAULT_SETTINGS), http=_Http())
    jobs = discover()
    for name, params in SAMPLES.items():
        path = os.path.join(OUT, name + ".png")
        jobs[name](params, ctx).save(path)
        print("wrote", path)
