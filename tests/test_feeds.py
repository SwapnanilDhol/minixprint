import copy
import json
import os
import time

import pytest
from aviation_fakes import FakeSession, load, make_ctx
from fastapi.testclient import TestClient

from minixprint import feeds
from minixprint.feeds import acars, metar
from minixprint.jobs import DEFAULT_SETTINGS, JobContext
from minixprint.server import create_app

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "feeds")
MSGS = json.load(open(os.path.join(FIX, "bot_messages.json"), encoding="utf-8"))
METAR1 = load("awc_metar_vomm.json")
METAR2 = copy.deepcopy(METAR1)
METAR2[0].update(obsTime=METAR1[0]["obsTime"] + 1800, wdir=70, wspd=14, visib=6, fltCat="MVFR",
                 rawOb="METAR VOMM 121400Z 07014KT 6000 FEW020 SCT100 31/26 Q1010 NOSIG")


def ctx_for(routes):
    return JobContext(settings=dict(DEFAULT_SETTINGS), http=FakeSession(routes))


BOT = {"source": "bot", "print_binary": True}  # the fixture's newest messages are encrypted H1/T1 blobs


def bot_ctx(items=None):
    return ctx_for({"/api/messages": {"items": MSGS["items"] if items is None else items}})


def metar_ctx(data):
    return ctx_for({"aviationweather.gov/api/data/metar": data})


# --- registry / schema -------------------------------------------------------------------

def test_discover_kinds():
    k = feeds.discover()
    assert {"metar", "acars"} <= set(k)
    assert k["metar"].PARAMS["station"]["required"] and k["acars"].DEFAULT_INTERVAL_S == 15


def test_validate_params():
    assert feeds.validate(metar, {"station": " vomm "}) == {"station": "VOMM"}
    with pytest.raises(ValueError):
        feeds.validate(metar, {})
    with pytest.raises(ValueError):
        feeds.validate(metar, {"station": "TOOLONG"})
    with pytest.raises(ValueError):
        feeds.validate(metar, {"station": "VOMM", "bogus": 1})
    p = feeds.validate(acars, {"skip_labels": "Q0, _d"})
    assert p == {"source": "auto", "udp_port": 5570, "print_binary": False,
                 "skip_labels": ["Q0", "_d"], "min_text_len": 1}
    assert feeds.validate(acars, {"print_binary": "true", "udp_port": "5571"})["print_binary"] is True
    assert feeds.validate(acars, {})["skip_labels"] == ["Q0", "_d", "Q1"]
    with pytest.raises(ValueError):
        feeds.validate(acars, {"source": "nope"})


# --- metar -------------------------------------------------------------------------------

def test_metar_cursor_semantics():
    p = {"station": "VOMM"}
    items, cur = metar.poll(p, None, metar_ctx(METAR1))
    assert len(items) == 1 and cur == METAR1[0]["rawOb"] and items[0]["key"] == str(METAR1[0]["obsTime"])
    again, cur2 = metar.poll(p, cur, metar_ctx(METAR1))
    assert again == [] and cur2 == cur
    changed, cur3 = metar.poll(p, cur, metar_ctx(METAR2))
    assert len(changed) == 1 and cur3 == METAR2[0]["rawOb"] != cur


def test_metar_fetch_failure_raises():
    with pytest.raises(RuntimeError):
        metar.poll({"station": "VOMM"}, None, ctx_for({}))


def test_metar_render():
    ctx = make_ctx()
    items, _ = metar.poll({"station": "VOMM"}, None, ctx)
    img = metar.render(items[0], {"station": "VOMM"}, ctx)
    assert img.mode == "1" and img.width == 384 and 100 < img.height < 600


# --- acars -------------------------------------------------------------------------------

def test_acars_first_poll_capped_and_collapsed():
    items, cur = acars.poll(feeds.validate(acars, BOT), None, bot_ctx())
    assert cur == 40
    # newest three raw messages (40, 39, 38) are one flight within 20 s -> one ticket
    assert len(items) == 1 and [m["id"] for m in items[0]["messages"]] == [38, 39, 40]
    assert items[0]["key"] == "40"


def test_acars_only_ids_above_cursor():
    p = feeds.validate(acars, BOT)
    items, cur = acars.poll(p, 36, bot_ctx())
    ids = [m["id"] for g in items for m in g["messages"]]
    assert ids == [37, 38, 39, 40] and cur == 40
    items, cur = acars.poll(p, 40, bot_ctx())
    assert items == [] and cur == 40


