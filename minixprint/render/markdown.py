"""Markdown -> 1-bit bitmap.

Supported: H1-H3 (larger bold; H4+ bold body size), paragraphs, bullet and numbered
lists (nested), horizontal rules, **bold**, *italic*, `code`, fenced/indented code
(mono), blockquotes (left bar). Everything else (tables, HTML, links, images)
degrades to its plain text; rendering never raises on odd input.
"""
from typing import List, Optional

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode
from PIL import ImageDraw

from .compose import blank, pad, rule, stack
from .fonts import advance, font
from .text import Span, paint, render_text

MARGIN = 4
_HEADING_SCALE = {1: 1.6, 2: 1.35, 3: 1.15}
_md = MarkdownIt("commonmark")


class _Ctx:
    def __init__(self, size: int):
        self.size = size
        self.gap = max(4, size // 2)  # space between blocks

    def f(self, bold=False, italic=False, mono=False):
        if mono:
            return font("mono", round(self.size * 0.75), bold, italic)
        return font("sans", self.size, bold, italic)


def _inline(node: SyntaxTreeNode, ctx: _Ctx, bold=False, italic=False, force_bold=False) -> List[Span]:
    spans: List[Span] = []
    for ch in node.children:
        t = ch.type
        if t == "text":
            spans.append((ch.content, ctx.f(bold or force_bold, italic)))
        elif t == "code_inline":
            spans.append((ch.content, ctx.f(bold or force_bold, False, mono=True)))
        elif t == "strong":
            spans += _inline(ch, ctx, True, italic, force_bold)
        elif t == "em":
            spans += _inline(ch, ctx, bold, True, force_bold)
        elif t == "softbreak":
            spans.append((" ", ctx.f(bold or force_bold, italic)))
        elif t == "hardbreak":
            spans.append(("\n", ctx.f()))
        elif ch.children:  # link, and any future inline container
            spans += _inline(ch, ctx, bold, italic, force_bold)
        else:  # image alt text, html_inline, unknown
            spans.append((ch.content or "", ctx.f(bold or force_bold, italic)))
    return spans


def _inline_of(node: SyntaxTreeNode, ctx: _Ctx, **kw) -> List[Span]:
    for ch in node.children:
        if ch.type == "inline":
            return _inline(ch, ctx, **kw)
    return [(node.content or "", ctx.f(**{k: v for k, v in kw.items() if k == "bold"}))]


class _Pending:
    """A list marker waiting to be drawn on the first text block of an item."""
    def __init__(self, span: Span, right: int):
        self.span, self.right = span, right


def _blocks(nodes, ctx: _Ctx, left: int, right: int, depth: int = 0,
            marker: Optional[_Pending] = None):
    out = []

    def take():
        nonlocal marker
        m, marker = marker, None
        return m

    def text_block(spans, **kw):
        m = take()
        out.append(paint(spans, left=left, right=right, base_font=ctx.f(),
                         marker=m.span if m else None,
                         marker_right=m.right if m else None, **kw))

    for n in nodes:
        t = n.type
        if t == "heading":
            level = int(n.tag[1:]) if n.tag else 3
            size = round(ctx.size * _HEADING_SCALE.get(level, 1.0))
            hctx = _Ctx(size)
            text_block(_inline_of(n, hctx, force_bold=True))
        elif t == "paragraph":
            text_block(_inline_of(n, ctx))
        elif t in ("bullet_list", "ordered_list"):
            out += _list(n, ctx, left, right, depth, take())
        elif t == "blockquote":
            inner = _blocks(n.children, ctx, left + 14, right, depth)
            if inner:
                img = stack(*inner, gap=ctx.gap // 2)
                ImageDraw.Draw(img).rectangle([left + 2, 0, left + 4, img.height - 1], fill=0)
                out.append(img)
        elif t == "hr":
            out.append(rule("solid"))
        elif t in ("fence", "code_block"):
            code = n.content.rstrip("\n").replace("\t", "    ")
            text_block([(code, ctx.f(mono=True))])
        elif n.children:
            out += _blocks(n.children, ctx, left, right, depth, take())
        elif n.content.strip():
            text_block([(n.content.strip(), ctx.f())])
    if marker is not None:  # item had no text block to attach to (e.g. "- ---")
        out.insert(0, paint([("", ctx.f())], left=left, right=right, base_font=ctx.f(),
                            marker=marker.span, marker_right=marker.right))
    return out


def _list(n: SyntaxTreeNode, ctx: _Ctx, left: int, right: int, depth: int,
          outer: Optional[_Pending]):
    ordered = n.type == "ordered_list"
    items = [c for c in n.children if c.type == "list_item"]
    start = int(n.attrs.get("start", 1) or 1) if ordered else 1
    mfont = ctx.f()
    if ordered:
        widest = max(advance(mfont, "%d." % (start + i)) for i in range(max(1, len(items))))
        indent = int(widest) + 12
    else:
        indent = 24
    out = []
    for i, li in enumerate(items):
        if ordered:
            mk = "%d." % (start + i)
        else:
            mk = "•" if depth == 0 else "–"
        pend = _Pending((mk, mfont), left + indent - 8)
        inner = _blocks(li.children, ctx, left + indent, right, depth + 1, pend)
        if inner:
            out.append(stack(*inner, gap=2))
    if outer is not None and out:
        out.insert(0, paint([("", mfont)], left=left, right=right, base_font=mfont,
                            marker=outer.span, marker_right=outer.right))
    return [stack(*out, gap=max(2, ctx.gap // 3))] if out else []


def render_markdown(md: str, size: int = 24, margin: int = MARGIN):
    """Render a Markdown string. `size` is the body font size in px."""
    md = md or ""
    ctx = _Ctx(size)
    try:
        root = SyntaxTreeNode(_md.parse(md))
        blocks = _blocks(root.children, ctx, margin, margin)
    except Exception:  # never crash on exotic input: fall back to plain text
        return render_text(md, size=size, margin=margin)
    if not blocks:
        return blank(8)
    return pad(stack(*blocks, gap=ctx.gap), margin, margin)
