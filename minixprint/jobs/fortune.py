"""``fortune``: one short line from the bundled list, centred between rules."""
import os

from ..render import render_text, rule, stack
from ._common import rng

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fortunes.txt")


def load_fortunes():
    with open(DATA, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]


def pick_fortune(params, ctx):
    return rng(params, ctx, "fortune").choice(load_fortunes())


def fortune(params, ctx):
    text = pick_fortune(params, ctx)
    size = 28 if len(text) < 70 else 24
    return stack(rule("double"), render_text(text, size=size, align="center", margin=10),
                 rule("double"), gap=4)


JOBS = {"fortune": fortune}