def test_acars_skip_labels_and_min_len():
    extra = [{"id": 41, "ts": 1787669990, "callsign": "AI101", "label": "Q0", "text": "link test"},
             {"id": 42, "ts": 1787670100, "callsign": "AI102", "label": "H1", "text": ""},
             {"id": 43, "ts": 1787670200, "callsign": "AI103", "label": "_d", "text": "ack"}]
    ctx = bot_ctx(extra + MSGS["items"])
    items, cur = acars.poll(feeds.validate(acars, dict(BOT, min_text_len=1)), 40, ctx)
    assert items == [] and cur == 43  # all skipped, but the cursor still moves past them
    items, _ = acars.poll(feeds.validate(acars, dict(BOT, skip_labels=[], min_text_len=0)), 40, ctx)
    assert [g["flight"] for g in items] == ["AI101", "AI102", "AI103"]


def test_acars_collapse_window():
    msgs = [{"id": 1, "ts": 100, "callsign": "A", "text": "x"}, {"id": 2, "ts": 119, "callsign": "A", "text": "y"},
            {"id": 3, "ts": 141, "callsign": "A", "text": "z"}, {"id": 4, "ts": 142, "callsign": "B", "text": "w"}]
    groups = acars.collapse(msgs)
    assert [[m["id"] for m in g["messages"]] for g in groups] == [[1, 2], [3], [4]]


def test_acars_source_down():
    with pytest.raises(RuntimeError):
        acars.poll(feeds.validate(acars, {"source": "bot"}), None, ctx_for({}))


def test_acars_render():
    ctx = make_ctx()
    items, _ = acars.poll(feeds.validate(acars, BOT), None, bot_ctx())
    img = acars.render(items[0], {}, ctx)
    assert img.mode == "1" and img.width == 384 and img.height > 150


# --- API / manager ----------------------------------------------------------------------

@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=str(tmp_path), fake=True, scheduler=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def use_http(app, routes):
    app.state.feeds.ctx = lambda: ctx_for(routes)


def jobs_of(client):
    return client.get("/api/history").json()


def test_api_kinds(client):
    ks = {k["kind"]: k for k in client.get("/api/feeds/kinds").json()}
    assert ks["metar"]["params"]["station"]["type"] == "icao" and ks["metar"]["default_interval_s"] == 300


def test_api_crud(client):
    assert client.get("/api/feeds").json() == []
    r = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "vomm"}})
    assert r.status_code == 201
    f = r.json()
    assert f["params"] == {"station": "VOMM"} and f["interval_s"] == 300 and f["enabled"] is False
    assert f["printed"] == 0 and "cursor" not in f
    fid = f["id"]
    assert client.post("/api/feeds/%d/start" % fid).json()["enabled"] is True
    assert client.post("/api/feeds/%d/stop" % fid).json()["enabled"] is False
    assert client.delete("/api/feeds/%d" % fid).status_code == 204
    assert client.delete("/api/feeds/%d" % fid).status_code == 404
    assert client.post("/api/feeds/99/start").status_code == 404


def test_api_validation(client):
    assert client.post("/api/feeds", json={"kind": "nope"}).status_code == 422
    assert client.post("/api/feeds", json={"kind": "metar", "params": {}}).status_code == 422
    assert client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"},
                                           "interval_s": 2}).status_code == 422


def test_poll_prints_once_then_on_change(app, client):
    fid = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"}}).json()["id"]
    use_http(app, {"aviationweather.gov/api/data/metar": METAR1})
    f = client.post("/api/feeds/%d/poll" % fid).json()
    assert f["printed"] == 1 and f["error"] is None and f["last_poll"] and f["last_item_ts"] == METAR1[0]["obsTime"]
    f = client.post("/api/feeds/%d/poll" % fid).json()
    assert f["printed"] == 1  # unchanged observation: nothing new
    use_http(app, {"aviationweather.gov/api/data/metar": METAR2})
    assert client.post("/api/feeds/%d/poll" % fid).json()["printed"] == 2
    hist = [h for h in jobs_of(client) if h["kind"] == "feed:metar"]
    assert len(hist) == 2 and hist[0]["summary"] == "metar VOMM" and hist[0]["user"] == "feed"


