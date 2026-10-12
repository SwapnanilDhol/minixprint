"""Aviation jobs: overhead boarding pass, METAR/TAF, runway rose, traffic table, digest.

Data sources and parameters are documented in docs/AVIATION.md ("Jobs").
"""
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw

from ..render import WIDTH, font, pad, render_qr, render_text, rule, stack
from ..render.compose import blank
from . import JobContext
from . import _aviation_data as ad

M = 6  # side margin for hand-drawn blocks


# --- drawing helpers --------------------------------------------------------------------

def _text_w(f, s: str) -> float:
    return f.getlength(s)


def _fit(s: str, kind: str, size: int, bold: bool, max_w: int, min_size: int = 14):
    """Largest font <= size in which s fits max_w."""
    while size > min_size and _text_w(font(kind, size, bold), s) > max_w:
        size -= 1
    return font(kind, size, bold)


def _badge(text: str, size: int = 22, full: bool = True) -> Image.Image:
    """White-on-black label, full paper width (or hugging the text, centred)."""
    f = font("sans", size, True)
    w = int(_text_w(f, text))
    asc, desc = f.getmetrics()
    h = asc + desc + 10
    img = blank(h)
    d = ImageDraw.Draw(img)
    bw = WIDTH - 2 * M if full else min(WIDTH - 2 * M, w + 28)
    x0 = (WIDTH - bw) // 2
    d.rectangle([x0, 0, x0 + bw - 1, h - 1], fill=0)
    d.text((WIDTH / 2, 5 + asc), text, font=f, fill=1, anchor="ms")
    return img


def _kv_columns(cols: List[tuple]) -> Image.Image:
    """Equal-width columns of (label, value): small label above a big value."""
    lf = font("sans", 15, True)
    n = len(cols)
    cw = (WIDTH - 2 * M) // n
    vsize = 30
    vh = sum(font("sans", vsize, True).getmetrics())
    lh = sum(lf.getmetrics())
    img = blank(lh + vh + 4)
    d = ImageDraw.Draw(img)
    for i, (label, value) in enumerate(cols):
        cx = M + cw * i + cw // 2
        d.text((cx, lh - lf.getmetrics()[1]), label, font=lf, fill=0, anchor="ms")
        vf = _fit(value, "sans", vsize, True, cw - 8)
        d.text((cx, lh + 4 + vf.getmetrics()[0]), value, font=vf, fill=0, anchor="ms")
        if i:
            d.line([M + cw * i, 2, M + cw * i, img.height - 2], fill=0, width=1)
    return img


def _clock(ctx: JobContext, ts: Optional[float] = None) -> datetime:
    return ad.local_dt(ts if ts is not None else ctx.now(), ctx.setting("timezone"))


def _no_data(title: str, lines: str) -> Image.Image:
    return stack(render_text(title, size=30, bold=True, align="center"),
                 rule("dashed"),
                 render_text(lines, size=20, align="center"), gap=4)


def _route(origin: str, dest: str) -> Image.Image:
    """'MAA -> DXB' with a hand-drawn arrow (Helvetica has no arrow glyph)."""
    f = font("sans", 36, True)
    asc, desc = f.getmetrics()
    ow, dw = _text_w(f, origin), _text_w(f, dest)
    arrow = 46
    total = ow + dw + arrow + 24
    img = blank(asc + desc + 2)
    d = ImageDraw.Draw(img)
    x = (WIDTH - total) / 2
    d.text((x, asc), origin, font=f, fill=0, anchor="ls")
    x += ow + 12
    y = asc * 0.55
    d.line([x, y, x + arrow, y], fill=0, width=4)
    d.polygon([(x + arrow + 2, y), (x + arrow - 12, y - 9), (x + arrow - 12, y + 9)], fill=0)
    d.text((x + arrow + 12, asc), dest, font=f, fill=0, anchor="ls")
    return img


# --- aviation.overhead ------------------------------------------------------------------

