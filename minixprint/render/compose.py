"""Composition helpers: stack blocks, rules, padding, and packing for the printer."""
from typing import Optional

from PIL import Image, ImageDraw

from . import WIDTH

_INVERT = bytes(range(255, -1, -1))


def blank(height: int) -> Image.Image:
    """White WIDTH x height image (height is clamped to >= 1)."""
    return Image.new("1", (WIDTH, max(1, int(height))), 1)


def _check(img: Image.Image) -> Image.Image:
    if img.width != WIDTH:
        raise ValueError("block is %d px wide, expected %d" % (img.width, WIDTH))
    return img if img.mode == "1" else img.convert("1")


def stack(*images: Optional[Image.Image], gap: int = 8) -> Image.Image:
    """Concatenate WIDTH-wide blocks vertically with `gap` white pixels between.

    None entries are skipped. With no blocks, returns a small blank image.
    """
    blocks = [_check(i) for i in images if i is not None]
    if not blocks:
        return blank(8)
    total = sum(b.height for b in blocks) + gap * (len(blocks) - 1)
    out = blank(total)
    y = 0
    for b in blocks:
        out.paste(b, (0, y))
        y += b.height + gap
    return out


def pad(img: Image.Image, top: int = 0, bottom: int = 0) -> Image.Image:
    """Add white space above and below."""
    img = _check(img)
    out = blank(img.height + top + bottom)
    out.paste(img, (0, max(0, top)))
    return out


def rule(style: str = "solid", thickness: int = 2, margin: int = 4) -> Image.Image:
    """Horizontal rule: "solid", "dashed" or "double"."""
    if style not in ("solid", "dashed", "double"):
        raise ValueError("style must be solid, dashed or double, got %r" % (style,))
    gapy = 4
    height = thickness * 2 + gapy + 6 if style == "double" else thickness + 8
    img = blank(height)
    d = ImageDraw.Draw(img)
    x0, x1 = margin, WIDTH - margin - 1
    if style == "double":
        y = 3
        d.rectangle([x0, y, x1, y + thickness - 1], fill=0)
        y += thickness + gapy
        d.rectangle([x0, y, x1, y + thickness - 1], fill=0)
    else:
        y = 4
        if style == "solid":
            d.rectangle([x0, y, x1, y + thickness - 1], fill=0)
        else:
            x = x0
            while x <= x1:
                d.rectangle([x, y, min(x + 7, x1), y + thickness - 1], fill=0)
                x += 14
    return img


def to_rows(img: Image.Image) -> bytes:
    """Pack into printer rows: 48 bytes per row, MSB first, 1 = black.

    Equivalent to `pack()` in minix.py. Pillow's mode "1" tobytes() is already
    MSB-first with 1 = white, so we only need to invert the bits.
    """
    img = _check(img)
    return img.tobytes().translate(_INVERT)
