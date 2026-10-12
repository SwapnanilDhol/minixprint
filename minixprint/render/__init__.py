"""Rendering layer: everything here returns a Pillow mode-"1" image exactly WIDTH px wide.

Pixel value 0 is black, 255 (1 in mode "1") is white/paper. See docs/RENDER.md.
"""

WIDTH = 384  # printable dots per line (48 bytes) at 203 dpi

# Imported after WIDTH is defined: the submodules do `from . import WIDTH`.
from .codes import render_barcode, render_qr  # noqa: E402
from .compose import pad, rule, stack, to_rows  # noqa: E402
from .fonts import font  # noqa: E402
from .image import render_image  # noqa: E402
from .markdown import render_markdown  # noqa: E402
from .receipt import render_receipt  # noqa: E402
from .text import render_text  # noqa: E402

__all__ = [
    "WIDTH", "font", "pad", "render_barcode", "render_image", "render_markdown",
    "render_qr", "render_receipt", "render_text", "rule", "stack", "to_rows",
]