def test_dedupe_key_format(app, client):
    fid = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"}}).json()["id"]
    use_http(app, {"aviationweather.gov/api/data/metar": METAR1})
    client.post("/api/feeds/%d/poll" % fid)
    rows = app.state.store._all("SELECT dedupe FROM jobs")
    assert rows == [{"dedupe": "feed:%d:%d" % (fid, METAR1[0]["obsTime"])}]
    # losing the cursor (e.g. DB edit) must not reprint inside the queue's dedupe window
    app.state.store.update_feed(fid, cursor=None)
    assert client.post("/api/feeds/%d/poll" % fid).json()["printed"] == 1
    assert len(app.state.store._all("SELECT id FROM jobs")) == 1


def test_error_recorded_and_cursor_kept(app, client):
    fid = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"}}).json()["id"]
    use_http(app, {"aviationweather.gov/api/data/metar": METAR1})
    client.post("/api/feeds/%d/poll" % fid)
    use_http(app, {})
    f = client.post("/api/feeds/%d/poll" % fid).json()
    assert "METAR fetch failed" in f["error"] and f["printed"] == 1
    use_http(app, {"aviationweather.gov/api/data/metar": METAR1})
    f = client.post("/api/feeds/%d/poll" % fid).json()
    assert f["error"] is None and f["printed"] == 1  # cursor survived the outage


def test_acars_feed_end_to_end(app, client):
    fid = client.post("/api/feeds", json={"kind": "acars", "params": BOT}).json()["id"]
    use_http(app, {"/api/messages": MSGS})
    f = client.post("/api/feeds/%d/poll" % fid).json()
    assert f["printed"] == 1 and f["params"]["source"] == "bot"
    assert client.post("/api/feeds/%d/poll" % fid).json()["printed"] == 1
    newer = {"items": [dict(MSGS["items"][0], id=41, ts=MSGS["items"][0]["ts"] + 300)] + MSGS["items"]}
    use_http(app, {"/api/messages": newer})
    assert client.post("/api/feeds/%d/poll" % fid).json()["printed"] == 2


def test_preview(app, client):
    fid = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"}}).json()["id"]
    use_http(app, {"aviationweather.gov/api/data/metar": METAR1})
    r = client.get("/api/feeds/%d/preview" % fid)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert app.state.store.feed(fid)["cursor"] is None and jobs_of(client) == []
    use_http(app, {})
    assert client.get("/api/feeds/%d/preview" % fid).status_code == 502
    aid = client.post("/api/feeds", json={"kind": "acars", "params": {"source": "bot"}}).json()["id"]
    use_http(app, {"/api/messages": {"items": []}})
    assert client.get("/api/feeds/%d/preview" % aid).status_code == 404


def test_tick_polls_due_enabled_feeds_only(app, client):
    a = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"}, "enabled": True}).json()["id"]
    b = client.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOBL"}}).json()["id"]
    use_http(app, {"aviationweather.gov/api/data/metar": METAR1})
    mgr = app.state.feeds
    assert mgr.tick() == [a]
    assert mgr.tick() == []                      # not due again yet
    assert mgr.tick(now=time.time() + 301) == [a]
    assert app.state.store.feed(b)["last_poll"] is None


def test_persistence_across_restart(tmp_path):
    app1 = create_app(data_dir=str(tmp_path), fake=True, scheduler=False)
    with TestClient(app1) as c:
        fid = c.post("/api/feeds", json={"kind": "metar", "params": {"station": "VOMM"}, "enabled": True}).json()["id"]
        use_http(app1, {"aviationweather.gov/api/data/metar": METAR1})
        c.post("/api/feeds/%d/poll" % fid)
    app2 = create_app(data_dir=str(tmp_path), fake=True, scheduler=False)
    with TestClient(app2) as c:
        f = c.get("/api/feeds").json()[0]
        assert f["id"] == fid and f["enabled"] is True and f["printed"] == 1
        use_http(app2, {"aviationweather.gov/api/data/metar": METAR1})
        assert c.post("/api/feeds/%d/poll" % fid).json()["printed"] == 1  # cursor persisted: no reprint
        assert app2.state.feeds.tick(now=time.time() + 301) == [fid]       # still scheduled


def test_cli_param_parsing():
    from minixprint.cli import _feed_params
    k = {"params": {"station": {"required": True}, "x": {}}}
    assert _feed_params(k, ["VOMM", "x=1"]) == {"station": "VOMM", "x": "1"}
    with pytest.raises(ValueError):
        _feed_params(k, ["A", "B"])
