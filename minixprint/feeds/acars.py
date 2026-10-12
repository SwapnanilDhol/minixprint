"""ACARS feed: prints a ticket for each new decoded message from the aviation bot."""
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from ..jobs import _aviation_data as ad
from ..jobs.aviation import M, _fit
from ..render import WIDTH, font, pad, render_text, rule, stack
from ..render.compose import blank

KIND = "acars"
DESCRIPTION = "Print a ticket for every new ACARS message the receiver decodes"
SOURCES = ["bot", "acarshub"]
PARAMS = {
    "source": {"type": "enum", "options": SOURCES, "default": "bot", "label": "Source"},
    "skip_labels": {"type": "list", "default": ["Q0", "_d", "Q1"], "label": "Skip labels"},
    "min_text_len": {"type": "int", "default": 1, "label": "Min text length"},
}
DEFAULT_INTERVAL_S = 15
FIRST_POLL_CAP = 3     # a brand-new feed prints at most this many (newest) messages
MAX_PER_POLL = 20      # burst guard
FETCH_LIMIT = 100
COLLAPSE_S = 20        # same flight within this many seconds -> one ticket
MAX_TEXT = 700
ACARSHUB_URL = "http://127.0.0.1:8081"


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


def poll(params: dict, cursor: Optional[int], ctx) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    base = _base(params, ctx)
    if not base:
        raise RuntimeError("no ACARS source URL configured (aviation_bot_url)")
    data = ad.get_json(ctx, base + "/api/messages", {"limit": FETCH_LIMIT})
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise RuntimeError("ACARS source %s unreachable or returned no message list" % base)
    msgs = sorted((m for m in data["items"] if isinstance(m, dict) and isinstance(m.get("id"), int)),
                  key=lambda m: m["id"])
    new_cursor = max([m["id"] for m in msgs] + ([cursor] if cursor is not None else [])) if msgs else cursor
    if cursor is not None:
        msgs = [m for m in msgs if m["id"] > cursor]
    skip = {s.lower() for s in params.get("skip_labels") or []}
    min_len = int(params.get("min_text_len") or 0)
    msgs = [m for m in msgs
            if str(m.get("label") or "").lower() not in skip and len(m.get("text") or "") >= min_len]
    msgs = msgs[-(FIRST_POLL_CAP if cursor is None else MAX_PER_POLL):]
    return collapse(msgs), new_cursor


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + " ..."


def render(item: Dict[str, Any], params: dict, ctx) -> Image.Image:
    tz = ctx.setting("timezone")
    msgs = item["messages"]
    first = msgs[0]
    reg = first.get("registration")
    call = str(first.get("callsign") or reg or first.get("icao") or "UNKNOWN")
    cf = _fit(call, "sans", 36, True, WIDTH - 2 * M, 20)
    head = blank(sum(cf.getmetrics()) + 4)
    d = ImageDraw.Draw(head)
    d.text((M, cf.getmetrics()[0]), call, font=cf, fill=0, anchor="ls")
    d.text((WIDTH - M, cf.getmetrics()[0]), "ACARS", font=font("sans", 13, True), fill=0, anchor="rs")
    parts = [head]
    sub = "  ·  ".join(x for x in (reg if reg != call else None,
                                 ad.local_dt(first["ts"], tz).strftime("%d %b %H:%M:%S") if first.get("ts") else None) if x)
    if sub:
        parts.append(render_text(sub, size=17, margin=M))
    for i, m in enumerate(msgs):
        parts.append(rule("dashed"))
        label = "·".join(x for x in (m.get("label"), m.get("sublabel")) if x) or "--"
        meta = [label]
        if m.get("freq_mhz") is not None:
            meta.append("%.3f MHz" % m["freq_mhz"])
        if i and m.get("ts"):
            meta.append(ad.local_dt(m["ts"], tz).strftime("%H:%M:%S"))
        parts.append(render_text("  ".join(meta), size=16, bold=True, margin=M))
        parts.append(render_text(_clean(m.get("text") or "(no text)"), size=15, mono=True, margin=M))
    return pad(stack(*parts, gap=3), 4, 8)
