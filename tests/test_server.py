import io
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from minixprint.server import create_app
from minixprint.server.scheduler import SpecError, next_run, parse_spec

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=str(tmp_path), fake=True, scheduler=False)
    with TestClient(app) as c:
        yield c


def png(width=384, height=40, mode="1"):
    buf = io.BytesIO()
    Image.new(mode, (width, height), 0 if mode == "1" else 128).save(buf, "PNG")
    return buf.getvalue()


def wait_done(client, job_id):
    for _ in range(50):
        row = next(h for h in client.get("/api/history").json() if h["id"] == job_id)
        if row["status"] not in ("queued", "printing"):
            return row
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_status_fake(client):
    s = client.get("/api/status").json()
    assert s["fake"] is True and s["queue_depth"] == 0 and s["user"] == "local"


def test_print_endpoints_and_history(client):
    hdr = {"Tailscale-User-Name": "Swap", "Tailscale-User-Login": "swap@example.com"}
    reqs = [
        ("text", {"json": {"text": "hello"}}),
        ("markdown", {"json": {"markdown": "# hi\n- a"}}),
        ("receipt", {"json": {"title": "T", "items": [{"name": "x", "qty": 1, "price": 2}]}}),
        ("qr", {"json": {"data": "https://example.com", "caption": "c"}}),
        ("image?dither=atkinson&gamma=1.2&invert=true", {"files": {"file": ("a.png", png(200, 100, "L"), "image/png")}}),
        ("raw", {"files": {"file": ("a.png", png(), "image/png")}}),
    ]
    for path, kw in reqs:
        r = client.post("/api/print/" + path, headers=hdr, **kw)
        assert r.status_code == 200, (path, r.text)
        j = r.json()
        assert wait_done(client, j["id"])["status"] == "done"
        assert client.get("/api/history/%d.png" % j["id"]).status_code == 200
    hist = client.get("/api/history?limit=3").json()
    assert len(hist) == 3
    assert hist[0]["user"] == "Swap" and hist[0]["kind"] == "raw" and hist[0]["height_px"] == 40
    assert set(hist[0]) >= {"id", "ts", "kind", "summary", "user", "height_px", "status", "error"}


def test_user_fallback_login(client):
    j = client.post("/api/print/text", json={"text": "x"}, headers={"Tailscale-User-Login": "a@b.c"}).json()
    assert client.get("/api/history").json()[0]["user"] == "a@b.c"
    assert j["status"] in ("queued", "printing", "done")


def test_previews_are_384_wide_pngs(client):
    cases = [
        ("text", {"json": {"text": "hello"}}),
        ("markdown", {"json": {"markdown": "# hi"}}),
        ("receipt", {"json": {"title": "T", "items": []}}),
        ("qr", {"json": {"data": "x"}}),
        ("image", {"files": {"file": ("a.jpg", png(50, 50, "L"), "image/png")}}),
        ("raw", {"files": {"file": ("a.png", png(), "image/png")}}),
        ("jobs/fortune", {"json": {}}),
    ]
    for path, kw in cases:
        r = client.post("/api/preview/" + path, **kw)
        assert r.status_code == 200 and r.headers["content-type"] == "image/png", path
        assert Image.open(io.BytesIO(r.content)).width == 384
    assert client.get("/api/history").json() == []  # previews are not recorded


def test_raw_wrong_width_and_bad_image(client):
    r = client.post("/api/print/raw", files={"file": ("a.png", png(100), "image/png")})
    assert r.status_code == 400
    r = client.post("/api/print/image", files={"file": ("a.png", b"junk", "image/png")})
    assert r.status_code == 415


def test_jobs(client):
    names = {j["name"]: j["description"] for j in client.get("/api/jobs").json()}
    assert "fortune" in names and names["fortune"]
    r = client.post("/api/jobs/fortune/run", json={})
    assert r.status_code == 200
    assert wait_done(client, r.json()["id"])["kind"] == "job:fortune"
    assert client.post("/api/jobs/nope/run", json={}).status_code == 404


def test_dedupe(client):
    a = client.post("/api/jobs/fortune/run?dedupe=k1", json={}).json()
    b = client.post("/api/jobs/fortune/run?dedupe=k1", json={}).json()
    assert a["status"] != "skipped" and b["status"] == "skipped" and b["skipped_of"] == a["id"]
    assert client.post("/api/jobs/fortune/run?dedupe=k2", json={}).json()["status"] != "skipped"


def test_feed(client):
    r = client.post("/api/feed", json={"dots": 50})
    assert r.status_code == 200
    assert wait_done(client, r.json()["id"])["kind"] == "feed"


def test_max_height_enforced(client):
    assert client.put("/api/settings", json={"max_height_px": 100}).status_code == 200
    r = client.post("/api/print/text", json={"text": "line\n" * 30})
    assert r.status_code == 413
    assert client.post("/api/preview/text", json={"text": "line\n" * 30}).status_code == 413


