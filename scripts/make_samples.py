#!/usr/bin/env python3
"""Regenerate docs/samples/*.png (referenced from docs/RENDER.md)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from preview import SAMPLE_RECEIPT  # noqa: E402

from minixprint.render import (  # noqa: E402
    render_barcode,
    render_image,
    render_markdown,
    render_qr,
    render_receipt,
    render_text,
    rule,
    stack,
)

OUT = os.path.join(ROOT, "docs", "samples")
os.makedirs(OUT, exist_ok=True)

MD = """# Weekend plan
Some **bold**, some *italic* and `inline code` in a paragraph that wraps over several lines.

## Shopping
- Coffee beans
- Oat milk
  - barista edition
  - unsweetened
- Paper rolls

### Steps
1. Boil water
2. Grind beans
3. Pour slowly

> Measure twice, cut once.

---
```
$ minix status
battery 87%
```
"""

samples = {
    "text": render_text("Hello from the MiniX!\nA long line of text wraps at the paper edge, "
                        "and explicit newlines are kept.", size=28),
    "text_center_bold": render_text("SALE\n50% OFF", size=44, align="center", bold=True),
    "markdown": render_markdown(MD),
    "receipt": render_receipt(SAMPLE_RECEIPT),
    "qr": render_qr("https://github.com/", caption="scan me"),
    "barcode": render_barcode("MINIX-0042"),
    "rules": stack(rule("solid"), rule("dashed"), rule("double"), gap=4),
}
photo = os.path.join(ROOT, "test_photo.png")
if os.path.exists(photo):
    samples["image_fs"] = render_image(photo, "fs")
    samples["image_atkinson"] = render_image(photo, "atkinson")
for name, img in samples.items():
    img.save(os.path.join(OUT, name + ".png"))
    print(name, img.size)
