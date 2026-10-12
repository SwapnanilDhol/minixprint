"""Offline stand-ins for ctx.http, serving tests/fixtures/aviation. Shared by the tests
and scripts/make_aviation_samples.py."""
import json
import os

from minixprint.jobs import DEFAULT_SETTINGS, JobContext

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "aviation")
NOW = 1791813446.6  # when the fixtures were captured


def load(name):
    with open(os.path.join(FIX, name), "r", encoding="utf-8") as f:
        return json.load(f)


class Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


class FakeSession:
    """routes: {url-substring: json | callable(params) | Exception}; first match wins.
    Unmatched URLs raise ConnectionError, like an unreachable host."""

    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def get(self, url, params=None, timeout=None):
        assert timeout is not None and timeout <= 5, "every request needs timeout <= 5s"
        self.calls.append((url, params))
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return Resp(val(params) if callable(val) else val)
        raise ConnectionError("unreachable: " + url)


def full_routes():
    return {
        "aviationweather.gov/api/data/metar": load("awc_metar_vomm.json"),
        "aviationweather.gov/api/data/taf": load("awc_taf_vomm.json"),
        "/api/metar": load("bot_metar.json"),
        "/api/aircraft": load("bot_aircraft.json"),
        "/api/runways/summary": load("bot_runways_summary.json"),
        "/api/state": load("bot_state.json"),
        "/api/routes/recent": load("bot_routes_recent.json"),
    }


class FixedCtx(JobContext):
    def now(self):
        return NOW


def make_ctx(routes=None, aircraft="aircraft.json", **settings):
    s = dict(DEFAULT_SETTINGS)
    s["aircraft_json"] = os.path.join(FIX, aircraft) if aircraft else "/nonexistent/aircraft.json"
    s.update(settings)
    return FixedCtx(settings=s, http=FakeSession(full_routes() if routes is None else routes))
