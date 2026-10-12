"""Folder watcher: print whatever lands in a directory through the HTTP server (docs/WATCH.md).

Polls every few seconds (no inotify/watchdog dependency, so it also works on network shares and
macOS folders). Images, PDFs, ``.txt`` and ``.md`` are sent to a running ``minixprint serve``;
a ``.minixprint-seen`` index in the folder remembers what was printed so restarts don't reprint.
"""
import json
import logging
import os
import shutil
import time
from typing import Dict, List, Optional

import requests

from . import raster

log = logging.getLogger("minixprint.watch")

SEEN_NAME = ".minixprint-seen"
DEFAULT_SERVER = "http://127.0.0.1:8090"
NATIVE_IMAGES = (".png", ".jpg", ".jpeg")  # sent as-is; the server's Pillow reads them
CONVERT_IMAGES = (".heic", ".heif", ".gif", ".bmp", ".webp", ".tif", ".tiff")
IGNORED_SUFFIXES = (".part", ".crdownload", ".download", ".tmp", ".partial", ".icloud")


class PrintFailed(Exception):
    """Permanent failure (bad file / server rejected it): don't retry."""


class Retry(Exception):
    """Transient failure (server down, 5xx): try again on the next poll."""


def kind_of(name: str) -> Optional[str]:
    low = name.lower()
    if low.startswith("."):
        return None
    ext = os.path.splitext(low)[1]
    if low.endswith(IGNORED_SUFFIXES):
        return None
    if ext in NATIVE_IMAGES + CONVERT_IMAGES:
        return "image"
    return {".pdf": "pdf", ".txt": "text", ".md": "markdown", ".markdown": "markdown"}.get(ext)


class Seen:
    """Index of printed files, keyed by name + size + mtime so an edited file prints again."""

    def __init__(self, directory: str):
        self.path = os.path.join(directory, SEEN_NAME)
        self.keys = set()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.keys = {line.rstrip("\n") for line in f if line.strip()}
        except OSError:
            pass

    @staticmethod
    def key(path: str) -> str:
        st = os.stat(path)
        return "%s\t%d\t%d" % (os.path.basename(path), st.st_size, st.st_mtime_ns)

    def __contains__(self, path: str) -> bool:
        return self.key(path) in self.keys

    def add(self, key: str) -> None:
        self.keys.add(key)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(key + "\n")


