"""Photo / image preparation: resize to the print width and reduce to 1 bit."""
from typing import Optional, Union

from PIL import Image, ImageOps

from . import WIDTH


def _load(src: Union[str, Image.Image]) -> Image.Image:
    img = Image.open(src) if isinstance(src, (str, bytes)) or hasattr(src, "__fspath__") else src
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    return img.convert("L")


def atkinson(gray: Image.Image) -> Image.Image:
    """Atkinson dither (as on the original Macintosh): returns a mode-"1" image.

    Only 6/8 of the quantisation error is diffused, so highlights and shadows blow
    out to clean white/black instead of speckling; it prints much cleaner on
    thermal paper than Floyd-Steinberg. Pure Python, deterministic.
    """
    w, h = gray.size
    src = gray.tobytes()
    out = bytearray(w * h)
    # Three rolling error rows: current, +1, +2. Padded by 2 on each side.
    r0 = [0.0] * (w + 4)
    r1 = [0.0] * (w + 4)
    r2 = [0.0] * (w + 4)
    for y in range(h):
        base = y * w
        for x in range(w):
            old = src[base + x] + r0[x + 2]
            if old >= 128:
                out[base + x] = 255
                err = (old - 255) / 8.0
            else:
                err = old / 8.0
            r0[x + 3] += err
            r0[x + 4] += err
            r1[x + 1] += err
            r1[x + 2] += err
            r1[x + 3] += err
            r2[x + 2] += err
        r0, r1, r2 = r1, r2, [0.0] * (w + 4)
    return Image.frombytes("L", (w, h), bytes(out)).convert("1")


def render_image(src: Union[str, Image.Image], dither: str = "fs", gamma: float = 1.0,
                 invert: bool = False, max_height: Optional[int] = None) -> Image.Image:
    """Scale to 384 px wide (aspect kept) and dither to 1 bit.

    dither: "fs" (Floyd-Steinberg, Pillow), "atkinson", or "none" (hard threshold).
    gamma: >1 brightens midtones, <1 darkens them (applied before dithering).
    invert: print a negative. max_height: if the scaled image is taller, it is
    scaled down to fit and centred horizontally on white paper.
    """
    if dither not in ("fs", "atkinson", "none"):
        raise ValueError("dither must be fs, atkinson or none, got %r" % (dither,))
    if gamma <= 0:
        raise ValueError("gamma must be > 0")
    img = _load(src)
    scale = WIDTH / img.width
    h = max(1, round(img.height * scale))
    w = WIDTH
    if max_height is not None and h > max_height:
        h = max(1, int(max_height))
        w = max(1, min(WIDTH, round(img.width * h / img.height)))
    img = img.resize((w, h), Image.LANCZOS)
    if gamma != 1.0:
        lut = [round(255 * (v / 255.0) ** (1.0 / gamma)) for v in range(256)]
        img = img.point(lut)
    if invert:
        img = ImageOps.invert(img)
    if dither == "atkinson":
        bw = atkinson(img)
    elif dither == "none":
        bw = img.point([0] * 128 + [255] * 128).convert("1")
    else:
        bw = img.convert("1", dither=Image.FLOYDSTEINBERG)
    if w != WIDTH:
        canvas = Image.new("1", (WIDTH, h), 1)
        canvas.paste(bw, ((WIDTH - w) // 2, 0))
        bw = canvas
    return bw
