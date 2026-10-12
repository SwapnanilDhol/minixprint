"""QR codes and 1-D barcodes, drawn module-by-module so scale is pixel-exact."""
from typing import Optional

import barcode
import qrcode
from PIL import Image, ImageDraw

from . import WIDTH
from .compose import blank, pad, stack
from .text import render_text

_QUIET = 2  # QR quiet zone, in modules


def render_qr(data: str, caption: Optional[str] = None, box_size: Optional[int] = None,
              fill: float = 0.7) -> Image.Image:
    """QR code centred on the paper. box_size = px per module; by default the largest
    integer size that keeps the symbol within `fill` (70%) of the width."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=_QUIET)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()  # includes the quiet zone
    n = len(matrix)
    if box_size is None:
        box_size = max(1, int(WIDTH * fill) // n)
    if n * box_size > WIDTH:
        raise ValueError("QR needs %d px at box_size=%d; paper is %d px"
                         % (n * box_size, box_size, WIDTH))
    sym = Image.new("1", (n * box_size, n * box_size), 1)
    d = ImageDraw.Draw(sym)
    for y, row in enumerate(matrix):
        for x, on in enumerate(row):
            if on:
                d.rectangle([x * box_size, y * box_size,
                             (x + 1) * box_size - 1, (y + 1) * box_size - 1], fill=0)
    img = blank(sym.height)
    img.paste(sym, ((WIDTH - sym.width) // 2, 0))
    if caption:
        img = stack(img, render_text(caption, size=20, align="center", margin=4), gap=2)
    return pad(img, 4, 4)


def render_barcode(data: str, kind: str = "code128", caption: bool = True,
                   height: int = 80) -> Image.Image:
    """1-D barcode (any python-barcode symbology: code128, code39, ean13, upca, ...)
    with the human-readable text underneath when caption=True."""
    bc = barcode.get(kind, data)
    modules = bc.build()[0]  # string of '1' (bar) / '0' (space)
    quiet = 10
    n = len(modules) + 2 * quiet
    scale = min(4, WIDTH // n)
    if scale < 1:
        raise ValueError("barcode too long for %d px paper (%d modules)" % (WIDTH, n))
    bars = Image.new("1", (len(modules) * scale, height), 1)
    d = ImageDraw.Draw(bars)
    for i, m in enumerate(modules):
        if m == "1":
            d.rectangle([i * scale, 0, (i + 1) * scale - 1, height - 1], fill=0)
    img = blank(height)
    img.paste(bars, ((WIDTH - bars.width) // 2, 0))
    if caption:
        text = getattr(bc, "get_fullcode", lambda: data)()
        img = stack(img, render_text(text, size=18, align="center", mono=True, margin=2), gap=2)
    return pad(img, 4, 4)
