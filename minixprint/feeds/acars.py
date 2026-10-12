"""ACARS feed: prints a ticket for each new message that a human can read or libacars can decode."""
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from ..jobs import _aviation_data as ad
from ..jobs.aviation import M, _fit
from ..render import WIDTH, font, pad, render_text, rule, stack
from ..render.compose import blank
from . import acars_decode as dec
from . import acars_udp as udp

KIND = "acars"
DESCRIPTION = "Print a ticket for every readable or decodable ACARS message the receiver gets"
SOURCES = ["auto", "acarsdec", "bot", "acarshub"]
PARAMS = {
    "source": {"type": "enum", "options": SOURCES, "default": "auto", "label": "Source"},
    "udp_port": {"type": "int", "default": udp.DEFAULT_PORT, "label": "acarsdec UDP port"},
    "print_binary": {"type": "bool", "default": False, "label": "Print encrypted/binary payloads"},
    "skip_labels": {"type": "list", "default": ["Q0", "_d", "Q1"], "label": "Skip labels"},
    "min_text_len": {"type": "int", "default": 1, "label": "Min text length"},
}
DEFAULT_INTERVAL_S = 15
FIRST_POLL_CAP = 3     # a brand-new feed prints at most this many (newest) messages
MAX_PER_POLL = 20      # burst guard
FETCH_LIMIT = 100
COLLAPSE_S = 20        # same flight within this many seconds -> one ticket
MAX_TEXT = 700
MAX_HEIGHT = 580       # px; messages that would push a ticket past this are cut ("+N more")
ACARSHUB_URL = "http://127.0.0.1:8081"
UDP_ID_FLOOR = 10 ** 11  # UDP ids are epoch milliseconds; bot ids are small row numbers


def resolve_source(params: dict) -> str:
    """``auto`` is acarsdec once UDP traffic has been seen on the port, else the bot."""
    src = params.get("source") or "auto"
    if src != "auto":
        return src
    port = int(params.get("udp_port") or udp.DEFAULT_PORT)
    try:
        udp.get_listener(port)  # listen from now on, so traffic can be noticed
    except RuntimeError:
        return "bot"
    return "acarsdec" if udp.traffic_seen(port) else "bot"


def _base(params: dict, ctx) -> str:
    if params.get("source") == "acarshub":
        return str(ctx.setting("acarshub_url") or ACARSHUB_URL).rstrip("/")
    return str(ctx.setting("aviation_bot_url") or "").rstrip("/")


def _flight(msg: dict) -> str:
    return str(msg.get("callsign") or msg.get("registration") or msg.get("icao") or "?")


