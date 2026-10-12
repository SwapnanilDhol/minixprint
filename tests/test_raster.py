import shutil
import sys

import pytest
from PIL import Image

from minixprint import raster


def test_stack_pages_fits_width_and_stacks():
    a = Image.new("L", (768, 100), 255)
    a.paste(0, (0, 0, 768, 10))           # black bar at the top of page 1
    b = Image.new("L", (384, 40), 255)
    b.paste(0, (0, 0, 384, 40))
    out = raster.stack_pages([a, b], trim=False)
    assert out.width == 384
    assert out.height == 50 + 40          # 768x100 -> 384x50
    assert out.getpixel((0, 0)) == 0 and out.getpixel((0, 49)) == 255 and out.getpixel((0, 60)) == 0


def test_trim_bottom_keeps_margin():
    img = Image.new("L", (384, 500), 255)
    img.paste(0, (0, 0, 384, 20))
    out = raster.trim_bottom(img, margin=16)
    assert out.size == (384, 36)


def test_trim_blank_page_is_short():
    out = raster.trim_bottom(Image.new("L", (384, 500), 255), margin=16)
    assert out.height == 16


def test_flatten_alpha_over_white():
    rgba = Image.new("RGBA", (4, 4), (0, 0, 0, 0))     # fully transparent -> white paper
    assert raster._flatten(rgba).getpixel((0, 0)) == 255


def test_engine_order_and_fallback(monkeypatch, tmp_path):
    calls = []

    def bad(name):
        def fn(pdf, tmp):
            calls.append(name)
            raise raster.RasterError(name + " missing")
        return fn

    def good(pdf, tmp):
        calls.append("good")
        return [Image.new("L", (384, 30), 0)]

    monkeypatch.setattr(raster, "ENGINES", [("pdftoppm", bad("pdftoppm")), ("gs", bad("gs")), ("last", good)])
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    img, engine = raster.rasterise_pdf(str(pdf), trim=False)
    assert engine == "last" and calls == ["pdftoppm", "gs", "good"]
    assert img.size == (384, 30)


def test_all_engines_fail(monkeypatch, tmp_path):
    def bad(pdf, tmp):
        raise raster.RasterError("nope")
    monkeypatch.setattr(raster, "ENGINES", [("pdftoppm", bad)])
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(raster.RasterError, match="poppler"):
        raster.rasterise_pdf(str(pdf))


def test_load_image_plain_png(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGB", (10, 5), (1, 2, 3)).save(p)
    assert raster.load_image(str(p)).size == (10, 5)


def test_load_image_unreadable(tmp_path):
    p = tmp_path / "a.heic"
    p.write_bytes(b"not an image")
    with pytest.raises(raster.RasterError):
        raster.load_image(str(p))


@pytest.mark.skipif(not (shutil.which("pdftoppm") or shutil.which("gs") or sys.platform == "darwin"),
                    reason="no PDF rasteriser")
def test_real_pdf_roundtrip(tmp_path):
    # Minimal one-page PDF with a filled black box.
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R>>"]
    stream = b"0 g 20 20 100 40 re f"
    objs.append(b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 5\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % xref
    pdf = tmp_path / "box.pdf"
    pdf.write_bytes(out)
    img, engine = raster.rasterise_pdf(str(pdf), trim=False)
    assert img.width == 384 and img.mode == "L"
    assert img.getextrema()[0] < 40       # the black box survived
