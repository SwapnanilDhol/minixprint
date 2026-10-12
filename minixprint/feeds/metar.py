"""METAR feed: prints a compact strip whenever the station issues a new observation."""
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from ..jobs import _aviation_data as ad
from ..jobs.aviation import M, _badge
from ..render import pad, render_text, rule, stack

KIND = "metar"
DESCRIPTION = "Print a METAR strip when a station issues a new observation"
PARAMS = {"station": {"type": "icao", "required": True, "label": "Station (ICAO)"}}
DEFAULT_INTERVAL_S = 300


def poll(params: dict, cursor: Optional[str], ctx) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    station = params["station"]
    m = ad.fetch_metar(ctx, station)
    if not m or not m.get("raw"):
        raise RuntimeError("METAR fetch failed for %s" % station)
    if m["raw"] == cursor:
        return [], cursor
    m["station"] = m.get("station") or station
    m["key"] = str(int(m["obs_time"])) if m.get("obs_time") else hashlib.sha1(m["raw"].encode()).hexdigest()[:10]
    m["ts"] = m.get("obs_time")
    return [m], m["raw"]


def render(item: Dict[str, Any], params: dict, ctx) -> Image.Image:
    m = item
    when = ad.local_dt(m["obs_time"], ctx.setting("timezone")).strftime("%d %b %H:%M") if m.get("obs_time") else ""
    head = m.get("station") or params["station"]
    parts = [render_text(head, size=34, bold=True, margin=M)]
    if when:
        parts.append(render_text("obs " + when, size=14, margin=M))
    if m.get("category"):
        parts.append(_badge(m["category"], 24, full=False))
    vis = m.get("vis_sm")
    vis_txt = "--" if vis is None else ("%.0f SM" % vis if vis >= 10 else "%.1f SM" % vis)
    temp = "--" if m.get("temp") is None else "%d" % round(m["temp"])
    dew = "--" if m.get("dewp") is None else "%d" % round(m["dewp"])
    lines = ["Wind  " + ad.fmt_wind(m), "Vis   " + vis_txt]
    if m.get("wx"):
        lines.append("Wx    " + str(m["wx"]))
    lines += ["Cloud " + ad.fmt_clouds(m), "Temp  %s/%s C" % (temp, dew),
              "QNH   " + ("--" if m.get("qnh") is None else "%d hPa" % round(m["qnh"]))]
    parts += [render_text("\n".join(lines), size=22, mono=True, margin=M), rule("dashed"),
              render_text(m["raw"], size=15, mono=True, margin=M)]
    return pad(stack(*parts, gap=3), 4, 8)
