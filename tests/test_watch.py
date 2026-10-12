import json
import os
import time

import pytest
import requests
from PIL import Image

from minixprint import cli, watch


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.text = json.dumps(body or {"id": 1})
        self._body = body or {"id": 1}

    def json(self):
        return self._body


@pytest.fixture
def posts(monkeypatch):
    class Calls(list):
        pass
    calls = Calls()
    state = {"resp": lambda: FakeResp()}

    def fake_post(url, **kw):
        calls.append((url, kw))
        r = state["resp"]()
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(watch.requests, "post", fake_post)
    calls.state = state
    return calls


def mk(tmp_path, name, data=b"x"):
    p = tmp_path / name
    p.write_bytes(data)
    old = time.time() - 10
    os.utime(p, (old, old))
    return p


def png_bytes():
    import io
    b = io.BytesIO()
    Image.new("RGB", (30, 20), (200, 10, 10)).save(b, "PNG")
    return b.getvalue()


def W(tmp_path, **kw):
    return watch.Watcher(str(tmp_path), "http://srv:1/p/", settle=0, **kw)


def test_kinds():
    assert watch.kind_of("a.PNG") == "image" and watch.kind_of("a.heic") == "image"
    assert watch.kind_of("a.pdf") == "pdf" and watch.kind_of("a.txt") == "text"
    assert watch.kind_of("a.md") == "markdown"
    for n in (".minixprint-seen", ".DS_Store", ".hidden.png", "a.png.crdownload", "a.zip", "a"):
        assert watch.kind_of(n) is None


def test_prints_image_text_markdown(tmp_path, posts):
    mk(tmp_path, "a.png", png_bytes())
    mk(tmp_path, "b.txt", b"hello\n")
    mk(tmp_path, "c.md", b"# Title\n")
    assert W(tmp_path, dither="none").scan() == 3
    by_url = {c[0]: c[1] for c in posts}
    img = by_url["http://srv:1/p/api/print/image"]
    assert img["params"] == {"dither": "none"} and img["files"]["file"][2] == "image/png"
    assert json.loads(by_url["http://srv:1/p/api/print/text"]["data"]) == {"text": "hello\n"}
    assert json.loads(by_url["http://srv:1/p/api/print/markdown"]["data"]) == {"markdown": "# Title\n"}


def test_seen_index_survives_restart(tmp_path, posts):
    mk(tmp_path, "a.txt", b"hi")
    assert W(tmp_path).scan() == 1
    assert (tmp_path / watch.SEEN_NAME).read_text().startswith("a.txt\t")
    assert W(tmp_path).scan() == 0 and len(posts) == 1
    # editing the file prints it again
    mk(tmp_path, "a.txt", b"hi there")
    assert W(tmp_path).scan() == 1 and len(posts) == 2


def test_delete_and_move(tmp_path, posts):
    mk(tmp_path, "a.txt", b"1")
    W(tmp_path, delete=True).scan()
    assert not (tmp_path / "a.txt").exists()
    mk(tmp_path, "b.txt", b"2")
    mk(tmp_path, "c.txt", b"3")
    dest = tmp_path / "done"
    w = W(tmp_path, move_to=str(dest))
    w.scan()
    assert sorted(os.listdir(dest)) == ["b.txt", "c.txt"]
    mk(tmp_path, "b.txt", b"22")       # same name again: no overwrite
    w.scan()
    assert sorted(os.listdir(dest)) == ["b-2.txt", "b.txt", "c.txt"]


def test_delete_and_move_exclusive(tmp_path):
    with pytest.raises(ValueError):
        watch.Watcher(str(tmp_path), delete=True, move_to=str(tmp_path / "x"))


def test_server_down_retries_then_prints(tmp_path, posts):
    mk(tmp_path, "a.txt", b"hi")
    posts.state["resp"] = lambda: requests.ConnectionError("down")
    w = W(tmp_path)
    assert w.scan() == 0 and not (tmp_path / watch.SEEN_NAME).exists()
    posts.state["resp"] = lambda: FakeResp()
    assert w.scan() == 1


def test_5xx_retries_4xx_skips(tmp_path, posts):
    mk(tmp_path, "a.txt", b"hi")
    posts.state["resp"] = lambda: FakeResp(503, {"detail": "busy"})
    w = W(tmp_path)
    assert w.scan() == 0 and not (tmp_path / watch.SEEN_NAME).exists()
    posts.state["resp"] = lambda: FakeResp(415, {"detail": "bad image"})
    assert w.scan() == 0 and w.errors == 1
    n = len(posts)
    w.scan()
    assert len(posts) == n            # recorded as seen: no retry loop


def test_settle_skips_fresh_files(tmp_path, posts):
    p = tmp_path / "a.txt"
    p.write_text("hi")
    w = watch.Watcher(str(tmp_path), settle=30)
    assert w.scan() == 0 and not posts


def test_empty_text_skipped(tmp_path, posts):
    mk(tmp_path, "a.txt", b"  \n")
    w = W(tmp_path)
    assert w.scan() == 0 and not posts and w.errors == 1


def test_pdf_goes_through_rasteriser(tmp_path, posts, monkeypatch):
    mk(tmp_path, "a.pdf", b"%PDF")
    monkeypatch.setattr(watch.raster, "rasterise_pdf", lambda p: (Image.new("L", (384, 50), 0), "fake"))
    assert W(tmp_path).scan() == 1
    url, kw = posts[0]
    assert url.endswith("/api/print/image") and kw["files"]["file"][2] == "image/png"
    assert Image.open(__import__("io").BytesIO(kw["files"]["file"][1])).size == (384, 50)


def test_heic_converted_via_loader(tmp_path, posts, monkeypatch):
    mk(tmp_path, "a.heic", b"heic")
    monkeypatch.setattr(watch.raster, "load_image", lambda p: Image.new("RGB", (8, 8)))
    assert W(tmp_path).scan() == 1
    assert posts[0][1]["files"]["file"][0] == "watch.png"


def test_rasterise_failure_is_permanent(tmp_path, posts, monkeypatch):
    mk(tmp_path, "a.pdf", b"%PDF")

    def boom(p):
        raise watch.raster.RasterError("no engine")
    monkeypatch.setattr(watch.raster, "rasterise_pdf", boom)
    w = W(tmp_path)
    assert w.scan() == 0 and w.errors == 1 and not posts


def test_once_exit_status(tmp_path, posts):
    mk(tmp_path, "a.txt", b"hi")
    assert W(tmp_path).run(once=True) == 0
    mk(tmp_path, "b.txt", b"hi2")
    posts.state["resp"] = lambda: FakeResp(422, {"detail": "no"})
    assert W(tmp_path).run(once=True) == 1


def test_cli_watch_once(tmp_path, posts):
    mk(tmp_path, "a.txt", b"hi")
    rc = cli.main(["watch", str(tmp_path), "--server", "http://h:9", "--once", "--dither", "fs"])
    assert rc == 0 and posts[0][0] == "http://h:9/api/print/text"


def test_cli_watch_bad_dir(tmp_path):
    assert cli.main(["watch", str(tmp_path / "nope"), "--once"]) == 1
