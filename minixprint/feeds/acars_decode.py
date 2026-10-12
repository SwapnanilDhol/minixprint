"""ACARS helpers: message classifier and a text rendering of acarsdec's ``libacars`` JSON.

libacars has no Python binding, so everything here works on the JSON that acarsdec and
dumpvdl2 emit (``la_proto_tree_format_json``): a nest of protocol nodes such as
``{"arinc622": {"msg_type": "adsc_msg", ..., "adsc": {"tags": [...], "err": false}}}``,
``{"miam": {...}}`` or ``{"media-adv": {...}}``. ``describe()`` turns that into
``[(style, text)]`` lines, ``style`` being ``"b"`` (bold), ``"m"`` (mono) or ``"t"`` (plain).
"""
import base64
import binascii
import re
from typing import Any, List, Optional, Tuple

from ..jobs import _aviation_data as ad

Line = Tuple[str, str]

BINARY_MIN_LEN = 40
BINARY_B64_FRACTION = 0.95
READABLE_PUNCT_FRACTION = 0.25
MAX_DUMP_LINES = 20
_B64 = re.compile(r"[A-Za-z0-9+/=]")
_PUNCT = set("/.-,")
_NON_PRINT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f�]")


# --- classifier ----------------------------------------------------------------------------

def classify(text: Optional[str], decoded: bool = False) -> str:
    """``"decoded"`` (libacars/decoded text exists), ``"readable"`` or ``"binary"``.

    Binary: an unbroken run of >= 40 base64-alphabet characters (>= 95 %, no whitespace) —
    encrypted airline payloads — or text that is mostly control/garbage characters.
    Readable: anything with whitespace, or >= 25 % ACARS punctuation (``/ . - ,``), or
    simply too short to be a blob (e.g. ``POS N12.93E080.10,FL350``).
    """
    if decoded:
        return "decoded"
    t = (text or "").strip()
    if not t:
        return "readable"
    if len(_NON_PRINT.findall(t)) / len(t) > 0.1:
        return "binary"
    if any(c.isspace() for c in t):
        return "readable"
    if sum(c in _PUNCT for c in t) / len(t) >= READABLE_PUNCT_FRACTION:
        return "readable"
    if len(t) >= BINARY_MIN_LEN and len(_B64.findall(t)) / len(t) >= BINARY_B64_FRACTION:
        return "binary"
    return "readable"


def payload_bytes(text: str) -> int:
    """Size of a binary payload: the base64-decoded length when it decodes, else its characters."""
    t = "".join((text or "").split())
    try:
        return len(base64.b64decode(t + "=" * (-len(t) % 4), validate=True))
    except (binascii.Error, ValueError):
        return len(t)


# --- libacars JSON -> lines -----------------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    return ad.num(v) if not isinstance(v, bool) else None


def _hemi(v: float, pos: str, neg: str, width: int) -> str:
    return "%s%0*.3f" % (pos if v >= 0 else neg, width, abs(v))


def fmt_latlon(lat: float, lon: float) -> str:
    return "%s %s" % (_hemi(lat, "N", "S", 6), _hemi(lon, "E", "W", 7))


def fmt_alt(ft: float) -> str:
    return ("FL%03d" % round(ft / 100.0) if ft >= 4000 else "%d ft" % round(ft)) + (
        " (%d ft)" % round(ft) if ft >= 4000 else "")


