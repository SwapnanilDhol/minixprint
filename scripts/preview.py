#!/usr/bin/env python3
"""Render content to a PNG so you can inspect it without a printer.

    python3 scripts/preview.py text "Hello there" out.png [--size 40 --align center --bold --mono]
    python3 scripts/preview.py md   "# Title\n- a\n- b" out.png     (or @file.md, or - for stdin)
    python3 scripts/preview.py receipt receipt.json out.png         (or --sample)
    python3 scripts/preview.py image photo.jpg out.png [--dither atkinson --gamma 1.2 --invert]
    python3 scripts/preview.py qr "https://example.com" out.png [--caption "scan me"]
    python3 scripts/preview.py barcode 123456789 out.png [--kind code128]

Add --scale N to enlarge the PNG for viewing (nearest-neighbour; the render itself is 384 px).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import Image  # noqa: E402

from minixprint.render import (  # noqa: E402
    render_barcode,
    render_image,
    render_markdown,
    render_qr,
    render_receipt,
    render_text,
)

SAMPLE_RECEIPT = {
    "title": "DOSA & CO.",
    "subtitle_lines": ["South Indian Kitchen", "12 MG Road, Bengaluru 560001", "GSTIN 29ABCDE1234F1Z5"],
    "meta": {"Bill #1042": "12 Oct 2026 19:30", "Table 7": "Server: Priya"},
    "items": [
        {"name": "Masala Dosa", "qty": 2, "price": 180},
        {"name": "Filter Coffee", "qty": 2, "price": 60},
        {"name": "Paneer Butter Masala", "qty": 1, "price": 320},
        {"name": "Butter Naan", "qty": 3, "price": 45},
        {"name": "Gulab Jamun", "qty": 1, "price": 90},
    ],
    "taxes": [{"label": "CGST", "rate": 2.5}, {"label": "SGST", "rate": 2.5}],
    "currency": "INR",
    "footer_lines": ["Thank you! Visit again", "dosaandco.in"],
    "qr": "https://dosaandco.in",
}


def arg_text(s):
    if s == "-":
        return sys.stdin.read()
    if s.startswith("@"):
        with open(s[1:], encoding="utf-8") as fh:
            return fh.read()
    return s.replace("\\n", "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("text", "md", "receipt", "image", "qr", "barcode"):
        p = sub.add_parser(name)
        if name == "receipt":
            p.add_argument("input", nargs="?", help="JSON file (omit with --sample)")
            p.add_argument("--sample", action="store_true")
        else:
            p.add_argument("input")
        p.add_argument("out", nargs="?", default="out.png")
        p.add_argument("--scale", type=int, default=1)
        if name == "text":
            p.add_argument("--size", type=int, default=28)
            p.add_argument("--align", default="left", choices=["left", "center", "right"])
            p.add_argument("--bold", action="store_true")
            p.add_argument("--mono", action="store_true")
            p.add_argument("--line-spacing", type=float, default=1.0)
        if name == "image":
            p.add_argument("--dither", default="fs", choices=["fs", "atkinson", "none"])
            p.add_argument("--gamma", type=float, default=1.0)
            p.add_argument("--invert", action="store_true")
            p.add_argument("--max-height", type=int)
        if name == "qr":
            p.add_argument("--caption")
        if name == "barcode":
            p.add_argument("--kind", default="code128")
    a = ap.parse_args(argv)

    if a.cmd == "text":
        img = render_text(arg_text(a.input), a.size, a.align, a.bold, a.mono, line_spacing=a.line_spacing)
    elif a.cmd == "md":
        img = render_markdown(arg_text(a.input))
    elif a.cmd == "receipt":
        if a.sample or not a.input:
            if a.input:  # `receipt --sample out.png`: the lone path is the output
                a.out = a.input
            data = SAMPLE_RECEIPT
        else:
            with open(a.input, encoding="utf-8") as fh:
                data = json.load(fh)
        img = render_receipt(data)
    elif a.cmd == "image":
        img = render_image(a.input, a.dither, a.gamma, a.invert, a.max_height)
    elif a.cmd == "qr":
        img = render_qr(arg_text(a.input), a.caption)
    else:
        img = render_barcode(a.input, a.kind)

    assert img.mode == "1" and img.width == 384
    out = img
    if a.scale > 1:
        out = img.convert("L").resize((img.width * a.scale, img.height * a.scale), Image.NEAREST)
    out.save(a.out)
    print("wrote %s  %dx%d" % (a.out, img.width, img.height))


if __name__ == "__main__":
    main()
