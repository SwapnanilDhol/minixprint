"""minixprint command line: see docs/CLI.md."""
import argparse
import json
import logging
import sys
from typing import Optional

from . import render
from .printer import connect
from .render import WIDTH
from .transport import TransportError

STRIPE_H, STRIPE_BAND = 120, 20


def _stripes():
    from PIL import Image, ImageDraw
    img = Image.new("1", (WIDTH, STRIPE_H), 1)
    d = ImageDraw.Draw(img)
    for y in range(0, STRIPE_H, 2 * STRIPE_BAND):
        d.rectangle([0, y, WIDTH - 1, y + STRIPE_BAND - 1], fill=0)
    return img


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def _text_image(a, text):
    return render.render_text(text, size=a.size, align=a.align, bold=a.bold, mono=a.mono)


def build_image(a):
    """Image for a print command (None for non-image commands)."""
    c = a.cmd
    if c == "text":
        return _text_image(a, _read("-") if a.text == "-" else a.text)
    if c == "pipe":
        return _text_image(a, sys.stdin.read())
    if c == "md":
        return render.render_markdown(_read(a.file))
    if c == "receipt":
        with open(a.file, encoding="utf-8") as f:
            return render.render_receipt(json.load(f))
    if c == "image":
        return render.render_image(a.file, dither=a.dither)
    if c == "qr":
        return render.render_qr(a.data, caption=a.caption)
    if c == "stripes":
        return _stripes()
    return None


def _add_text_opts(p):
    p.add_argument("--size", type=int, default=28, help="font size in px (default 28)")
    p.add_argument("--align", choices=["left", "center", "right"], default="left")
    p.add_argument("--bold", action="store_true")
    p.add_argument("--mono", action="store_true")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="minixprint", description="Seznik MiniX thermal printer")
    ap.add_argument("--usb", action="store_const", const="usb", dest="prefer", help="force USB")
    ap.add_argument("--ble", action="store_const", const="ble", dest="prefer",
                    help="force Bluetooth LE (printer must be unplugged from USB)")
    ap.set_defaults(prefer="auto")
    ap.add_argument("--port", help="USB serial port (default: auto-detect)")
    ap.add_argument("--name", help="BLE name prefix (default 'Seznik MiniX')")
    ap.add_argument("--density", type=int, choices=[0, 1, 2], default=2)
    ap.add_argument("-v", "--verbose", action="store_true", help="log every byte to stderr")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    sub.add_parser("info", help="identity, firmware, battery")
    sub.add_parser("status", help="status flags")
    f = sub.add_parser("feed", help="feed paper")
    f.add_argument("dots", nargs="?", type=int, default=80)

    p = sub.add_parser("serve", help="run the HTTP server + dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--root-path", default="", help='URL prefix when behind a proxy, e.g. "/print"')
    p.add_argument("--fake", action="store_true", help="no printer: archive jobs only")

    p = sub.add_parser("watch", help="print every new file dropped in a folder (docs/WATCH.md)")
    p.add_argument("dir")
    p.add_argument("--server", default="http://127.0.0.1:8090", help="print server URL")
    p.add_argument("--dither", choices=["fs", "atkinson", "none"], default="atkinson")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--delete", action="store_true", help="delete files after printing")
    g.add_argument("--move-to", metavar="DIR", help="move files here after printing")
    p.add_argument("--once", action="store_true", help="print what is there and exit")
    p.add_argument("--interval", type=float, default=2.0, help="poll seconds (default 2)")

    p = sub.add_parser("feeds", help="manage live feeds on a running server (docs/FEEDS.md)")
    p.add_argument("--server", default="http://127.0.0.1:8090", help="print server URL")
    fs = p.add_subparsers(dest="action", metavar="ACTION")
    fs.add_parser("list", help="list feeds (default)")
    fs.add_parser("kinds", help="list feed kinds and their params")
    q = fs.add_parser("add", help="add a feed and start it: add metar VOMM | add acars [key=value ...]")
    q.add_argument("kind")
    q.add_argument("args", nargs="*", help="first positional is the required param (e.g. the station), "
                   "or key=value pairs; list values are comma separated")
    q.add_argument("--interval", type=int, help="poll seconds (default per kind)")
    q.add_argument("--paused", action="store_true", help="create stopped")
    for name in ("start", "stop", "poll", "rm"):
        q = fs.add_parser(name, help={"start": "start a feed", "stop": "stop a feed",
                                      "poll": "poll now", "rm": "delete a feed"}[name])
        q.add_argument("id", type=int)

    printers = []
    p = sub.add_parser("text", help='print text ("-" reads stdin)')
    p.add_argument("text")
    _add_text_opts(p)
    printers.append(p)
    p = sub.add_parser("pipe", help="print stdin as text")
    _add_text_opts(p)
    printers.append(p)
    p = sub.add_parser("md", help="print a Markdown file (- for stdin)")
    p.add_argument("file")
    printers.append(p)
    p = sub.add_parser("receipt", help="print a receipt from JSON")
    p.add_argument("file")
    printers.append(p)
    p = sub.add_parser("image", help="print an image")
    p.add_argument("file")
    p.add_argument("--dither", choices=["fs", "atkinson", "none"], default="fs")
    printers.append(p)
    p = sub.add_parser("qr", help="print a QR code")
    p.add_argument("data")
    p.add_argument("--caption")
    printers.append(p)
    printers.append(sub.add_parser("stripes", help="test pattern"))
    for p in printers:
        p.add_argument("--out", metavar="PNG", help="write a PNG preview instead of printing")
        p.add_argument("--feed", type=int, default=100, help="dots to feed after printing")
    return ap