def fmt_eta(sec: Any) -> str:
    s = _num(sec)
    return "" if s is None else " eta %02d:%02d" % (int(s) // 3600 % 24, int(s) // 60 % 60)


def _from_home(lat: float, lon: float, home: Optional[Tuple[float, float]]) -> Optional[str]:
    if not home:
        return None
    km = ad.haversine_km(home[0], home[1], lat, lon)
    brg = ad.bearing_deg(home[0], home[1], lat, lon)
    return "%.0f km / %.0f nm %s (%03.0f°) from home" % (km, km / ad.KM_PER_NM, ad.compass16(brg), brg)


def _hms(ts: Optional[float], sec: Any) -> Optional[str]:
    """ADS-C timestamps are seconds since the top of the hour; anchor them to the message time."""
    s = _num(sec)
    if s is None:
        return None
    if ts:
        base = ts - ts % 3600 + s
        if base > ts + 1800:
            base -= 3600
        elif base < ts - 1800:
            base += 3600
        s = base % 86400
    return "%02d:%02d:%02d UTC" % (int(s) // 3600 % 24, int(s) // 60 % 60, int(s) % 60)


def _find(node: Any, key: str) -> Optional[Any]:
    """First value stored under ``key`` anywhere in a nest of dicts/lists."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            r = _find(v, key)
            if r is not None:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return ("%.3f" % v).rstrip("0").rstrip(".")
    return str(v)


def _compact(v: Any) -> str:
    """One-line rendering of a value: units, lat/lon, lists collapsed."""
    if isinstance(v, dict):
        if "val" in v and "unit" in v:
            return "%s %s" % (_scalar(v["val"]), v["unit"])
        if "deg" in v and "dir" in v:
            return "%s%s°%s" % (v["dir"], v["deg"], "" if v.get("min") is None else " %s'" % _scalar(v["min"]))
        if "hour" in v and "min" in v:
            return "%02d:%02d%s" % (v["hour"], v["min"], "" if "sec" not in v else ":%02d" % v["sec"])
        if "value_descr" in v:
            return str(v["value_descr"])
        if "choice" in v and isinstance(v.get("data"), dict) and len(v) <= 3:
            return "%s %s" % (v.get("choice_label") or v["choice"], _compact(v["data"]))
        return " ".join(("%s=%s" % (k, _compact(x))) for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_compact(x) for x in v)
    return _scalar(v)


def _tag(tags: List[Any], name: str) -> Optional[dict]:
    for t in tags:
        if isinstance(t, dict) and isinstance(t.get(name), dict):
            return t[name]
    return None


def _adsc(adsc: dict, ts: Optional[float], home) -> List[Line]:
    tags = [t for t in adsc.get("tags") or [] if isinstance(t, dict)]
    out = [("b", "ADS-C report")]
    if adsc.get("err"):
        out.append(("t", "(message had decode errors)"))
    br = _tag(tags, "basic_report") or _tag(tags, "emerg_basic_report")
    if br:
        lat, lon, alt = _num(br.get("lat")), _num(br.get("lon")), _num(br.get("alt"))
        if lat is not None and lon is not None:
            out.append(("m", "Pos  " + fmt_latlon(lat, lon)))
            far = _from_home(lat, lon, home)
            if far:
                out.append(("t", far))
        if alt is not None:
            out.append(("m", "Alt  " + fmt_alt(alt)))
        when = _hms(ts, br.get("ts_sec"))
        if when:
            out.append(("m", "Time " + when))
    er = _tag(tags, "earth_ref_data")
    if er:
        bits = []
        if _num(er.get("gnd_spd_kts")) is not None:
            bits.append("GS %.0f kt" % _num(er["gnd_spd_kts"]))
        if _num(er.get("true_trk_deg")) is not None and er.get("true_trk_valid", True):
            bits.append("TRK %03.0f°" % _num(er["true_trk_deg"]))
        if _num(er.get("vspd_ftmin")) is not None:
            bits.append("VS %+.0f fpm" % _num(er["vspd_ftmin"]))
        if bits:
            out.append(("m", "  ".join(bits)))
    ar = _tag(tags, "air_ref_data")
    if ar:
        bits = []
        if _num(ar.get("spd_mach")) is not None:
            bits.append("M%.3f" % _num(ar["spd_mach"]))
        if _num(ar.get("true_hdg_deg")) is not None and ar.get("true_hdg_valid", True):
            bits.append("HDG %03.0f°" % _num(ar["true_hdg_deg"]))
        if bits:
            out.append(("m", "  ".join(bits)))
    me = _tag(tags, "meteo_data")
    if me:
        bits = []
        if _num(me.get("wind_spd_kts")) is not None:
            wd = _num(me.get("wind_dir_true_deg"))
            bits.append("Wind %s%.0f kt" % ("%03.0f°/" % wd if wd is not None and me.get("wind_dir_valid", True) else "", me["wind_spd_kts"]))
        if _num(me.get("temp_c")) is not None:
            bits.append("%.1f C" % _num(me["temp_c"]))
        if bits:
            out.append(("m", "  ".join(bits)))
    fid = _tag(tags, "flight_id")
    if fid and fid.get("flight_id"):
        out.append(("m", "Flight " + str(fid["flight_id"]).strip()))
    pr = _tag(tags, "predicted_route")
    if pr:
        for label, key in (("Next ", "next_wpt"), ("Then ", "next_next_wpt")):
            w = pr.get(key)
            if isinstance(w, dict) and _num(w.get("lat")) is not None and _num(w.get("lon")) is not None:
                alt = _num(w.get("alt"))
                out.append(("m", "%s%s%s%s" % (label, fmt_latlon(w["lat"], w["lon"]),
                                              "" if alt is None else " " + fmt_alt(alt), fmt_eta(w.get("eta_sec")))))
    for t in tags:
        for name in ("intermediate_projection", "fixed_projection"):
            p = t.get(name)
            if isinstance(p, dict):
                if _num(p.get("lat")) is not None and _num(p.get("lon")) is not None:
                    where = fmt_latlon(p["lat"], p["lon"])
                else:
                    where = "%.0f nm" % (_num(p.get("dist_nm")) or 0) + (
                        " TRK %03.0f°" % _num(p["true_trk_deg"]) if _num(p.get("true_trk_deg")) is not None else "")
                alt = _num(p.get("alt"))
                out.append(("m", "Proj %s%s%s" % (where, "" if alt is None else " " + fmt_alt(alt), fmt_eta(p.get("eta_sec")))))
    known = {"basic_report", "emerg_basic_report", "earth_ref_data", "air_ref_data", "meteo_data",
             "flight_id", "predicted_route", "intermediate_projection", "fixed_projection"}
    for t in tags:
        for name, body in t.items():
            if name not in known:
                out.append(("m", "%s: %s" % (name, _compact(body))))
    return out


def _walk_choices(node: Any, acc: List[str]) -> None:
    """Collect CPDLC message elements: dicts carrying a ``choice_label`` plus their ``data``."""
    if isinstance(node, dict):
        label = node.get("choice_label")
        if label:
            data = node.get("data")
            extra = ""
            if isinstance(data, dict) and data:
                parts = [_compact(v) for v in data.values() if not (isinstance(v, dict) and "choice_label" in v)]
                extra = " " + "; ".join(p for p in parts if p) if parts else ""
            acc.append(str(label).strip() + extra)
        for v in node.values():
            _walk_choices(v, acc)
    elif isinstance(node, list):
        for v in node:
            _walk_choices(v, acc)


def _cpdlc(cpdlc: dict, msg_type: str) -> List[Line]:
    if cpdlc.get("err"):
        return [("b", "CPDLC"), ("t", "(could not be decoded)")]
    keys = " ".join(k for k in _keys(cpdlc))
    direction = "uplink" if "uplink" in keys else "downlink" if "downlink" in keys else ""
    system = "FANS-1/A" if "fans1a" in msg_type or "atc_" in keys else "ATN" if "atn" in msg_type else ""
    out = [("b", " ".join(x for x in ("CPDLC", direction, "·" if system else "", system) if x))]
    els = []  # type: List[str]
    _walk_choices(cpdlc, els)
    for e in els:
        out.append(("t", "• " + e))
    mid = _find(cpdlc, "msg_id")
    if mid is not None:
        out.append(("m", "msg id %s" % _scalar(mid)))
    if not els:
        out.extend(_dump({k: v for k, v in cpdlc.items() if k != "err"}))
    return out


def _keys(node: Any):
    if isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def _miam(miam: dict) -> List[Line]:
    out = [("b", "MIAM")]
    text = _find(miam, "text")
    if isinstance(text, str) and text.strip():
        label = _find(miam, "label")
        if label:
            out.append(("m", "inner label %s%s" % (label, "" if not _find(miam, "sublabel") else "·" + str(_find(miam, "sublabel")))))
        out.append(("m", text.strip()))
        return out
    octets = _find(miam, "octet_string")
    comp = _find(miam, "compression")
    if octets is not None:
        n = len(octets.replace(" ", "")) // 2 if isinstance(octets, str) else len(octets) if hasattr(octets, "__len__") else 0
        out.append(("t", "compressed MIAM, %d bytes" % n))
        return out
    if comp is not None:
        out.append(("t", "compressed MIAM"))
    out.extend(_dump(miam))
    return out


def _media_adv(m: dict) -> List[Line]:
    cur = m.get("current_link") or {}
    out = [("b", "Media advisory")]
    if cur:
        t = cur.get("time") or {}
        out.append(("m", "%s %s%s" % (cur.get("descr") or cur.get("code"),
                                       "established" if cur.get("established") else "lost",
                                       " at %02d:%02d:%02d UTC" % (t.get("hour", 0), t.get("min", 0), t.get("sec", 0)) if t else "")))
    avail = [str(x.get("descr") or x.get("code")) for x in m.get("links_avail") or [] if isinstance(x, dict)]
    if avail:
        out.append(("m", "Available: " + ", ".join(avail)))
    return out


def _dump(node: Any, prefix: str = "") -> List[Line]:
    """Compact key: value dump for structures we have no dedicated renderer for."""
    out = []  # type: List[Line]

    def rec(n: Any, path: str) -> None:
        if len(out) >= MAX_DUMP_LINES:
            return
        if isinstance(n, dict) and not ("val" in n and "unit" in n):
            for k, v in n.items():
                rec(v, "%s.%s" % (path, k) if path else str(k))
        elif isinstance(n, list) and any(isinstance(x, (dict, list)) for x in n):
            for i, v in enumerate(n):
                rec(v, "%s[%d]" % (path, i))
        else:
            out.append(("m", "%s: %s" % (path, _compact(n))))

    rec(node, prefix)
    if len(out) >= MAX_DUMP_LINES:
        out[-1] = ("m", "...")
    return out


def describe(libacars: Any, ts: Optional[float] = None,
             home: Optional[Tuple[float, float]] = None) -> List[Line]:
    """Lines for a libacars JSON object; never raises on odd shapes."""
    if not isinstance(libacars, dict) or not libacars:
        return []
    try:
        return _describe(libacars, ts, home)
    except Exception:  # a malformed record must still print something useful
        return _dump(libacars)[:MAX_DUMP_LINES]


def _describe(libacars: dict, ts, home) -> List[Line]:
    out = []  # type: List[Line]
    seen = set()
    arinc = libacars.get("arinc622")
    msg_type = ""
    if isinstance(arinc, dict):
        seen.add("arinc622")
        msg_type = str(arinc.get("msg_type") or "")
        if arinc.get("crc_ok") is False:
            out.append(("t", "(ARINC 622 CRC failed)"))
        if isinstance(arinc.get("adsc"), dict):
            out += _adsc(arinc["adsc"], ts, home)
        elif isinstance(arinc.get("cpdlc"), dict):
            out += _cpdlc(arinc["cpdlc"], msg_type)
        else:
            out.append(("b", "ARINC 622 " + (msg_type.replace("_", " ") or "report")))
            rest = {k: v for k, v in arinc.items() if k not in ("msg_type", "crc_ok")}
            out += _dump(rest)
    if isinstance(libacars.get("adsc"), dict):
        seen.add("adsc")
        out += _adsc(libacars["adsc"], ts, home)
    if isinstance(libacars.get("cpdlc"), dict):
        seen.add("cpdlc")
        out += _cpdlc(libacars["cpdlc"], msg_type)
    if isinstance(libacars.get("miam"), dict):
        seen.add("miam")
        out += _miam(libacars["miam"])
    if isinstance(libacars.get("media-adv"), dict):
        seen.add("media-adv")
        out += _media_adv(libacars["media-adv"])
    rest = {k: v for k, v in libacars.items() if k not in seen}
    if rest:
        out += _dump(rest)
    return out[:MAX_DUMP_LINES + 8]
