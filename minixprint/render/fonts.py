"""Portable font resolution.

Order: macOS system fonts (Helvetica / Menlo), then DejaVu (Linux / Raspberry Pi,
`apt install fonts-dejavu-core`), then Pillow's built-in default font. A missing
bold/italic face degrades to the closest available one instead of failing.
"""
import os
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

# style -> (path, ttc index); style is (bold, italic)
_Family = Dict[Tuple[bool, bool], Tuple[str, int]]

_MAC = "/System/Library/Fonts/"
_DEJAVU_DIRS = [
    "/usr/share/fonts/truetype/dejavu/",
    "/usr/share/fonts/dejavu/",
    "/usr/share/fonts/TTF/",
    "",  # bare filename: let Pillow search the system font dirs
]


def _dejavu(stem: str) -> List[_Family]:
    fams = []
    for d in _DEJAVU_DIRS:
        fams.append({
            (False, False): (d + stem + ".ttf", 0),
            (True, False): (d + stem + "-Bold.ttf", 0),
            (False, True): (d + stem + "-Oblique.ttf", 0),
            (True, True): (d + stem + "-BoldOblique.ttf", 0),
        })
    return fams


_FAMILIES: Dict[str, List[_Family]] = {
    "sans": [{
        (False, False): (_MAC + "Helvetica.ttc", 0),
        (True, False): (_MAC + "Helvetica.ttc", 1),
        (False, True): (_MAC + "Helvetica.ttc", 2),
        (True, True): (_MAC + "Helvetica.ttc", 3),
    }] + _dejavu("DejaVuSans"),
    "mono": [{
        (False, False): (_MAC + "Menlo.ttc", 0),
        (True, False): (_MAC + "Menlo.ttc", 1),
        (False, True): (_MAC + "Menlo.ttc", 2),
        (True, True): (_MAC + "Menlo.ttc", 3),
    }] + _dejavu("DejaVuSansMono"),
}

# Style fallbacks when a family lacks the exact face.
_FALLBACK = {
    (True, True): [(True, True), (True, False), (False, True), (False, False)],
    (True, False): [(True, False), (False, False)],
    (False, True): [(False, True), (False, False)],
    (False, False): [(False, False)],
}


@lru_cache(maxsize=None)
def font(kind: str = "sans", size: int = 28, bold: bool = False, italic: bool = False):
    """Return a Pillow font. kind is "sans" or "mono"; sizes are in pixels."""
    if kind not in _FAMILIES:
        raise ValueError("kind must be 'sans' or 'mono', got %r" % (kind,))
    size = max(1, int(round(size)))
    env = os.environ.get("MINIXPRINT_FONT_" + kind.upper())  # explicit override
    if env:
        try:
            return ImageFont.truetype(env, size)
        except OSError:
            pass
    for fam in _FAMILIES[kind]:
        for style in _FALLBACK[(bool(bold), bool(italic))]:
            if style not in fam:
                continue
            path, idx = fam[style]
            try:
                return ImageFont.truetype(path, size, index=idx)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size)  # Pillow >= 10.1, FreeType-backed
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def metrics(f) -> Tuple[int, int]:
    """(ascent, descent) in px, tolerant of Pillow's bitmap fallback font."""
    try:
        return f.getmetrics()
    except AttributeError:  # pragma: no cover
        return 11, 3


def advance(f, text: str) -> float:
    """Pixel width of text."""
    try:
        return f.getlength(text)
    except AttributeError:  # pragma: no cover
        return float(f.getsize(text)[0])


def char_width(f) -> Optional[float]:
    """Advance of one glyph of a monospace font."""
    return advance(f, "0")
