import pytest
from aviation_fakes import FakeSession, full_routes, load, make_ctx

from minixprint.jobs import _aviation_data as ad
from minixprint.jobs import discover
from minixprint.render import WIDTH

NAMES = ["aviation.overhead", "aviation.metar", "aviation.runway", "aviation.now", "aviation.digest"]


def check(img):
    assert img.mode == "1" and img.width == WIDTH and img.height > 8


def test_discover_lists_all_five():
    assert set(NAMES) <= set(discover())


@pytest.mark.parametrize("name", NAMES)
def test_renders_from_fixtures(name):
    check(discover()[name]({}, make_ctx()))


@pytest.mark.parametrize("name", NAMES)
def test_renders_fully_offline(name):
    ctx = make_ctx(routes={}, aircraft=None)  # every request fails, no aircraft.json
    check(discover()[name]({}, ctx))


@pytest.mark.parametrize("name", NAMES)
def test_http_errors_do_not_raise(name):
    routes = {k: RuntimeError("boom") for k in full_routes()}
    check(discover()[name]({}, make_ctx(routes=routes, aircraft="aircraft_empty_real.json")))


@pytest.mark.parametrize("contact", [
    {}, {"hex": "abc123"}, {"hex": "abc123", "alt_baro": "ground", "gs": None},
    {"hex": "abc123", "flight": "X" * 40, "reasons": ["A" * 50, "B"], "squawk": "7700",
     "lat": "junk", "lon": None, "track": "n/a"},
    {"hex": "abc123", "origin": "MAA", "dest": None, "is_military": True},
])
def test_overhead_sparse_contacts(contact):
    check(discover()["aviation.overhead"]({"contact": contact}, make_ctx(routes={})))


def test_overhead_picks_closest_and_by_hex():
    ctx = make_ctx()
    check(discover()["aviation.overhead"]({}, ctx))
    check(discover()["aviation.overhead"]({"hex": "04022C"}, ctx))
    check(discover()["aviation.overhead"]({"hex": "ffffff"}, ctx))  # "not tracked" card


def test_overhead_no_network_when_contact_given():
    ctx = make_ctx()
    discover()["aviation.overhead"]({"contact": {"hex": "abc123", "flight": "TEST1"}}, ctx)
    assert ctx.http.calls == []


def test_load_aircraft_sorted_and_enriched():
    data = ad.load_aircraft(make_ctx())
    dists = [a["dist_km"] for a in data["aircraft"] if a["dist_km"] is not None]
    assert dists == sorted(dists)
    assert data["aircraft"][-1]["dist_km"] is None  # unpositioned sorts last
    by_hex = {a["hex"]: a for a in data["aircraft"]}
    assert by_hex["04022c"]["registration"] == "ET-AVB"  # from the bot
    assert by_hex["04022c"]["origin"] == "MAA"


def test_metar_multiple_stations_and_no_data_card():
    ctx = make_ctx(airports=["VOMM", "VIDP"])
    vomm = load("awc_metar_vomm.json")
    ctx.http.routes["aviationweather.gov/api/data/metar"] = lambda p: vomm if p["ids"] == "VOMM" else []
    ctx.http.routes["/api/metar"] = RuntimeError("down")
    both = discover()["aviation.metar"]({}, ctx)
    one = discover()["aviation.metar"]({"stations": ["VOMM"]}, ctx)
    check(both)
    assert both.height > one.height


def test_fetch_metar_falls_back_to_bot():
    ctx = make_ctx()
    ctx.http.routes["aviationweather.gov/api/data/metar"] = RuntimeError("down")
    m = ad.fetch_metar(ctx, "VOMM")
    assert m and m["category"] == "IFR" and m["wdir"] == 50
    ctx.http.routes["/api/metar"] = RuntimeError("down")
    assert ad.fetch_metar(ctx, "VOMM") is None


def test_parse_metar_fixture():
    m = ad.fetch_metar(make_ctx(), "VOMM")
    assert ad.fmt_wind(m) == "050° 10 kt"
    assert round(m["qnh"]) == 1011 and m["temp"] == 31 and m["dewp"] == 26
    assert ad.fmt_clouds(m) == "FEW 2000, SCT 10000"
    assert ad.fmt_wind({"wspd": 12, "wdir": 250, "wgst": 18}) == "250° 12G18 kt"
    assert ad.fmt_wind({"wspd": 0}) == "calm"
    assert ad.fmt_wind({"wspd": 3, "wdir": "VRB"}) == "VRB 03 kt"


