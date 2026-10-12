"""Word-wrapped text layout. Shared by render_text, markdown and receipt rendering."""
import re
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from . import WIDTH
from .compose import blank, pad
from .fonts import advance, font, metrics

Span = Tuple[str, object]  # (text, Pillow font)
Line = List[Span]

_TOKEN = re.compile(r"\n|[^\S\n]+|\S+")


def wrap_spans(spans: Sequence[Span], max_width: float) -> List[Line]:
    """Greedy word wrap over styled spans.

    "\\n" inside a span forces a line break (and keeps leading indentation of the
    new line); lines created by wrapping drop leading whitespace. Words wider than
    max_width are split by character. Never loops on a too-narrow width.
    """
    lines: List[Line] = [[]]
    x = 0.0
    has_word = False
    skip_ws = False

    def newline(wrapped: bool):
        nonlocal x, has_word, skip_ws
        _rstrip(lines[-1])
        lines.append([])
        x, has_word, skip_ws = 0.0, False, wrapped

    for text, f in spans:
        for tok in _TOKEN.findall(text.replace("\t", "    ").replace("\r", "")):
            if tok == "\n":
                newline(False)
            elif tok.isspace():
                if not skip_ws:
                    lines[-1].append((tok, f))
                    x += advance(f, tok)
            else:
                w = advance(f, tok)
                if x + w > max_width and has_word:
                    newline(True)
                if x + w <= max_width:
                    lines[-1].append((tok, f))
                    x += w
                    has_word, skip_ws = True, False
                    continue
                # Too wide even for an empty line: split by character.
                piece = ""
                for ch in tok:
                    if piece and x + advance(f, piece + ch) > max_width:
                        lines[-1].append((piece, f))
                        newline(True)
                        piece = ""
                    piece += ch
                lines[-1].append((piece, f))
                x = advance(f, piece)
                has_word, skip_ws = True, False
    _rstrip(lines[-1])
    return lines


def _rstrip(line: Line):
    while line and not line[-1][0].strip():
        line.pop()
    if line:
        t, f = line[-1]
        line[-1] = (t.rstrip(), f)


def paint(spans: Sequence[Span], align: str = "left", left: int = 4, right: int = 4,
          line_spacing: float = 1.0, base_font=None, marker: Optional[Span] = None,
          marker_right: Optional[int] = None) -> Image.Image:
    """Lay out spans between `left` and WIDTH-right and draw them.

    Returns a WIDTH-wide image with no vertical margin. `marker`, if given, is
    drawn on the first line's baseline, right-aligned to x=marker_right
    (default: left - 6): used for list bullets.
    """
    if align not in ("left", "center", "right"):
        raise ValueError("align must be left, center or right, got %r" % (align,))
    avail = WIDTH - left - right
    lines = wrap_spans(spans, avail)
    if base_font is None:
        base_font = spans[0][1] if spans else font("sans", 24)

    # Measure
    rows = []
    for ln in lines:
        fonts = [f for _, f in ln] or [base_font]
        asc = max(metrics(f)[0] for f in fonts)
        desc = max(metrics(f)[1] for f in fonts)
        height = max(1, int(round((asc + desc) * line_spacing)))
        rows.append((ln, asc, height - asc - desc, height))
    total = sum(r[3] for r in rows)
    img = blank(total)
    d = ImageDraw.Draw(img)
    y = 0
    first_baseline = None
    for ln, asc, extra, height in rows:
        baseline = y + asc + extra // 2 if extra > 0 else y + asc
        width = sum(advance(f, t) for t, f in ln)
        if align == "left":
            x = float(left)
        elif align == "center":
            x = left + (avail - width) / 2
        else:
            x = left + avail - width
        if width > avail:  # unbreakable overflow (e.g. one huge glyph): pin left
            x = float(left)
        for t, f in ln:
            _text(d, x, baseline, t, f)
            x += advance(f, t)
        if first_baseline is None:
            first_baseline = baseline
        y += height
    if marker is not None and first_baseline is not None:
        mt, mf = marker
        mr = marker_right if marker_right is not None else left - 6
        _text(d, mr - advance(mf, mt), first_baseline, mt, mf)
    return img


def _text(d, x, baseline, t, f):
    try:
        d.text((x, baseline), t, font=f, fill=0, anchor="ls")
    except (ValueError, TypeError):  # pragma: no cover - bitmap fallback font
        d.text((x, baseline - metrics(f)[0]), t, font=f, fill=0)


def render_text(text: str, size: int = 28, align: str = "left", bold: bool = False,
                mono: bool = False, margin: int = 4, line_spacing: float = 1.0) -> Image.Image:
    """Render plain text, word-wrapped to the paper width.

    Explicit newlines are honoured; `line_spacing` multiplies the font's natural line
    height (1.0 = tight, 1.2 = airy). `margin` is padding in px on all four sides.
    """
    f = font("mono" if mono else "sans", size, bold)
    img = paint([(text or "", f)], align=align, left=margin, right=margin,
                line_spacing=line_spacing, base_font=f)
    return pad(img, margin, margin)
