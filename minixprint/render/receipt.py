"""Data-driven monospace receipt (look follows the original receipt.py prototype)."""
import textwrap
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from . import WIDTH
from .codes import render_qr
from .compose import blank, pad, stack
from .fonts import advance, font, metrics

MARGIN = 4
MONO_SIZE = 17
TITLE_SIZE = 34
QTY_W = 3
AMT_W = 9


def _money(x: float) -> str:
    return "{:,.2f}".format(x)


def _pairs(meta: Any) -> List[Tuple[str, str]]:
    if not meta:
        return []
    items = meta.items() if isinstance(meta, dict) else meta
    return [(str(a), str(b)) for a, b in items]


def _layout(data: Dict[str, Any]):
    """Turn receipt data into text rows [(text, font, align)], returning (rows, cols, line_height).

    data keys (all optional):
      title            big centred heading (shrunk to fit if too wide)
      subtitle_lines   list of centred lines under the title
      meta             {"Bill #1042": "12 Oct 2026 19:30", ...} or [(left, right), ...]
      items            [{"name", "qty" (default 1), "price" (unit price)}]
      taxes            [{"label": "CGST", "rate": 2.5}]   rate in percent of subtotal
                       [{"label": "Service", "amount": 12.0}]   or absolute amount
      currency         prefix for the total, e.g. "INR"
      footer_lines     centred lines; the first one is bold
      qr               string encoded as a QR code at the very end
    Columns are character-cell based, so every amount right-aligns exactly.
    """
    mono, bold = font("mono", MONO_SIZE), font("mono", MONO_SIZE, True)
    cw = advance(mono, "0")
    cols = int((WIDTH - 2 * MARGIN) // cw)
    asc, desc = metrics(mono)
    lh = asc + desc + 2

    rows: List[Tuple[str, object, str]] = []  # (text, font, align)

    def line(t="", f=mono, a="l"):
        rows.append((t, f, a))

    def row(left: str, right: str, f=mono):
        room = cols - len(right) - 1
        wrapped = textwrap.wrap(left, max(1, room), break_long_words=True) or [""]
        for i, part in enumerate(wrapped):
            if i == len(wrapped) - 1:
                line(part.ljust(cols - len(right)) + right, f)
            else:
                line(part, f)

    def rule(ch="-"):
        line(ch * cols)

    title = str(data.get("title") or "")
    if title:
        size = TITLE_SIZE
        tf = font("sans", size, True)
        while advance(tf, title) > WIDTH - 2 * MARGIN and size > 18:
            size -= 2
            tf = font("sans", size, True)
        tparts = [title] if advance(tf, title) <= WIDTH - 2 * MARGIN else \
            textwrap.wrap(title, max(8, int(cols * MONO_SIZE / size))) or [title]
        for p in tparts:
            line(p, tf, "c")
    for s in data.get("subtitle_lines") or []:
        for part in textwrap.wrap(str(s), cols) or [""]:
            line(part, mono, "c")
    if title or data.get("subtitle_lines"):
        line()

    meta = _pairs(data.get("meta"))
    if meta:
        rule("=")
        for a, b in meta:
            row(a, b)
        rule("=")

    items = data.get("items") or []
    subtotal = 0.0
    if items:
        row("ITEM", "QTY".rjust(QTY_W) + " " + "AMOUNT".rjust(AMT_W), bold)
        rule()
        for it in items:
            qty = it.get("qty", 1)
            amount = qty * float(it.get("price", 0))
            subtotal += amount
            row(str(it.get("name", "")), "%*s %*s" % (QTY_W, _qty(qty), AMT_W, _money(amount)))
        rule()

    taxes = data.get("taxes") or []
    tax_total = 0.0
    if items or taxes:
        w = QTY_W + 1 + AMT_W
        if taxes:
            row("Subtotal", _money(subtotal).rjust(w))
        for t in taxes:
            if "amount" in t:
                amt = float(t["amount"])
                label = str(t.get("label", "Tax"))
            else:
                rate = float(t.get("rate", 0))
                amt = round(subtotal * rate / 100.0, 2)
                label = "%s %g%%" % (t.get("label", "Tax"), rate)
            tax_total += amt
            row(label, _money(amt).rjust(w))
        total = subtotal + tax_total
        cur = str(data.get("currency") or "")
        rule("=")
        row("TOTAL", ((cur + " ") if cur else "") + _money(total), bold)
        rule("=")

    footer = [str(s) for s in data.get("footer_lines") or []]
    if footer:
        line()
        for i, s in enumerate(footer):
            for part in textwrap.wrap(s, cols) or [""]:
                line(part, bold if i == 0 else mono, "c")

    return rows, cols, lh


def render_receipt(data: Dict[str, Any]) -> Image.Image:
    """Render a receipt dict (keys documented on _layout and in docs/RENDER.md)."""
    rows, cols, lh = _layout(data)
    mono = font("mono", MONO_SIZE)
    blocks: List[Image.Image] = []
    heights = []
    for t, f, a in rows:
        fa, fd = metrics(f)
        heights.append(max(lh, fa + fd + 2))
    body = blank(sum(heights) + 2 * MARGIN) if rows else None
    if body is not None:
        d = ImageDraw.Draw(body)
        y = MARGIN
        for (t, f, a), h in zip(rows, heights):
            fa, fd = metrics(f)
            x = MARGIN if a == "l" else (WIDTH - advance(f, t)) / 2
            try:
                d.text((x, y + (h - fa - fd) // 2 + fa), t, font=f, fill=0, anchor="ls")
            except (ValueError, TypeError):  # pragma: no cover
                d.text((x, y), t, font=f, fill=0)
            y += h
        blocks.append(body)

    qr = data.get("qr")
    if qr:
        blocks.append(render_qr(str(qr), fill=0.5))
    if not blocks:
        return blank(8)
    return stack(*blocks, gap=0)


def _qty(q) -> str:
    return "%g" % q