def overhead_job(params: dict, ctx: JobContext) -> Image.Image:
    """Boarding-pass cards for aircraft currently overhead, from the ADS-B receiver."""
    params = params or {}
    hlat, hlon = ad.home(ctx)
    contact = params.get("contact")
    if isinstance(contact, dict) and contact:
        c = ad.norm_aircraft(contact)
    else:
        traffic = ad.load_aircraft(ctx)["aircraft"]
        want = str(params.get("hex") or "").lower()
        if want:
            c = next((a for a in traffic if a["hex"] == want), None)
            if c is None:
                return _no_data("NOT TRACKED", "Aircraft %s is not in the current traffic." % want.upper())
        else:
            positioned = [a for a in traffic if a.get("dist_km") is not None]
            if not positioned:
                return _no_data("NOTHING OVERHEAD",
                                "No aircraft with a position right now.\n"
                                + _clock(ctx).strftime("%d %b %Y  %H:%M"))
            c = positioned[0]
    ad.add_geometry(c, hlat, hlon)

    callsign = c["flight"] or c["registration"] or (c["hex"] or "UNKNOWN").upper()
    parts: List[Optional[Image.Image]] = []

    # reasons badge
    reasons = [str(r).strip().upper() for r in c["reasons"] if str(r).strip()]
    if c["is_military"] and not any("MIL" in r for r in reasons):
        reasons.insert(0, "MILITARY")
    sq = str(c["squawk"] or "")
    if sq in ("7500", "7600", "7700") and not any(sq in r for r in reasons):
        reasons.append("EMERGENCY " + sq)
    if reasons:
        for r in reasons[:3]:
            parts.append(_badge(r, 22))

    # big callsign
    cf = _fit(callsign, "sans", 40, True, WIDTH - 2 * M, 22)
    head = blank(sum(cf.getmetrics()) + 4)
    ImageDraw.Draw(head).text((M, cf.getmetrics()[0]), callsign, font=cf, fill=0, anchor="ls")
    d = ImageDraw.Draw(head)
    tag = "BOARDING PASS"
    tf = font("sans", 13, True)
    d.text((WIDTH - M, cf.getmetrics()[0]), tag, font=tf, fill=0, anchor="rs")
    parts.append(head)

    # reg + type
    regtype = "  ·  ".join(x for x in (c["registration"], c["type_name"] or c["type"]) if x)
    if regtype:
        parts.append(render_text(regtype, size=20, margin=M))

    # route
    if c["origin"] or c["dest"]:
        parts.append(_route(c["origin"] or "???", c["dest"] or "???"))
        cities = " to ".join(x for x in (c["origin_city"], c["dest_city"]) if x)
        if cities:
            parts.append(render_text(cities, size=16, align="center", margin=2))

    parts.append(rule("solid", thickness=1))

    # stats
    alt = ad.fmt_alt(c["alt_baro"])
    gs = "%d" % round(c["gs"]) if c["gs"] is not None else "--"
    trk = "%03d°" % (round(c["track"]) % 360) if c["track"] is not None else "--"
    alt_label = "ALT" if alt.startswith("FL") or alt in ("GND", "--") else "ALT ft"
    parts.append(_kv_columns([(alt_label, alt), ("GS kt", gs), ("TRK", trk)]))

    # distance + bearing
    if c["dist_km"] is not None:
        where = "%.1f km" % c["dist_km"]
        if c["bearing"] is not None:
            where += "  %s (%03d°)" % (ad.compass16(c["bearing"]), round(c["bearing"]) % 360)
        parts.append(render_text(where + " from home", size=20, bold=True, align="center", margin=3))
    now = _clock(ctx)
    parts.append(render_text("%s  ·  %s  ·  hex %s" % (now.strftime("%d %b %H:%M"),
                                                       "SQK " + sq if sq else "SQK ----", c["hex"].upper() or "-"),
                             size=15, align="center", margin=2))

    # tear line + QR
    parts.append(rule("dashed"))
    parts.append(render_text("- - - tear here - - -", size=14, align="center", margin=1))
    if c["hex"]:
        parts.append(render_qr("https://globe.adsbexchange.com/?icao=" + c["hex"],
                               caption="globe.adsbexchange.com", fill=0.5))
    return pad(stack(*parts, gap=4), 4, 8)


# --- aviation.metar ---------------------------------------------------------------------

