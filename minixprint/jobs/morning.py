"""``morning``: the breakfast docket — date, weather, todos, a note and a fortune.

Every section is optional and fails on its own: a dead network just drops the weather.
params: ``sections`` (list, default all of date/weather/todos/notes/fortune), ``todos``
(list of str), ``notes`` (str or list of str), ``seed``. Settings: ``todo_file``.
"""
import logging
import os

from PIL import Image, ImageDraw

from ..render import WIDTH, font, pad, render_text, rule, stack
from ..render.text import paint
from ._common import today
from .fortune import pick_fortune

log = logging.getLogger(__name__)

ALL = ["date", "weather", "todos", "notes", "fortune"]
FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> (text, glyph)
_CODES = [
    ((0,), "Clear sky", "sun"), ((1,), "Mostly clear", "sun"), ((2,), "Partly cloudy", "partly"),
    ((3,), "Overcast", "cloud"), ((45, 48), "Fog", "fog"),
    ((51, 53, 55, 56, 57), "Drizzle", "rain"), ((61, 63, 65, 66, 67), "Rain", "rain"),
    ((80, 81, 82), "Rain showers", "rain"), ((71, 73, 75, 77, 85, 86), "Snow", "snow"),
    ((95, 96, 99), "Thunderstorm", "storm"),
]


def describe(code):
    for codes, text, glyph in _CODES:
        if code in codes:
            return text, glyph
    return "Unknown", "cloud"


def glyph(name, s=24):
    """Tiny 1-bit weather icon, s x s px."""
    im = Image.new("1", (s, s), 1)
    d = ImageDraw.Draw(im)

    def cloud(dy=0):
        d.ellipse([3, 9 + dy, 13, 19 + dy], outline=0, fill=1, width=2)
        d.ellipse([8, 5 + dy, 18, 15 + dy], outline=0, fill=1, width=2)
        d.ellipse([13, 9 + dy, 22, 19 + dy], outline=0, fill=1, width=2)
        d.rectangle([6, 14 + dy, 19, 19 + dy], fill=1)
        d.line([5, 19 + dy, 20, 19 + dy], fill=0, width=2)

    def sun(cx, cy, r, rays=True):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
        if rays:
            import math
            for k in range(8):
                a = k * math.pi / 4
                d.line([cx + math.cos(a) * (r + 2), cy + math.sin(a) * (r + 2),
                        cx + math.cos(a) * (r + 5), cy + math.sin(a) * (r + 5)], fill=0, width=2)

    if name == "sun":
        sun(12, 12, 5)
    elif name == "partly":
        sun(8, 8, 3)
        cloud(2)
    elif name == "cloud":
        cloud()
    elif name == "fog":
        for y in (6, 11, 16, 21):
            d.line([3, y, 21, y], fill=0, width=2)
    elif name == "rain":
        cloud(-3)
        for x in (7, 12, 17):
            d.line([x, 18, x - 2, 23], fill=0, width=2)
    elif name == "snow":
        cloud(-3)
        for x in (7, 12, 17):
            d.rectangle([x - 1, 20, x, 21], fill=0)
    elif name == "storm":
        cloud(-3)
        d.polygon([(13, 15), (8, 21), (12, 21), (10, 24), (17, 18), (13, 18)], fill=0)
    return im


# --------------------------------------------------------------------------- sections

def date_section(ctx, params):
    d = today(ctx)
    return stack(
        render_text(d.strftime("%A").upper(), size=34, bold=True, align="center", margin=2),
        render_text(d.strftime("%d %B %Y").lstrip("0"), size=22, align="center", margin=0),
        render_text("day %d  |  week %d" % (d.timetuple().tm_yday, d.isocalendar()[1]),
                    size=16, align="center", margin=2), gap=0)


def weather_section(ctx, params):
    lat, lon = ctx.setting("home_lat"), ctx.setting("home_lon")
    tz = ctx.setting("timezone", "auto")
    r = ctx.http.get(FORECAST, params={
        "latitude": lat, "longitude": lon, "timezone": tz, "forecast_days": 1,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
        "hourly": "temperature_2m"}, timeout=10)
    r.raise_for_status()
    j = r.json()
    day = j["daily"]
    text, name = describe(day["weathercode"][0])
    hi, lo = day["temperature_2m_max"][0], day["temperature_2m_min"][0]
    rain = day["precipitation_probability_max"][0]
    head = Image.new("1", (WIDTH, 30), 1)
    head.paste(glyph(name), (8, 3))
    d = ImageDraw.Draw(head)
    d.text((40, 15), text, font=font("sans", 22, True), fill=0, anchor="lm")
    lines = "%d° / %d°C" % (round(hi), round(lo))
    if rain is not None:
        lines += "   rain %d%%" % rain
    return stack(head, render_text(lines, size=20, margin=2, align="center"), gap=0)


def read_todo_file(path):
    with open(path, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def todos_section(ctx, params):
    items = params.get("todos")
    if items is None:
        path = ctx.setting("todo_file")
        items = read_todo_file(path) if path and os.path.exists(path) else []
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        return None
    rows = [render_text("TO DO", size=18, bold=True, margin=2)]
    f = font("sans", 20)
    for it in items[:12]:
        box = paint([(it, f)], left=32, right=4, base_font=f)
        ImageDraw.Draw(box).rectangle([6, 5, 20, 19], outline=0, width=2)
        rows.append(pad(box, 2, 2))
    return stack(*rows, gap=2)


def notes_section(ctx, params):
    notes = params.get("notes")
    if not notes:
        return None
    if isinstance(notes, str):
        notes = [notes]
    return stack(render_text("ON THIS DAY", size=18, bold=True, margin=2),
                 render_text("\n".join(str(n) for n in notes), size=19, margin=2), gap=2)


def fortune_section(ctx, params):
    return render_text(pick_fortune(params, ctx), size=20, align="center", margin=4)


SECTIONS = {"date": date_section, "weather": weather_section, "todos": todos_section,
            "notes": notes_section, "fortune": fortune_section}


def morning(params, ctx):
    names = params.get("sections") or ALL
    blocks = []
    for name in names:
        fn = SECTIONS.get(name)
        if fn is None:
            continue
        try:
            block = fn(ctx, params)
        except Exception as exc:  # one broken section must not lose the slip
            log.warning("morning: section %s failed: %s", name, exc)
            continue
        if block is not None:
            if blocks:
                blocks.append(rule("dashed" if name != "fortune" else "double"))
            blocks.append(block)
    if not blocks:
        blocks = [render_text("Good morning!", size=28, align="center")]
    return pad(stack(*blocks, gap=2), 0, 12)


JOBS = {"morning": morning}