class Watcher:
    def __init__(self, directory: str, server: str = DEFAULT_SERVER, dither: str = "atkinson",
                 delete: bool = False, move_to: Optional[str] = None, interval: float = 2.0,
                 settle: float = 1.0):
        if delete and move_to:
            raise ValueError("--delete and --move-to are mutually exclusive")
        if not os.path.isdir(directory):
            raise ValueError("not a directory: %s" % directory)
        self.dir = os.path.abspath(directory)
        self.server = server.rstrip("/")
        self.dither = dither
        self.delete = delete
        self.move_to = os.path.abspath(move_to) if move_to else None
        self.interval = interval
        self.settle = settle  # a file must be unmodified this long (AirDrop / downloads still writing)
        self.seen = Seen(self.dir)
        self.failures: Dict[str, int] = {}
        self.errors = 0  # permanent failures this run

    # -- HTTP ---------------------------------------------------------------------------
    def _post(self, path: str, **kw) -> dict:
        try:
            r = requests.post(self.server + path, timeout=60, **kw)
        except requests.RequestException as e:
            raise Retry("server unreachable: %s" % e)
        if r.status_code >= 500:
            raise Retry("server error %d: %s" % (r.status_code, r.text[:200]))
        if r.status_code >= 400:
            raise PrintFailed("server rejected it (%d): %s" % (r.status_code, r.text[:200]))
        try:
            return r.json()
        except ValueError:
            return {}

    def _send_png(self, png: bytes) -> dict:
        return self._post("/api/print/image", params={"dither": self.dither},
                          files={"file": ("watch.png", png, "image/png")})

    def print_file(self, path: str) -> dict:
        kind = kind_of(path)
        name = os.path.basename(path)
        try:
            if kind == "image":
                if path.lower().endswith(NATIVE_IMAGES):
                    with open(path, "rb") as f:
                        data = f.read()
                    ctype = "image/png" if path.lower().endswith(".png") else "image/jpeg"
                    return self._post("/api/print/image", params={"dither": self.dither},
                                      files={"file": (name, data, ctype)})
                return self._send_png(raster.to_png_bytes(raster.load_image(path)))
            if kind == "pdf":
                img, engine = raster.rasterise_pdf(path)
                log.info("rasterised %s with %s", name, engine)
                return self._send_png(raster.to_png_bytes(img))
            if kind in ("text", "markdown"):
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if not text.strip():
                    raise PrintFailed("empty file")
                field = "text" if kind == "text" else "markdown"
                return self._post("/api/print/" + field, data=json.dumps({field: text}),
                                  headers={"Content-Type": "application/json"})
        except raster.RasterError as e:
            raise PrintFailed(str(e))
        except OSError as e:
            raise Retry(str(e))
        raise PrintFailed("unsupported file type")

    # -- scanning -----------------------------------------------------------------------
    def pending(self) -> List[str]:
        out = []
        now = time.time()
        for name in os.listdir(self.dir):
            path = os.path.join(self.dir, name)
            if not kind_of(name) or not os.path.isfile(path):
                continue
            try:
                if now - os.stat(path).st_mtime < self.settle or path in self.seen:
                    continue
            except OSError:
                continue
            out.append(path)
        out.sort(key=lambda p: (os.stat(p).st_mtime, p))
        return out

    def _dispose(self, path: str) -> None:
        if self.delete:
            os.remove(path)
        elif self.move_to:
            os.makedirs(self.move_to, exist_ok=True)
            dest = os.path.join(self.move_to, os.path.basename(path))
            stem, ext = os.path.splitext(dest)
            n = 1
            while os.path.exists(dest):
                n += 1
                dest = "%s-%d%s" % (stem, n, ext)
            shutil.move(path, dest)

    def scan(self) -> int:
        """Print everything new once; returns the number of files printed. Raises nothing."""
        printed = 0
        for path in self.pending():
            name = os.path.basename(path)
            try:
                key = Seen.key(path)
                res = self.print_file(path)
            except Retry as e:
                self.failures[path] = self.failures.get(path, 0) + 1
                log.warning("%s: %s (will retry)", name, e)
                continue
            except PrintFailed as e:
                log.error("%s: %s (skipping)", name, e)
                self.errors += 1
                self.seen.add(Seen.key(path))
                continue
            except OSError:
                continue  # vanished mid-scan
            self.seen.add(key)
            self.failures.pop(path, None)
            printed += 1
            log.info("printed %s as job %s", name, res.get("id", "?"))
            try:
                self._dispose(path)
            except OSError as e:
                log.warning("%s: could not remove/move: %s", name, e)
        return printed

    def run(self, once: bool = False) -> int:
        """Poll forever (Ctrl-C to stop), or with once=True process what's there and return.
        Returns the process exit status: 1 if any file failed in --once mode."""
        log.info("watching %s -> %s", self.dir, self.server)
        if once:
            deadline = time.time() + self.settle + 5
            while True:
                self.scan()
                # Wait out the settle window for files that arrived a moment ago.
                fresh = [n for n in os.listdir(self.dir) if kind_of(n)
                         and os.path.join(self.dir, n) not in self.seen
                         and os.path.isfile(os.path.join(self.dir, n))]
                if not fresh or time.time() > deadline:
                    return 1 if (fresh or self.errors) else 0
                time.sleep(max(0.05, min(self.settle, 1.0)))
        try:
            while True:
                self.scan()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            return 0