def _metar_card(ctx: JobContext, station: str) -> Image.Image:
    m = ad.fetch_metar(ctx, station)
    if not m or not m.get("raw"):
        return _no_data(station, "NO DATA\nMETAR unavailable (fetch failed).")
    age = None
    if m["obs_time"]:
        age = ctx.now() - m["obs_time"]
    parts: List[Optional[Image.Image]] = [render_text(station, size=40, bold=True, margin=M)]
    if m.get("name"):
        parts.append(render_text(m["name"], size=15, margin=M))
    if age is not None and age > ad.STALE_METAR_S:
        parts.append(_badge("STALE · %dh OLD" % round(age / 3600), 18))
    if m["category"]:
        parts.append(_badge(m["category"], 28, full=False))

    vis = m["vis_sm"]
    vis_txt = "--" if vis is None else ("%.0f SM" % vis if vis >= 10 else "%.1f SM" % vis)
    if m["vis_sm"] is not None and m["vis_sm"] < 6:
        vis_txt += " (%s km)" % ("%.1f" % (vis * 1.609)).rstrip("0").rstrip(".")
    temp = "--" if m["temp"] is None else "%d°C" % round(m["temp"])
    dew = "--" if m["dewp"] is None else "%d°C" % round(m["dewp"])
    qnh = "--" if m["qnh"] is None else "Q%d" % round(m["qnh"])
    lines = ["Wind  " + ad.fmt_wind(m), "Vis   " + vis_txt]
    if m.get("wx"):
        lines.append("Wx    " + str(m["wx"]))
    lines += ["Cloud " + ad.fmt_clouds(m), "Temp  %s / %s" % (temp, dew), "QNH   " + qnh[1:] + " hPa"]
    parts.append(render_text("\n".join(lines), size=24, mono=True, margin=M))
    if m["obs_time"]:
        parts.append(render_text("obs " + _clock(ctx, m["obs_time"]).strftime("%d %b %H:%M"),
                                 size=14, margin=M))
    parts.append(rule("dashed"))
    parts.append(render_text(m["raw"], size=15, mono=True, margin=M))
    taf = ad.fetch_taf(ctx, station)
    if taf:
        parts.append(render_text("TAF", size=16, bold=True, margin=M))
        parts.append(render_text(taf, size=15, mono=True, margin=M))
    return stack(*parts, gap=4)


def metar_job(params: dict, ctx: JobContext) -> Image.Image:
    """Compact METAR/TAF strip for your airports, with flight category."""
    stations = (params or {}).get("stations") or ctx.setting("airports") or [ctx.setting("home_airport")]
    if isinstance(stations, str):
        stations = [s for s in stations.replace(",", " ").split()]
    cards = []
    for s in stations:
        if s:
            cards.append(_metar_card(ctx, str(s).upper()))
            cards.append(rule("double"))
    if not cards:
        return _no_data("METAR", "No stations configured.")
    return pad(stack(*cards[:-1], gap=6), 4, 8)


# --- aviation.runway --------------------------------------------------------------------