def test_settings(client):
    s = client.get("/api/settings").json()
    assert s["max_height_px"] == 4000 and s["density"] == 2 and s["timezone"] == "Asia/Kolkata"
    s = client.put("/api/settings", json={"home_airport": "vobl", "airports": ["vobl", "vomm"], "density": 1}).json()
    assert s["home_airport"] == "VOBL" and s["airports"] == ["VOBL", "VOMM"] and s["density"] == 1
    assert client.put("/api/settings", json={"timezone": "Mars/Base"}).status_code == 422


def test_schedules_crud(client):
    r = client.post("/api/schedules", json={"spec": "daily 07:30", "job": "fortune", "params": {"seed": 1}})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.get("/api/schedules").json()[0]["params"] == {"seed": 1}
    assert client.patch("/api/schedules/%d" % sid, json={"enabled": False}).json()["enabled"] is False
    assert client.post("/api/schedules", json={"spec": "whenever", "job": "fortune"}).status_code == 422
    assert client.post("/api/schedules", json={"spec": "every 5m", "job": "nope"}).status_code == 404
    assert client.delete("/api/schedules/%d" % sid).status_code == 204
    assert client.delete("/api/schedules/%d" % sid).status_code == 404
    assert client.get("/api/schedules").json() == []


def test_scheduler_tick_fires(tmp_path):
    app = create_app(data_dir=str(tmp_path), fake=True, scheduler=False)
    with TestClient(app) as c:
        sid = c.post("/api/schedules", json={"spec": "every 1m", "job": "fortune"}).json()["id"]
        sch = app.state.scheduler
        assert sch.tick(time.time()) == []
        assert sch.tick(time.time() + 90) == [sid]
        assert sch.tick(time.time() + 91) == []  # last_run advanced
        time.sleep(0.3)
        assert c.get("/api/history").json()[0]["user"] == "scheduler"


def test_static_dashboard_and_root_path(tmp_path):
    app = create_app(data_dir=str(tmp_path), fake=True, scheduler=False, root_path="/print")
    with TestClient(app) as c:
        assert "MiniX" in c.get("/").text
        assert c.get("/app.js").status_code == 200
        # served at /print (no slash) by tailscale: page must redirect itself so relative assets resolve
        assert "location.pathname.endsWith" in c.get("/").text
        assert c.get("/api/status").status_code == 200
        assert c.get("/print/api/status").status_code == 200  # proxy that keeps the prefix
        assert c.get("/openapi.json").json()["servers"][0]["url"] == "/print"


def test_settings_aviation_sources(tmp_path):
    with TestClient(create_app(data_dir=str(tmp_path), fake=True, scheduler=False)) as c:
        r = c.put("/api/settings", json={"aircraft_json": "/tmp/a.json", "aviation_bot_url": "http://x:1", "home_lat": 1.5})
        assert r.json()["aircraft_json"] == "/tmp/a.json" and r.json()["home_lat"] == 1.5
        assert c.get("/api/settings").json()["aviation_bot_url"] == "http://x:1"


def test_spec_parser_errors():
    for bad in ["", "daily", "daily 25:00", "weekly FUN 10:00", "every 0m", "every 5", "hourly"]:
        with pytest.raises(SpecError):
            parse_spec(bad)


def test_next_run_every():
    t = datetime(2026, 3, 2, 10, 0, tzinfo=IST)
    assert next_run("every 30m", t, IST) == datetime(2026, 3, 2, 10, 30, tzinfo=IST)
    assert next_run("every 2h", t, IST) == datetime(2026, 3, 2, 12, 0, tzinfo=IST)


def test_next_run_daily():
    assert next_run("daily 07:30", datetime(2026, 3, 2, 6, 0, tzinfo=IST), IST) == datetime(2026, 3, 2, 7, 30, tzinfo=IST)
    assert next_run("daily 07:30", datetime(2026, 3, 2, 7, 30, tzinfo=IST), IST) == datetime(2026, 3, 3, 7, 30, tzinfo=IST)
    # an instant given in UTC is interpreted in the schedule's zone
    utc = datetime(2026, 3, 2, 3, 0, tzinfo=ZoneInfo("UTC"))  # 08:30 IST
    assert next_run("daily 07:30", utc, IST) == datetime(2026, 3, 3, 7, 30, tzinfo=IST)


def test_next_run_weekly():
    mon = datetime(2026, 3, 2, 12, 0, tzinfo=IST)  # a Monday
    assert next_run("weekly MON,FRI 09:00", mon, IST) == datetime(2026, 3, 6, 9, 0, tzinfo=IST)
    assert next_run("weekly MON,FRI 18:00", mon, IST) == datetime(2026, 3, 2, 18, 0, tzinfo=IST)
    fri = datetime(2026, 3, 6, 19, 0, tzinfo=IST)
    assert next_run("weekly MON,FRI 18:00", fri, IST) == datetime(2026, 3, 9, 18, 0, tzinfo=IST)


def test_every_job_has_a_distinct_description(client):
    jobs = client.get("/api/jobs").json()
    assert len(jobs) >= 10
    descs = {j["name"]: j["description"] for j in jobs}
    assert all(d.strip() for d in descs.values()), descs
    assert len(set(descs.values())) == len(descs), "duplicate job descriptions: %r" % descs
