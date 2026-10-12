"""Printer loss: status flips to disconnected, HTTP keeps answering, queued jobs wait and print on return."""
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from minixprint.printer import MiniX
from minixprint.server import create_app
from minixprint.server import queue as qmod
from minixprint.transport import Transport


class FakeTransport(Transport):
    """Healthy until `fail_at` (a write/read count) is reached, then raises OSError."""

    def __init__(self, hub):
        self.hub = hub
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True

    def _tick(self):
        self.hub.ops += 1
        if self.hub.broken or (self.hub.fail_at is not None and self.hub.ops >= self.hub.fail_at):
            self.hub.broken = True
            raise OSError(6, "Device not configured")

    def write(self, data):
        self._tick()
        self.hub.written.append(bytes(data))

    def read(self, timeout):
        self._tick()
        return b"\x00\x00\x5a"


class Hub:
    def __init__(self):
        self.ops = 0
        self.fail_at = None
        self.broken = False
        self.written = []
        self.available = True
        self.connects = 0

    def connect(self):
        if not self.available:
            raise RuntimeError("no printer found")
        self.connects += 1
        self.ops, self.fail_at, self.broken = 0, None, False
        return MiniX(FakeTransport(self)).open()


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(qmod, "RECONNECT_MIN", 0.05)
    monkeypatch.setattr(qmod, "RECONNECT_MAX", 0.2)
    monkeypatch.setattr(qmod, "STATUS_TTL", 0.05)
    monkeypatch.setattr(qmod, "INFO_TTL", 0.05)


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def job_status(client, jid):
    return next(h for h in client.get("/api/history").json() if h["id"] == jid)["status"]


def img():
    return Image.new("1", (384, 16), 0)


def test_refresh_failure_then_recovery_prints_queued_job(tmp_path, fast):
    hub = Hub()
    app = create_app(data_dir=str(tmp_path), connect_fn=hub.connect, scheduler=False)
    with TestClient(app) as c:
        assert wait_for(lambda: c.get("/api/status").json()["connected"])
        hub.available = False
        hub.broken = True  # next refresh hits OSError
        assert wait_for(lambda: not c.get("/api/status").json()["connected"])
        s = c.get("/api/status").json()
        assert s["fake"] is False and s["connected"] is False and "Device not configured" in s["error"]
        assert c.get("/api/history").status_code == 200

        r = c.post("/api/print/text", json={"text": "while away"})
        assert r.status_code == 200
        jid = r.json()["id"]
        time.sleep(0.4)
        assert job_status(c, jid) == "queued"  # waits, not faked
        assert c.get("/api/status").json()["connected"] is False

        before = len(hub.written)
        hub.available = True
        assert wait_for(lambda: job_status(c, jid) == "done")
        assert len(hub.written) > before
        s = c.get("/api/status").json()
        assert s["connected"] is True and s["fake"] is False


def test_job_fails_mid_print_next_job_waits(tmp_path, fast):
    hub = Hub()
    app = create_app(data_dir=str(tmp_path), connect_fn=hub.connect, scheduler=False)
    with TestClient(app) as c:
        assert wait_for(lambda: c.get("/api/status").json()["connected"])
        # break the transport on the very next write (the job's first)
        hub.available = False
        hub.fail_at = hub.ops + 1
        j1 = c.post("/api/print/text", json={"text": "one"}).json()["id"]
        assert wait_for(lambda: job_status(c, j1) == "failed")
        row = next(h for h in c.get("/api/history").json() if h["id"] == j1)
        assert "Device not configured" in row["error"]
        s = c.get("/api/status").json()
        assert s["connected"] is False and s["fake"] is False

        j2 = c.post("/api/print/text", json={"text": "two"}).json()["id"]
        time.sleep(0.4)
        assert job_status(c, j2) == "queued"
        hub.available = True
        assert wait_for(lambda: job_status(c, j2) == "done")
        assert app.state.queue.status()["connected"]


def test_unexpected_exceptions_do_not_kill_worker(tmp_path, fast):
    hub = Hub()
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyError("boom")  # not an OSError
        return hub.connect()

    app = create_app(data_dir=str(tmp_path), connect_fn=flaky, scheduler=False)
    with TestClient(app) as c:
        assert wait_for(lambda: c.get("/api/status").json()["connected"])
        hub.broken = True
        assert wait_for(lambda: not c.get("/api/status").json()["connected"])
        assert wait_for(lambda: calls["n"] >= 3)  # survived KeyError, kept retrying
        assert wait_for(lambda: c.get("/api/status").json()["connected"])


def test_backoff_grows_and_caps(tmp_path, monkeypatch):
    monkeypatch.setattr(qmod, "RECONNECT_MIN", 2.0)
    assert qmod.RECONNECT_MIN == 2.0 and qmod.RECONNECT_MAX == 30.0
    from minixprint.server.store import Store
    q = qmod.PrintQueue(Store(str(tmp_path)), lambda: {}, connect_fn=lambda: (_ for _ in ()).throw(OSError("x")))
    waits = []
    for _ in range(7):
        q._connect()
        waits.append(q._backoff)
    assert waits == [4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 30.0]


def test_never_connected_stays_fake(tmp_path, fast):
    hub = Hub()
    hub.available = False
    app = create_app(data_dir=str(tmp_path), connect_fn=hub.connect, scheduler=False)
    with TestClient(app) as c:
        s = c.get("/api/status").json()
        assert s["fake"] is True and s["connected"] is False