def _feed_params(kind: dict, args: list) -> dict:
    """['VOMM'] -> {'station': 'VOMM'} (first required param); 'k=v' pairs are explicit."""
    params = {}
    required = [n for n, sp in kind["params"].items() if sp.get("required")]
    for arg in args:
        if "=" in arg:
            k, v = arg.split("=", 1)
            params[k] = v
        elif required:
            params[required.pop(0)] = arg
        else:
            raise ValueError("unexpected argument %r (use key=value)" % arg)
    return params


def _feeds(a) -> int:
    import requests
    base = a.server.rstrip("/")

    def call(method, path, **kw):
        try:
            r = requests.request(method, base + path, timeout=60, **kw)
        except requests.RequestException as e:
            raise ValueError("cannot reach %s: %s" % (base, e))
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ValueError(str(detail))
        return r.json() if r.content else None

    def show(f):
        what = f["kind"] + (" " + f["params"]["station"] if "station" in f["params"] else "")
        print("%-3s %-2s %-14s every %4ss  printed %-4s %s" % (
            f["id"], "on" if f["enabled"] else "--", what, f["interval_s"], f["printed"],
            ("ERROR: " + f["error"]) if f["error"] else ""))

    try:
        act = a.action or "list"
        if act == "list":
            rows = call("GET", "/api/feeds")
            if not rows:
                print("no feeds")
            for f in rows:
                show(f)
        elif act == "kinds":
            for k in call("GET", "/api/feeds/kinds"):
                print("%-8s every %ss  %s" % (k["kind"], k["default_interval_s"], k["description"]))
                for n, sp in k["params"].items():
                    print("    %s (%s)%s" % (n, sp["type"], " required" if sp.get("required") else
                                             " default %s" % sp.get("default")))
        elif act == "add":
            kinds = {k["kind"]: k for k in call("GET", "/api/feeds/kinds")}
            if a.kind not in kinds:
                raise ValueError("unknown kind %r; available: %s" % (a.kind, ", ".join(sorted(kinds))))
            body = {"kind": a.kind, "params": _feed_params(kinds[a.kind], a.args), "enabled": not a.paused}
            if a.interval:
                body["interval_s"] = a.interval
            show(call("POST", "/api/feeds", json=body))
        elif act in ("start", "stop", "poll"):
            show(call("POST", "/api/feeds/%d/%s" % (a.id, act)))
        elif act == "rm":
            call("DELETE", "/api/feeds/%d" % a.id)
    except ValueError as e:
        print("minixprint: %s" % e, file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[list] = None) -> int:
    a = parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.WARNING,
                        format="[%(created).3f] %(message)s", stream=sys.stderr)
    if a.cmd == "serve":
        import uvicorn

        from .server import create_app
        logging.getLogger().setLevel(logging.INFO)
        uvicorn.run(create_app(fake=a.fake, root_path=a.root_path), host=a.host, port=a.port)
        return 0
    if a.cmd == "feeds":
        return _feeds(a)
    if a.cmd == "watch":
        from .watch import Watcher
        logging.getLogger().setLevel(logging.INFO)
        try:
            return Watcher(a.dir, a.server, a.dither, a.delete, a.move_to, a.interval).run(a.once)
        except ValueError as e:
            print("minixprint: %s" % e, file=sys.stderr)
            return 1
    try:
        img = build_image(a)
        if img is not None and getattr(a, "out", None):
            img.save(a.out)
            print("wrote %s (%dx%d)" % (a.out, img.width, img.height))
            return 0
        with connect(a.prefer, a.port, a.name) as p:
            if a.cmd == "info":
                for k, v in p.info().items():
                    print("%-9s %s" % (k, v))
                print("%-9s %s" % ("battery%", p.battery()))
            elif a.cmd == "status":
                print(p.status())
            elif a.cmd == "feed":
                p.feed(a.dots)
            else:
                print(p.print_image(img, a.density, a.feed))
    except (TransportError, OSError, ValueError) as e:
        print("minixprint: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