def _rose(rwy: Optional[str], wdir: Optional[float], size: int = 96) -> Image.Image:
    """Compass rose glyph: ring, N/E/S/W ticks, the runway as a thick line and a wind
    arrow pointing the way the air is moving (i.e. from `wdir` toward the centre)."""
    S = size * 4  # draw large, downsample for cleaner lines
    img = Image.new("L", (S, S), 255)
    d = ImageDraw.Draw(img)
    c, r = S / 2, S / 2 - S * 0.04

    def pt(deg, rad):
        a = math.radians(deg)
        return c + rad * math.sin(a), c - rad * math.cos(a)

    d.ellipse([c - r, c - r, c + r, c + r], outline=0, width=S // 48)
    for k in range(0, 360, 45):
        inner = r * (0.82 if k % 90 == 0 else 0.92)
        d.line([pt(k, inner), pt(k, r)], fill=0, width=S // 40)
    nf = font("sans", int(S * 0.17), True)
    tx, ty = pt(0, r * 0.62)
    d.text((tx, ty), "N", font=nf, fill=0, anchor="mm")
    hdg = ad.runway_heading(rwy) if rwy else None
    if hdg is not None:
        d.line([pt(hdg, r * 0.78), pt(hdg + 180, r * 0.78)], fill=0, width=S // 11)
        d.line([pt(hdg, r * 0.78), pt(hdg + 180, r * 0.78)], fill=255, width=S // 80)
    if wdir is not None:
        tail, tip = pt(wdir, r * 1.02), pt(wdir, r * 0.12)
        d.line([tail, tip], fill=0, width=S // 22)
        for off in (25, -25):  # barbs fold back toward the tail
            d.line([tip, pt(wdir + off, r * 0.12 + S * 0.16)], fill=0, width=S // 22)
    small = img.resize((size, size), Image.LANCZOS)
    return small.point(lambda p: 255 if p > 140 else 0).convert("1")


def runway_job(params: dict, ctx: JobContext) -> Image.Image:
    """Runway in use at the home airport, with a wind rose and crosswind."""
    now = ctx.now()
    st = ad.runway_state(ctx, now)
    airport = str(ctx.setting("home_airport", "VOMM"))
    if not st:
        return stack(render_text(airport, size=20, bold=True, align="center"),
                     render_text("RUNWAY\nUNKNOWN", size=40, bold=True, align="center"),
                     rule("dashed"),
                     render_text("Aviation bot not reachable or no runway data yet.\n"
                                 + _clock(ctx).strftime("%d %b %H:%M"), size=16, align="center"),
                     gap=6)
    metar = ad.fetch_metar(ctx, airport)
    wdir = ad.num(metar["wdir"]) if metar else None
    wind_txt = ad.fmt_wind(metar) if metar else "wind unknown"
    parts: List[Optional[Image.Image]] = [
        render_text("%s  RUNWAY IN USE" % airport, size=18, bold=True, align="center"),
        render_text(st["runway"], size=96, bold=True, align="center", margin=0),
    ]
    if not st["live"]:
        parts.append(_badge("LAST KNOWN", 16, full=False))
    row = blank(100)
    row.paste(_rose(st["runway"], wdir), (M + 4, 2))
    d = ImageDraw.Draw(row)
    x = M + 96 + 16
    d.text((x, 18), "WIND", font=font("sans", 14, True), fill=0, anchor="ls")
    wf = _fit(wind_txt, "sans", 24, True, WIDTH - x - M, 14)
    d.text((x, 44), wind_txt, font=wf, fill=0, anchor="ls")
    hdg = ad.runway_heading(st["runway"])
    if wdir is not None and hdg is not None:
        diff = ((wdir - hdg + 180) % 360) - 180
        xw = abs(math.sin(math.radians(diff)) * (metar["wspd"] or 0))
        hw = math.cos(math.radians(diff)) * (metar["wspd"] or 0)
        d.text((x, 70), "%s %d kt" % ("head" if hw >= 0 else "tail", round(abs(hw))),
               font=font("sans", 16), fill=0, anchor="ls")
        d.text((x, 90), "xwind %d kt" % round(xw), font=font("sans", 16), fill=0, anchor="ls")
    parts.append(row)
    if st["since"]:
        since = _clock(ctx, st["since"]).strftime("%H:%M")
        sw = st["switches_today"]
        parts.append(render_text("in use since %s (%s switch%s today)" % (
            since, sw, "" if sw == 1 else "es"), size=18, align="center"))
    parts.append(render_text(_clock(ctx).strftime("%d %b %Y  %H:%M"), size=14, align="center"))
    return pad(stack(*parts, gap=4), 4, 8)


# --- aviation.now -----------------------------------------------------------------------

def now_job(params: dict, ctx: JobContext) -> Image.Image:
    """Departure-board style list of aircraft in range right now."""
    limit = max(1, min(12, int((params or {}).get("limit", 12))))
    data = ad.load_aircraft(ctx)
    ac = data["aircraft"]
    rate = ad.message_rate(data)
    head = "%d aircraft" % len(ac)
    if rate is not None:
        head += " · %.0f msg/s" % rate
    elif data["messages"] is not None:
        head += " · %s msgs" % format(int(data["messages"]), ",")
    parts: List[Optional[Image.Image]] = [
        render_text("OVERHEAD NOW", size=30, bold=True, align="center"),
        render_text(head + "\n" + _clock(ctx).strftime("%d %b %H:%M"), size=17, align="center"),
        rule("solid"),
    ]
    if not ac:
        msg = "Sky is quiet." if data["source"] != "none" else "No receiver data (aircraft.json unreadable)."
        parts.append(render_text(msg, size=20, align="center"))
        return pad(stack(*parts, gap=4), 4, 8)
    rows = ["%-8s %-4s %5s %5s %-3s" % ("CALL", "TYPE", "ALT", "KM", "BRG")]
    for a in ac[:limit]:
        call = (a["flight"] or a["registration"] or a["hex"].upper() or "?")[:8]
        dist = "%.1f" % a["dist_km"] if a["dist_km"] is not None else "--"
        brg = ad.compass16(a["bearing"]) if a["bearing"] is not None else "--"
        rows.append("%-8s %-4s %5s %5s %-3s" % (call, (a["type"] or "")[:4],
                                                ad.fmt_alt(a["alt_baro"]), dist, brg))
    parts.append(render_text("\n".join(rows), size=18, mono=True, margin=M))
    if len(ac) > limit:
        parts.append(render_text("+%d more" % (len(ac) - limit), size=16, align="right"))
    return pad(stack(*parts, gap=4), 4, 8)


# --- aviation.digest --------------------------------------------------------------------

def _line(label: str, value: Any, width: int = 31) -> str:
    v = str(value)
    return label + v.rjust(max(1, width - len(label)))


def digest_job(params: dict, ctx: JobContext) -> Image.Image:
    """Daily or weekly traffic digest: counts, busiest hours and notable aircraft."""
    kind = str((params or {}).get("kind", "daily")).lower()
    if kind not in ("daily", "weekly"):
        kind = "daily"
    days = 7 if kind == "weekly" else 1
    now = ctx.now()
    state = ad.bot_get(ctx, "/api/state")
    routes = ad.bot_get(ctx, "/api/routes/recent")
    items = [r for r in (routes or {}).get("items") or []
             if isinstance(r, dict) and (ad.num(r.get("ts")) or 0) >= now - days * 86400]
    parts: List[Optional[Image.Image]] = [
        render_text("%s DIGEST" % kind.upper(), size=32, bold=True, align="center"),
        render_text(_clock(ctx).strftime("%a %d %b %Y  %H:%M"), size=16, align="center"),
        rule("double"),
    ]
    lines: List[str] = []
    if isinstance(state, dict) and isinstance(state.get("logbook"), dict):
        lb = state["logbook"]
        lines += ["LOGBOOK (all time)",
                  _line("Airframes", format(int(lb.get("airframes") or 0), ",")),
                  _line("Sightings", format(int(lb.get("sightings") or 0), ",")),
                  _line("Messages", format(int(lb.get("messages") or 0), ","))]
        if lb.get("farthest_km") is not None:
            lines.append(_line("Farthest", "%.0f km" % lb["farthest_km"]))
            if lb.get("farthest_by"):
                lines.append(_line("  by", str(lb["farthest_by"])[:20]))
        if lb.get("highest_ft") is not None:
            lines.append(_line("Highest", "%s ft" % format(int(lb["highest_ft"]), ",")))
    else:
        lines.append("Bot offline: receiver only")
        data = ad.load_aircraft(ctx)
        ac = data["aircraft"]
        lines.append(_line("Tracked now", len(ac)))
        if data["messages"] is not None:
            lines.append(_line("Msgs since start", format(int(data["messages"]), ",")))
        far = [a for a in ac if a["dist_km"] is not None]
        if far:
            f = max(far, key=lambda a: a["dist_km"])
            lines.append(_line("Farthest now", "%.0f km" % f["dist_km"]))
        alts = [ad.num(a["alt_baro"]) for a in ac if ad.num(a["alt_baro"]) is not None]
        if alts:
            lines.append(_line("Highest now", "%s ft" % format(int(max(alts)), ",")))
    parts.append(render_text("\n".join(lines), size=18, mono=True, margin=M))

    if items:
        hexes = {r.get("icao") for r in items if r.get("icao")}
        parts += [rule("dashed"),
                  render_text("LAST %s" % ("24 H" if days == 1 else "7 DAYS"), size=18,
                              bold=True, margin=M)]
        top: Dict[str, int] = {}
        for r in items:
            if r.get("origin") and r.get("dest"):
                k = "%s>%s" % (r["origin"], r["dest"])
                top[k] = top.get(k, 0) + 1
        body = [_line("Flown routes", len(items)), _line("Airframes", len(hexes))]
        if top:
            body.append("Top routes")
            for k, n in sorted(top.items(), key=lambda kv: -kv[1])[:5]:
                body.append(_line("  " + k.replace(">", "-"), "x%d" % n))
        body.append("Recent airframes")
        seen = set()
        for r in items:
            key = r.get("icao")
            if key in seen:
                continue
            seen.add(key)
            label = r.get("registration") or r.get("callsign") or str(key).upper()
            body.append(_line("  " + str(label)[:11],
                              "%s-%s" % (r.get("origin") or "?", r.get("dest") or "?")))
            if len(seen) >= 8:
                break
        parts.append(render_text("\n".join(body), size=18, mono=True, margin=M))
    elif isinstance(state, dict):
        parts += [rule("dashed"), render_text("No flown routes logged in this period.",
                                              size=16, align="center")]
    return pad(stack(*parts, gap=4), 4, 8)


JOBS = {
    "aviation.overhead": overhead_job,
    "aviation.metar": metar_job,
    "aviation.runway": runway_job,
    "aviation.now": now_job,
    "aviation.digest": digest_job,
}
