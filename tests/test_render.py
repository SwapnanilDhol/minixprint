
import pytest
from PIL import Image

from minixprint.render import (
    WIDTH,
    font,
    pad,
    render_barcode,
    render_image,
    render_markdown,
    render_qr,
    render_receipt,
    render_text,
    rule,
    stack,
    to_rows,
)
from minixprint.render.text import wrap_spans

RECEIPT = {
    "title": "DOSA & CO.",
    "subtitle_lines": ["South Indian Kitchen"],
    "meta": {"Bill #1": "12 Oct 2026", "Table 7": "Server: Priya"},
    "items": [{"name": "Masala Dosa", "qty": 2, "price": 180},
              {"name": "An extremely long item name that must wrap onto lines", "qty": 1, "price": 5.5}],
    "taxes": [{"label": "CGST", "rate": 2.5}, {"label": "Fee", "amount": 3}],
    "currency": "INR",
    "footer_lines": ["Thanks"],
    "qr": "https://example.com",
}


def check(img):
    assert img.mode == "1"
    assert img.width == WIDTH == 384
    assert img.height >= 1
    return img


def black_extent(img):
    """(min_x, max_x) of black pixels, or None."""
    ink = img.convert("L").point(lambda v: 255 if v == 0 else 0)
    box = ink.getbbox()
    return box and (box[0], box[2] - 1)


def test_all_renderers_width_and_mode(tmp_path):
    photo = Image.new("RGB", (100, 50), (120, 120, 120))
    imgs = [
        render_text("hi"), render_text(""), render_text("a\n\nb", align="center", bold=True, mono=True),
        render_markdown("# T\npara"), render_markdown(""), render_receipt(RECEIPT), render_receipt({}),
        render_qr("hello", caption="cap"), render_barcode("ABC-123"),
        render_image(photo), render_image(photo, "atkinson"), render_image(photo, "none"),
        rule("solid"), rule("dashed"), rule("double"), stack(), pad(rule(), 3, 4),
    ]
    for im in imgs:
        check(im)


@pytest.mark.parametrize("mono", [False, True])
@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_wrapping_does_not_overflow(mono, align):
    text = ("The quick brown fox jumps over the lazy dog " * 6 + "\n"
            + "Supercalifragilisticexpialidocious" * 4 + "\n   indented line")
    img = check(render_text(text, size=28, align=align, mono=mono, margin=4))
    lo, hi = black_extent(img)
    assert lo >= 0 and hi <= WIDTH - 1
    # margins respected: nothing drawn in the outer 3 px
    assert lo >= 3 and hi <= WIDTH - 4


def test_wrap_breaks_lines_and_long_words():
    f = font("sans", 28)
    lines = wrap_spans([("aaa bbb ccc " * 10 + "x" * 200, f)], 300)
    assert len(lines) > 3
    for ln in lines:
        assert sum(f.getlength(t) for t, _ in ln) <= 300 + 0.01


def test_wrap_tiny_width_terminates():
    f = font("sans", 28)
    assert wrap_spans([("abc def", f)], 1)


def test_line_spacing_grows_height():
    a = render_text("a\nb\nc", line_spacing=1.0).height
    b = render_text("a\nb\nc", line_spacing=1.5).height
    assert b > a


def test_receipt_columns_align():
    from minixprint.render import receipt as r
    rows, cols, _ = r._layout(RECEIPT)
    mono = font("mono", r.MONO_SIZE)
    assert cols >= 30
    # every left-aligned row is a full-width cell string, so right edges coincide
    left_rows = [t for t, f, a in rows if a == "l" and t]
    assert left_rows
    amount_rows = [t for t in left_rows if t.rstrip()[-3] == "." or "TOTAL" in t or "ITEM" in t]
    assert any("TOTAL" in t for t in amount_rows)
    for t in amount_rows:
        assert len(t) == cols, t
        assert mono.getlength(t) <= WIDTH - 2 * r.MARGIN
    # amounts end on the same column: the decimal point is 3 chars from the right
    for t in left_rows:
        if t.rstrip()[-3:-2] == "." and "INR" not in t:
            assert t[-3] == "."
    total = [t for t, f, a in rows if "TOTAL" in t][0]
    assert "INR" in total
    # 2*180 + 5.5 = 365.5; CGST 2.5% = 9.14 (rounded), fee 3 -> 377.64
    assert "377.64" in total
    check(render_receipt(RECEIPT))


def test_receipt_total_math_and_long_names():
    img = render_receipt(RECEIPT)
    plain = render_receipt({"items": [{"name": "x", "qty": 1, "price": 1}]})
    assert img.height > plain.height  # wrapping / extra sections add height


def test_to_rows_length_and_bits():
    img = Image.new("1", (WIDTH, 3), 1)
    px = img.load()
    px[0, 0] = 0      # first bit of row 0 -> 0x80
    px[7, 0] = 0      # last bit of byte 0
    px[383, 2] = 0    # last bit of last byte of row 2
    rows = to_rows(img)
    assert len(rows) == 3 * 48
    assert rows[0] == 0x81
    assert rows[1] == 0x00
    assert rows[2 * 48 + 47] == 0x01
    assert to_rows(Image.new("1", (WIDTH, 2), 0)) == b"\xff" * 96


