"""Fetching, parsing and geometry for the aviation jobs.

Nothing here draws. Every network call goes through ``ctx.http`` with a short timeout
and every fetcher returns ``None`` / ``[]`` on failure instead of raising, so the jobs
can always render *something* offline. Underscore-prefixed module: ``discover()`` imports
it but it exports no ``JOBS``.
"""
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

TIMEOUT = 5  # seconds, per request
AWC_URL = "https://aviationweather.gov/api/data"
STALE_METAR_S = 3 * 3600

COMPASS16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

KM_PER_NM = 1.852


# --- geometry ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (mean Earth radius 6371 km)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial true bearing from point 1 to point 2, 0 <= b < 360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def compass16(deg: float) -> str:
    """16-point compass name for a bearing (N, NNE, ... NNW)."""
    return COMPASS16[int(((deg % 360) + 11.25) // 22.5) % 16]


# --- small coercions --------------------------------------------------------------------

def num(v: Any) -> Optional[float]:
    """float(v) or None; tolerates strings, "ground" and junk."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def fmt_alt(alt: Any) -> str:
    """'FL360' at/above 18000 ft, plain feet below, 'GND' on the ground, '--' unknown."""
    if isinstance(alt, str) and alt.strip().lower() == "ground":
        return "GND"
    f = num(alt)
    if f is None:
        return "--"
    if f >= 18000:
        return "FL%03d" % round(f / 100.0)
    return "%d" % round(f)


def local_dt(ts: float, tz_name: Optional[str]) -> datetime:
    try:
        from zoneinfo import ZoneInfo  # py3.9+
        return datetime.fromtimestamp(ts, ZoneInfo(tz_name or "UTC"))
    except Exception:  # missing tzdata / bad name: fall back to UTC
        return datetime.fromtimestamp(ts, timezone.utc)


# --- HTTP -------------------------------------------------------------------------------

def get_json(ctx, url: str, params: Optional[dict] = None) -> Optional[Any]:
    """GET + parse JSON through ctx.http; None on any failure."""
    if ctx.http is None:
        return None
    try:
        r = ctx.http.get(url, params=params, timeout=TIMEOUT)
        if getattr(r, "status_code", 200) >= 400:
            return None
        return r.json()
    except Exception:
        return None


def bot_get(ctx, path: str, params: Optional[dict] = None) -> Optional[Any]:
    base = str(ctx.setting("aviation_bot_url", "") or "").rstrip("/")
    if not base:
        return None
    data = get_json(ctx, base + path, params)
    if isinstance(data, dict) and data.get("ok") is False:
        return None
    return data


# --- aircraft ---------------------------------------------------------------------------

def norm_aircraft(a: dict) -> Dict[str, Any]:
    """Normalize a dump1090 aircraft entry *or* a bot contact into one flat shape.

    The bot's field names aren't pinned down in docs/AVIATION.md, so several aliases are
    accepted for each field.
    """
    def pick(*keys):
        for k in keys:
            v = a.get(k)
            if v not in (None, ""):
                return v
        return None

    flight = pick("flight", "callsign")
    reg = pick("registration", "reg", "r")
    typ = pick("type_code", "type", "t")
    return {
        "hex": str(pick("hex", "icao", "icao24") or "").lower(),
        "flight": str(flight).strip() if flight else None,
        "registration": str(reg).strip() if reg else None,
        "type": str(typ).strip() if typ else None,
        "type_name": pick("type_name", "desc", "model"),
        "origin": pick("origin", "origin_iata"),
        "dest": pick("dest", "destination", "dest_iata"),
        "origin_city": pick("origin_city"),
        "dest_city": pick("dest_city", "destination_city"),
        "alt_baro": pick("alt_baro", "alt", "altitude"),
        "gs": num(pick("gs", "speed")),
        "track": num(pick("track", "heading")),
        "lat": num(a.get("lat")),
        "lon": num(a.get("lon")),
        "squawk": pick("squawk"),
        "rssi": num(a.get("rssi")),
        "is_military": bool(a.get("is_military") or a.get("military")),
        "reasons": list(a.get("reasons") or []),
        "distance_km": num(pick("distance_km", "dist_km")),
        "seen_pos": num(a.get("seen_pos")),
    }


def home(ctx) -> Tuple[float, float]:
    return (float(ctx.setting("home_lat", 12.9941)), float(ctx.setting("home_lon", 80.1709)))


def add_geometry(c: dict, hlat: float, hlon: float) -> dict:
    """Fill c['dist_km'] and c['bearing'] (None when no position)."""
    if c.get("lat") is not None and c.get("lon") is not None:
        c["dist_km"] = haversine_km(hlat, hlon, c["lat"], c["lon"])
        c["bearing"] = bearing_deg(hlat, hlon, c["lat"], c["lon"])
    else:
        c["dist_km"] = c.get("distance_km")
        c["bearing"] = None
    return c


def read_aircraft_json(ctx) -> Optional[dict]:
    """Raw dump1090 JSON. The setting may be a file path (on the Pi) or an http(s) URL."""
    src = ctx.setting("aircraft_json")
    if not src:
        return None
    src = str(src)
    if src.startswith(("http://", "https://")):
        data = get_json(ctx, src)
    else:
        try:
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
    return data if isinstance(data, dict) else None


def bot_aircraft(ctx) -> List[dict]:
    data = bot_get(ctx, "/api/aircraft")
    items = data.get("aircraft") if isinstance(data, dict) else None
    return [norm_aircraft(x) for x in items or [] if isinstance(x, dict)]


def load_aircraft(ctx) -> Dict[str, Any]:
    """Current traffic, enriched and sorted by distance (unpositioned last).

    Returns {"aircraft": [...], "messages": int|None, "now": float|None, "source": str}.
    aircraft.json is primary; the bot's /api/aircraft fills in registration / type /
    route by hex, and is the fallback when the file is unreadable.
    """
    raw = read_aircraft_json(ctx)
    hlat, hlon = home(ctx)
    enrich = {c["hex"]: c for c in bot_aircraft(ctx) if c["hex"]}
    if raw is not None:
        ac = [norm_aircraft(x) for x in raw.get("aircraft") or [] if isinstance(x, dict)]
        source = "aircraft.json"
    else:
        ac, source = list(enrich.values()), ("bot" if enrich else "none")
    for c in ac:
        e = enrich.get(c["hex"])
        if e:
            for k in ("registration", "type", "type_name", "origin", "dest",
                      "origin_city", "dest_city", "flight"):
                if not c.get(k) and e.get(k):
                    c[k] = e[k]
        add_geometry(c, hlat, hlon)
    ac.sort(key=lambda c: (c["dist_km"] is None, c["dist_km"] or 0.0))
    return {
        "aircraft": ac,
        "messages": (raw or {}).get("messages"),
        "now": num((raw or {}).get("now")),
        "source": source,
    }


_rate_cache: Dict[str, Tuple[float, float]] = {}


def message_rate(data: Dict[str, Any]) -> Optional[float]:
    """Messages/s. aircraft.json only has a running total, so the rate is the delta
    against the previous reading this process saw (None on the first call or after a
    restart of dump1090)."""
    msgs, now = num(data.get("messages")), data.get("now")
    if msgs is None or now is None:
        return None
    prev = _rate_cache.get("last")
    _rate_cache["last"] = (msgs, now)
    if prev and now > prev[1] and msgs >= prev[0] and now - prev[1] < 600:
        return (msgs - prev[0]) / (now - prev[1])
    return None


# --- weather ----------------------------------------------------------------------------

def flight_category(vis_sm: Optional[float], ceiling_ft: Optional[float]) -> str:
    """US FAA flight category from visibility (statute miles) and ceiling (ft AGL).

        LIFR  vis < 1 SM      or ceiling < 500 ft
        IFR   1 <= vis < 3    or 500 <= ceiling < 1000
        MVFR  3 <= vis <= 5   or 1000 <= ceiling <= 3000
        VFR   vis > 5 and ceiling > 3000 (or no ceiling)

    The worse of the two wins; an unknown visibility is ignored, and with both unknown
    the result is "" (no badge).
    """
    if vis_sm is None and ceiling_ft is None:
        return ""
    rank = 0
    if vis_sm is not None:
        rank = max(rank, 3 if vis_sm < 1 else 2 if vis_sm < 3 else 1 if vis_sm <= 5 else 0)
    if ceiling_ft is not None:
        rank = max(rank, 3 if ceiling_ft < 500 else 2 if ceiling_ft < 1000
                   else 1 if ceiling_ft <= 3000 else 0)
    return ("VFR", "MVFR", "IFR", "LIFR")[rank]


def ceiling_ft(clouds: Any) -> Optional[float]:
    """Lowest BKN / OVC / VV layer base (ft), None when there is no ceiling."""
    best = None
    for layer in clouds or []:
        if not isinstance(layer, dict):
            continue
        if str(layer.get("cover", "")).upper() in ("BKN", "OVC", "OVX", "VV"):
            base = num(layer.get("base"))
            if base is not None and (best is None or base < best):
                best = base
    return best


def _vis_sm(v: Any) -> Optional[float]:
    if isinstance(v, str):
        v = v.replace("+", "")
    return num(v)


def parse_metar(d: dict) -> Dict[str, Any]:
    """Normalise an aviationweather.gov metar object or the bot's /api/metar record."""
    src = d.get("source_data") if isinstance(d.get("source_data"), dict) else {}
    g = lambda *ks: next((x for x in (d.get(k, src.get(k)) for k in ks) if x is not None), None)  # noqa: E731
    clouds = g("clouds") or []
    vis = _vis_sm(g("visib"))
    if vis is None and num(d.get("visibility_m")) is not None:
        vis = num(d.get("visibility_m")) / 1609.344
    wdir = g("wdir", "wind_direction_deg_true")
    qnh = num(g("altim", "pressure_hpa"))
    if qnh is not None and qnh < 100:  # some feeds give inHg
        qnh = qnh * 33.8639
    obs = num(g("obsTime", "observed_at"))
    ceil = ceiling_ft(clouds) if clouds else num(d.get("ceiling_ft"))
    cat = g("fltCat", "flight_category") or flight_category(vis, ceil)
    return {
        "station": g("icaoId", "station"),
        "name": g("name"),
        "raw": g("rawOb", "raw_text", "raw"),
        "obs_time": obs,
        "wdir": wdir,
        "wspd": num(g("wspd", "wind_speed_kt")),
        "wgst": num(g("wgst", "wind_gust_kt")),
        "vis_sm": vis,
        "clouds": clouds,
        "ceiling_ft": ceil,
        "temp": num(g("temp", "temperature_c")),
        "dewp": num(g("dewp", "dewpoint_c")),
        "qnh": qnh,
        "wx": g("wxString", "present_weather"),
        "category": str(cat).upper() if cat else flight_category(vis, ceil),
    }


def fetch_metar(ctx, station: str) -> Optional[Dict[str, Any]]:
    """Latest METAR for a station: aviationweather.gov first, then the bot's cache."""
    data = get_json(ctx, AWC_URL + "/metar", {"ids": station, "format": "json"})
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return parse_metar(data[0])
    data = bot_get(ctx, "/api/metar", {"station": station})
    if isinstance(data, dict):
        rec = data.get("metar") if isinstance(data.get("metar"), dict) else data
        if rec.get("raw_text") or rec.get("rawOb") or rec.get("raw"):
            return parse_metar(rec)
    return None


def fetch_taf(ctx, station: str) -> Optional[str]:
    data = get_json(ctx, AWC_URL + "/taf", {"ids": station, "format": "json"})
    if isinstance(data, list) and data and isinstance(data[0], dict):
        raw = data[0].get("rawTAF")
        return str(raw) if raw else None
    return None


def fmt_wind(m: Dict[str, Any]) -> str:
    """'250° 12G18 kt', 'VRB 03 kt' or 'calm'."""
    spd = m.get("wspd")
    if spd is None:
        return "--"
    if spd == 0:
        return "calm"
    d = m.get("wdir")
    dnum = num(d)
    dtxt = "VRB" if dnum is None and d else ("%03d°" % round(dnum) if dnum is not None else "---")
    gust = m.get("wgst")
    return "%s %02d%s kt" % (dtxt, spd, "G%02d" % gust if gust else "")


def fmt_clouds(m: Dict[str, Any]) -> str:
    layers = [c for c in m.get("clouds") or [] if isinstance(c, dict)]
    if not layers:
        return "CLR"
    out = []
    for lay in layers:
        base = num(lay.get("base"))
        out.append("%s %s" % (lay.get("cover", "?"), "%d" % base if base is not None else "---"))
    return ", ".join(out)


# --- runway -----------------------------------------------------------------------------

def runway_heading(rwy: str) -> Optional[float]:
    """'25' -> 250, '07L' -> 70 (magnetic heading approximated by the number x 10)."""
    mm = re.match(r"\s*(\d{1,2})", str(rwy or ""))
    return float(int(mm.group(1)) * 10 % 360 or 360) if mm else None


def runway_state(ctx, now: float) -> Optional[Dict[str, Any]]:
    """Active runway from the bot.

    Uses /api/runways/summary over the last 36 h (its timeline lists runway intervals)
    and falls back to /api/state's ``runway`` block. Returns
    {"runway", "since", "switches_today", "live"} or None when the bot is unreachable.
    """
    airport = str(ctx.setting("home_airport", "VOMM"))
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    start = datetime.fromtimestamp(now - 36 * 3600, timezone.utc).strftime(fmt)
    end = datetime.fromtimestamp(now, timezone.utc).strftime(fmt)
    summ = bot_get(ctx, "/api/runways/summary",
                   {"airport": airport, "start": start, "end": end, "grouping": "day"})
    tl = [t for t in (summ or {}).get("timeline") or [] if isinstance(t, dict) and t.get("runway")]
    if tl:
        tl.sort(key=lambda t: num(t.get("start_at")) or 0)
        # merge consecutive intervals on the same runway into one stretch
        stretches: List[Dict[str, Any]] = []
        for t in tl:
            if stretches and stretches[-1]["runway"] == t["runway"]:
                stretches[-1]["end"] = num(t.get("end_at")) or stretches[-1]["end"]
            else:
                stretches.append({"runway": t["runway"], "start": num(t.get("start_at")),
                                  "end": num(t.get("end_at"))})
        cur = stretches[-1]
        midnight = local_dt(now, ctx.setting("timezone")).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        today = [s for s in stretches if (s["start"] or 0) >= midnight]
        switches = len(today) - 1 if (stretches[0]["start"] or 0) >= midnight else len(today)
        return {"runway": str(cur["runway"]), "since": cur["start"],
                "switches_today": max(0, switches),
                "live": cur["end"] is None or now - cur["end"] < 600}
    state = bot_get(ctx, "/api/state")
    rw = (state or {}).get("runway") if isinstance(state, dict) else None
    if isinstance(rw, dict):
        cur = rw.get("runway")
        if cur:
            return {"runway": str(cur), "since": None, "switches_today": None, "live": True}
        if rw.get("last_confirmed_runway"):
            return {"runway": str(rw["last_confirmed_runway"]), "since": None,
                    "switches_today": None, "live": False}
    return None
