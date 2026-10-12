"""Rasterise PDFs and odd image formats to 384 px wide greyscale; shared by the CUPS backend
and the folder watcher (docs/CUPS.md, docs/WATCH.md).

PDF engines, tried in order: ``pdftoppm`` (poppler), ``gs`` (ghostscript), then on macOS
``qlmanage`` (Quick Look thumbnail, ~1500 px) and ``sips`` (72 dpi), both first page only. Everything returns a
Pillow mode-"L" image; dithering happens in the server.
"""
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, List, Tuple

from PIL import Image

# Not imported from .render: that pulls in every renderer, and the CUPS backend installs
# this file on its own (deploy/cups/install.sh).
WIDTH = 384
DPI = 203
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".heic", ".heif", ".gif", ".bmp", ".webp", ".tif", ".tiff")


class RasterError(Exception):
    pass


def _run(cmd: List[str], timeout: int = 120) -> None:
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RasterError("%s: %s" % (cmd[0], e))
    if r.returncode != 0:
        raise RasterError("%s failed: %s" % (cmd[0], r.stderr.decode("utf-8", "replace").strip()[:300]))


def _flatten(im: Image.Image) -> Image.Image:
    """To greyscale, compositing transparency onto white paper (sips emits RGBA)."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, rgba)
    return im.convert("L")


def _load_all(paths: List[str]) -> List[Image.Image]:
    pages = []
    for p in paths:
        with Image.open(p) as im:
            pages.append(_flatten(im))
    return pages


def _pdftoppm(pdf: str, tmp: str) -> List[Image.Image]:
    exe = shutil.which("pdftoppm")
    if not exe:
        raise RasterError("pdftoppm not installed")
    # -r only sets the scale of the intermediate render; -scale-to-x pins the final width.
    _run([exe, "-gray", "-r", str(DPI), "-scale-to-x", str(WIDTH), "-scale-to-y", "-1",
          pdf, os.path.join(tmp, "p")])
    return _load_all(sorted(glob.glob(os.path.join(tmp, "p*.pgm"))))


def _gs(pdf: str, tmp: str) -> List[Image.Image]:
    exe = shutil.which("gs")
    if not exe:
        raise RasterError("gs not installed")
    # No "scale to width" in gs: render at DPI and let _fit() resample.
    _run([exe, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pnggray", "-r%d" % DPI,
          "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4",
          "-sOutputFile=" + os.path.join(tmp, "p%04d.png"), pdf])
    return _load_all(sorted(glob.glob(os.path.join(tmp, "p*.png"))))


def _sips(pdf: str, tmp: str) -> List[Image.Image]:
    exe = shutil.which("sips")
    if not exe:
        raise RasterError("sips not installed")
    out = os.path.join(tmp, "p0001.png")
    _run([exe, "-s", "format", "png", pdf, "--out", out])
    return _load_all([out])


def _qlmanage(pdf: str, tmp: str) -> List[Image.Image]:
    exe = shutil.which("qlmanage")
    if not exe:
        raise RasterError("qlmanage not installed")
    _run([exe, "-t", "-s", "2000", "-o", tmp, pdf])
    return _load_all(glob.glob(os.path.join(tmp, "*.png")))


ENGINES: List[Tuple[str, Callable[[str, str], List[Image.Image]]]] = [
    ("pdftoppm", _pdftoppm), ("gs", _gs), ("qlmanage", _qlmanage), ("sips", _sips),
]


def _fit(img: Image.Image) -> Image.Image:
    if img.width != WIDTH:
        img = img.resize((WIDTH, max(1, round(img.height * WIDTH / img.width))), Image.LANCZOS)
    return img


def trim_bottom(img: Image.Image, margin: int = 16, white: int = 250) -> Image.Image:
    """Drop blank paper at the bottom of a page (keeping `margin` px) so a Letter/A4 page
    with three lines of text doesn't feed a metre of empty paper."""
    inv = img.point([255 if v < white else 0 for v in range(256)])
    box = inv.getbbox()
    if box is None:
        return img.crop((0, 0, img.width, min(img.height, margin)))
    return img.crop((0, 0, img.width, min(img.height, box[3] + margin)))


def stack_pages(pages: List[Image.Image], trim: bool = True) -> Image.Image:
    pages = [_fit(p) for p in pages]
    if trim:
        pages = [trim_bottom(p) for p in pages]
    out = Image.new("L", (WIDTH, sum(p.height for p in pages)), 255)
    y = 0
    for p in pages:
        out.paste(p, (0, y))
        y += p.height
    return out


def rasterise_pdf(path: str, trim: bool = True) -> Tuple[Image.Image, str]:
    """All pages of a PDF stacked into one 384 px wide "L" image, plus the engine used."""
    errors = []
    for name, fn in ENGINES:
        if name in ("sips", "qlmanage") and sys.platform != "darwin":
            continue
        with tempfile.TemporaryDirectory(prefix="minixraster") as tmp:
            try:
                pages = fn(path, tmp)
            except (RasterError, OSError, ValueError) as e:
                errors.append(str(e))
                continue
            if pages:
                return stack_pages(pages, trim), name
            errors.append("%s produced no pages" % name)
    raise RasterError("cannot rasterise %s (install poppler-utils: apt install poppler-utils / "
                      "brew install poppler): %s" % (os.path.basename(path), "; ".join(errors)))


def load_image(path: str) -> Image.Image:
    """Open an image Pillow may not read (HEIC): falls back to ``sips`` on macOS."""
    try:
        with Image.open(path) as im:
            im.load()
            return im.copy()
    except Exception as first:
        sips = shutil.which("sips") if sys.platform == "darwin" else None
        if not sips:
            raise RasterError("cannot read %s: %s" % (os.path.basename(path), first))
        with tempfile.TemporaryDirectory(prefix="minixraster") as tmp:
            out = os.path.join(tmp, "x.png")
            _run([sips, "-s", "format", "png", path, "--out", out])
            with Image.open(out) as im:
                im.load()
                return im.copy()


def to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def available_engines() -> List[str]:
    names = []
    for n, exe in (("pdftoppm", "pdftoppm"), ("gs", "gs"), ("sips", "sips"), ("qlmanage", "qlmanage")):
        if shutil.which(exe) and (n in ("pdftoppm", "gs") or sys.platform == "darwin"):
            names.append(n)
    return names