def test_to_rows_matches_legacy_pack():
    def pack(img):  # verbatim logic of minix.py pack()
        px = img.load()
        out = bytearray()
        for y in range(img.height):
            for xb in range(48):
                b = 0
                for bit in range(8):
                    if px[xb * 8 + bit, y] == 0:
                        b |= 0x80 >> bit
                out.append(b)
        return bytes(out)
    img = render_receipt(RECEIPT)
    assert to_rows(img) == pack(img)


def test_to_rows_rejects_wrong_width():
    with pytest.raises(ValueError):
        to_rows(Image.new("1", (100, 5), 1))


def test_stack_and_pad_heights():
    a, b = rule("solid"), rule("double")
    assert stack(a, b, gap=8).height == a.height + b.height + 8
    assert pad(a, 3, 5).height == a.height + 8


@pytest.mark.parametrize("md", [
    "", "   \n\n", "---", "***\n---\n___",
    "- a\n  - b\n    - c\n      - d\n- e",
    "1. a\n   1. b\n      - c\n2. d",
    "- - nested immediately", "- ---", "10. ten\n11. eleven",
    "> quote\n> > nested quote\n> - list in quote",
    "```\ncode " + "x" * 200 + "\n```", "    indented code",
    "| a | b |\n|---|---|\n| 1 | 2 |", "<div>html</div>", "![alt](x.png) [link](http://x)",
    "**bold *both* bold** `code`  \nhard break", "#" * 8 + " too deep", "# \n##\n###",
    "\x00 weird ☃ \U0001F600 chars", "line1\\\nline2",
])
def test_markdown_edge_cases(md):
    check(render_markdown(md))


def test_markdown_rule_only_and_empty_heights():
    assert render_markdown("").height == 8
    assert render_markdown("---").height < 40


def test_markdown_headings_are_taller_than_body():
    h1 = render_markdown("# Title").height
    p = render_markdown("Title").height
    assert h1 > p


def test_markdown_bar_drawn_for_blockquote():
    img = render_markdown("> quote")
    # left bar: a black column near the left margin spanning most of the height
    px = img.load()
    col = [px[6, y] for y in range(4, img.height - 4)]
    assert col and all(v == 0 for v in col)


def test_image_dither_deterministic():
    grad = Image.linear_gradient("L").resize((200, 120))
    for mode in ("fs", "atkinson", "none"):
        a = render_image(grad, mode)
        b = render_image(grad, mode)
        assert a.tobytes() == b.tobytes()
        check(a)
    assert render_image(grad, "fs").tobytes() != render_image(grad, "atkinson").tobytes()


def test_image_scaling_gamma_invert_maxheight(tmp_path):
    flat = Image.new("L", (192, 96), 128)
    out = render_image(flat, "none")
    assert out.size == (384, 192)
    white = Image.new("L", (10, 10), 255)
    assert render_image(white, "none").getextrema() == (255, 255)
    assert render_image(white, "none", invert=True).getextrema() == (0, 0)
    bright = render_image(flat, "none", gamma=2.0)  # midtone brightened -> white
    assert bright.getextrema() == (255, 255)
    tall = Image.new("L", (100, 1000), 0)
    clipped = check(render_image(tall, "none", max_height=200))
    assert clipped.height == 200
    p = tmp_path / "x.png"
    flat.save(p)
    assert render_image(str(p), "atkinson").size == (384, 192)


def test_image_alpha_is_white_background():
    rgba = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    assert render_image(rgba, "none").getextrema() == (255, 255)


def test_image_bad_args():
    with pytest.raises(ValueError):
        render_image(Image.new("L", (4, 4)), dither="bogus")


def test_atkinson_preserves_extremes():
    from minixprint.render.image import atkinson
    assert atkinson(Image.new("L", (16, 16), 255)).getextrema() == (255, 255)
    assert atkinson(Image.new("L", (16, 16), 0)).getextrema() == (0, 0)


def test_qr_fills_about_70_percent():
    img = render_qr("https://example.com/some/path")
    lo, hi = black_extent(img)
    frac = (hi - lo + 1) / WIDTH
    assert 0.4 < frac <= 0.75
    with pytest.raises(ValueError):
        render_qr("x" * 50, box_size=50)


def test_barcode_kinds():
    for kind, data in (("code128", "Hello-123"), ("ean13", "590123412345"), ("code39", "ABC123")):
        check(render_barcode(data, kind))
    assert render_barcode("12345", caption=False).height < render_barcode("12345").height
    with pytest.raises(ValueError):
        render_barcode("X" * 200)


def test_fonts_fallback_never_fails():
    for kind in ("sans", "mono"):
        for bold in (False, True):
            assert font(kind, 20, bold, italic=True) is not None
    with pytest.raises(ValueError):
        font("comic")