@pytest.mark.parametrize("vis,ceil,cat", [
    (10, None, "VFR"), (6, 5000, "VFR"), (5.01, 3001, "VFR"),
    (5, None, "MVFR"), (3, None, "MVFR"), (10, 3000, "MVFR"), (10, 1000, "MVFR"),
    (2.99, None, "IFR"), (1, None, "IFR"), (10, 999, "IFR"), (10, 500, "IFR"),
    (0.99, None, "LIFR"), (0.25, 5000, "LIFR"), (10, 499, "LIFR"), (10, 0, "LIFR"),
    (2, 400, "LIFR"), (None, 800, "IFR"), (4, None, "MVFR"), (None, None, ""),
])
def test_flight_category(vis, ceil, cat):
    assert ad.flight_category(vis, ceil) == cat


def test_ceiling_ignores_few_and_scattered():
    assert ad.ceiling_ft([{"cover": "FEW", "base": 500}, {"cover": "SCT", "base": 800}]) is None
    assert ad.ceiling_ft([{"cover": "BKN", "base": 2500}, {"cover": "OVC", "base": 1200}]) == 1200


def test_haversine_known_values():
    # Chennai (MAA) -> Mumbai (BOM) ~1030 km; one degree of latitude ~111.19 km
    assert ad.haversine_km(12.9941, 80.1709, 19.0887, 72.8679) == pytest.approx(1032, abs=15)
    assert ad.haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.05)
    assert ad.haversine_km(12.9, 80.1, 12.9, 80.1) == 0
    # London -> Paris ~343.5 km
    assert ad.haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(343.5, abs=1.5)


def test_bearing_cardinals_and_compass():
    assert ad.bearing_deg(0, 0, 1, 0) == pytest.approx(0)
    assert ad.bearing_deg(0, 0, 0, 1) == pytest.approx(90)
    assert ad.bearing_deg(1, 0, 0, 0) == pytest.approx(180)
    assert ad.bearing_deg(0, 1, 0, 0) == pytest.approx(270)
    assert ad.bearing_deg(0, 0, 1, 1) == pytest.approx(45, abs=0.1)
    names = {0: "N", 22.5: "NNE", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW",
             270: "W", 315: "NW", 337.5: "NNW", 359: "N", 11: "N", 12: "NNE", 348.7: "NNW"}
    for deg, name in names.items():
        assert ad.compass16(deg) == name, deg


def test_runway_state_from_summary():
    ctx = make_ctx()
    st = ad.runway_state(ctx, ctx.now())
    assert st["runway"] == "25" and st["live"] is True
    assert st["since"] == pytest.approx(ctx.now() - 1800)
    assert st["switches_today"] >= 1


def test_runway_degrades_when_bot_down():
    ctx = make_ctx(routes={"aviationweather": full_routes()["aviationweather.gov/api/data/metar"]})
    img = discover()["aviation.runway"]({}, ctx)
    check(img)
    assert ad.runway_state(ctx, ctx.now()) is None


def test_runway_falls_back_to_state_block():
    routes = full_routes()
    routes["/api/runways/summary"] = {"ok": False, "error": "x"}
    routes["/api/state"] = {"runway": {"runway": None, "last_confirmed_runway": "07"}}
    st = ad.runway_state(make_ctx(routes=routes), 1791813446.6)
    assert st == {"runway": "07", "since": None, "switches_today": None, "live": False}
    check(discover()["aviation.runway"]({}, make_ctx(routes=routes)))


def test_runway_heading():
    assert ad.runway_heading("25") == 250 and ad.runway_heading("07L") == 70
    assert ad.runway_heading("36") == 360 and ad.runway_heading("x") is None


def test_now_limit_and_messages():
    full = discover()["aviation.now"]({"limit": 12}, make_ctx())
    short = discover()["aviation.now"]({"limit": 3}, make_ctx())
    assert short.height < full.height


def test_message_rate_is_delta_between_readings():
    ad._rate_cache.clear()
    assert ad.message_rate({"messages": 100, "now": 1000.0}) is None
    assert ad.message_rate({"messages": 400, "now": 1010.0}) == pytest.approx(30.0)


@pytest.mark.parametrize("kind", ["daily", "weekly", "bogus"])
def test_digest_kinds(kind):
    check(discover()["aviation.digest"]({"kind": kind}, make_ctx()))


def test_digest_bot_down_uses_aircraft_json():
    ctx = make_ctx(routes={})
    ctx.http = FakeSession({})
    check(discover()["aviation.digest"]({}, ctx))


def test_timeouts_are_capped():
    ctx = make_ctx()
    for n in NAMES:
        discover()[n]({}, ctx)  # FakeSession asserts timeout <= 5 on every call
    assert ctx.http.calls