def collapse(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group oldest-first messages: same flight, each within COLLAPSE_S of the previous."""
    groups = []  # type: List[Dict[str, Any]]
    for m in msgs:
        g = groups[-1] if groups else None
        if g and g["flight"] == _flight(m) and (m.get("ts") or 0) - (g["messages"][-1].get("ts") or 0) <= COLLAPSE_S:
            g["messages"].append(m)
            g["key"] = str(m["id"])
        else:
            groups.append({"key": str(m["id"]), "flight": _flight(m), "ts": m.get("ts"), "messages": [m]})
    return groups


def _is_decoded(m: Dict[str, Any]) -> bool:
    return bool(m.get("libacars") or str(m.get("decoded") or "").strip())


def _keep(m: Dict[str, Any], skip: set, min_len: int, print_binary: bool) -> bool:
    m["class"] = dec.classify(m.get("text"), _is_decoded(m))
    if str(m.get("label") or "").lower() in skip:
        return False
    if m["class"] == "binary":
        return print_binary
    return m["class"] == "decoded" or len(m.get("text") or "") >= min_len


def _fetch_udp(params: dict, cursor: Optional[int], ctx) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    lst = udp.get_listener(int(params.get("udp_port") or udp.DEFAULT_PORT))
    cursor = cursor if isinstance(cursor, int) and cursor >= UDP_ID_FLOOR else None
    msgs = sorted(lst.since(cursor), key=lambda m: m["id"])
    # a brand-new feed starts "now": an empty buffer must not let later traffic look old
    new_cursor = msgs[-1]["id"] if msgs else cursor if cursor is not None else int(ctx.now() * 1000) - 1
    return msgs, new_cursor


def _fetch_http(params: dict, cursor: Optional[int], ctx, source: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    base = _base({"source": source}, ctx)
    if not base:
        raise RuntimeError("no ACARS source URL configured (aviation_bot_url)")
    data = ad.get_json(ctx, base + "/api/messages", {"limit": FETCH_LIMIT})
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise RuntimeError("ACARS source %s unreachable or returned no message list" % base)
    if isinstance(cursor, int) and cursor >= UDP_ID_FLOOR:
        cursor = None  # switched over from the UDP source
    msgs = sorted((m for m in data["items"] if isinstance(m, dict) and isinstance(m.get("id"), int)),
                  key=lambda m: m["id"])
    new_cursor = max([m["id"] for m in msgs] + ([cursor] if cursor is not None else [])) if msgs else cursor
    if cursor is not None:
        msgs = [m for m in msgs if m["id"] > cursor]
    return msgs, new_cursor


def poll(params: dict, cursor: Optional[int], ctx) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    source = resolve_source(params)
    if source == "acarsdec":
        msgs, new_cursor = _fetch_udp(params, cursor, ctx)
        fresh = cursor is None or cursor < UDP_ID_FLOOR
    else:
        msgs, new_cursor = _fetch_http(params, cursor, ctx, source)
        fresh = cursor is None or cursor >= UDP_ID_FLOOR
    skip = {s.lower() for s in params.get("skip_labels") or []}
    min_len = int(params.get("min_text_len") or 0)
    print_binary = bool(params.get("print_binary"))
    msgs = [m for m in msgs if _keep(m, skip, min_len, print_binary)]
    msgs = msgs[-(FIRST_POLL_CAP if fresh else MAX_PER_POLL):]
    return collapse(msgs), new_cursor


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + " ..."


def _differs(summary: str, text: str) -> bool:
    s = summary.rstrip("….").strip()
    return bool(s) and not text.strip().startswith(s)


def _body(m: Dict[str, Any], ts: Optional[float], home) -> List[Image.Image]:
    """Ticket blocks for one message: decoded content, else readable text, else a placeholder."""
    cls = m.get("class") or dec.classify(m.get("text"), _is_decoded(m))
    text = m.get("text") or ""
    out = []  # type: List[Image.Image]
    lines = dec.describe(m.get("libacars"), m.get("ts"), home) if m.get("libacars") else []
    if lines:
        groups = []  # type: List[list]
        for style, t in lines:  # consecutive lines of one style share a block (less gap on paper)
            if groups and groups[-1][0] == style and style != "b":
                groups[-1][1].append(t)
            else:
                groups.append([style, [t]])
        for style, ts in groups:
            out.append(render_text("\n".join(ts), size=16 if style == "b" else 15, bold=style == "b",
                                   mono=style == "m", margin=M))
        return out
    decoded = str(m.get("decoded") or "").strip()
    if decoded:
        return [render_text(_clean(decoded), size=15, mono=True, margin=M)]
    if cls == "binary":
        return [render_text("encrypted/binary payload · %d bytes" % dec.payload_bytes(text), size=15, margin=M)]
    summary = str(m.get("summary") or "").strip()
    if summary and _differs(summary, text):
        return [render_text(_clean(summary), size=15, mono=True, margin=M)]
    return [render_text(_clean(text or "(no text)"), size=15, mono=True, margin=M)]


def render(item: Dict[str, Any], params: dict, ctx) -> Image.Image:
    tz = ctx.setting("timezone")
    msgs = item["messages"]
    first = msgs[0]
    reg = first.get("registration")
    call = str(first.get("callsign") or reg or first.get("icao") or "UNKNOWN")
    link = "VDL2" if first.get("link") == "vdl2" else "ACARS"
    cf = _fit(call, "sans", 36, True, WIDTH - 2 * M, 20)
    head = blank(sum(cf.getmetrics()) + 4)
    d = ImageDraw.Draw(head)
    d.text((M, cf.getmetrics()[0]), call, font=cf, fill=0, anchor="ls")
    d.text((WIDTH - M, cf.getmetrics()[0]), link, font=font("sans", 13, True), fill=0, anchor="rs")
    parts = [head]
    sub = "  ·  ".join(x for x in (reg if reg != call else None,
                                 ad.local_dt(first["ts"], tz).strftime("%d %b %H:%M:%S") if first.get("ts") else None) if x)
    if sub:
        parts.append(render_text(sub, size=17, margin=M))
    home = None
    if ctx.setting("home_lat") is not None and ctx.setting("home_lon") is not None:
        home = (float(ctx.setting("home_lat")), float(ctx.setting("home_lon")))
    used = sum(p.height for p in parts)
    for i, m in enumerate(msgs):
        block = [rule("dashed")]
        label = "·".join(x for x in (m.get("label"), m.get("sublabel")) if x) or "--"
        meta = [label]
        if m.get("freq_mhz") is not None:
            meta.append("%.3f MHz" % m["freq_mhz"])
        if i and m.get("ts"):
            meta.append(ad.local_dt(m["ts"], tz).strftime("%H:%M:%S"))
        block.append(render_text("  ".join(meta), size=16, bold=True, margin=M))
        block += _body(m, m.get("ts"), home)
        h = sum(b.height + 3 for b in block)
        if i and used + h > MAX_HEIGHT:
            parts.append(render_text("+%d more message%s" % (len(msgs) - i, "" if len(msgs) - i == 1 else "s"),
                                     size=14, margin=M))
            break
        parts += block
        used += h
    img = pad(stack(*parts, gap=3), 4, 8)
    return img if img.height <= MAX_HEIGHT + 40 else img.crop((0, 0, img.width, MAX_HEIGHT + 40))
