"""SQLite persistence: job history, schedules and settings. PNGs live beside the DB."""
import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    user TEXT NOT NULL DEFAULT 'local',
    height INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    dedupe TEXT
);
CREATE INDEX IF NOT EXISTS jobs_dedupe ON jobs (dedupe, ts);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled INTEGER NOT NULL DEFAULT 1,
    spec TEXT NOT NULL,
    job TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL,
    last_run REAL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def default_data_dir() -> str:
    return os.environ.get("MINIXPRINT_DATA_DIR") or os.path.expanduser("~/.local/share/minixprint")


class Store:
    def __init__(self, data_dir: Optional[str] = None):
        self.dir = data_dir or default_data_dir()
        self.png_dir = os.path.join(self.dir, "png")
        os.makedirs(self.png_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(os.path.join(self.dir, "minixprint.db"), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _exec(self, sql: str, args: tuple = ()):
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # --- jobs --------------------------------------------------------------
    def add_job(self, kind: str, summary: str, user: str, height: int, status: str = "queued",
                error: Optional[str] = None, dedupe: Optional[str] = None) -> int:
        cur = self._exec(
            "INSERT INTO jobs (ts, kind, summary, user, height, status, error, dedupe) "
            "VALUES (?,?,?,?,?,?,?,?)", (time.time(), kind, summary, user, height, status, error, dedupe))
        return cur.lastrowid

    def set_job(self, job_id: int, status: str, error: Optional[str] = None) -> None:
        self._exec("UPDATE jobs SET status=?, error=? WHERE id=?", (status, error, job_id))

    def job(self, job_id: int) -> Optional[Dict[str, Any]]:
        rows = self._all("SELECT * FROM jobs WHERE id=?", (job_id,))
        return rows[0] if rows else None

    def history(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self._all("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))

    def depth(self) -> int:
        return self._all("SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','printing')")[0]["n"]

    def recent_dedupe(self, key: str, since: float) -> Optional[Dict[str, Any]]:
        rows = self._all("SELECT * FROM jobs WHERE dedupe=? AND ts>? AND status!='failed' "
                         "ORDER BY id DESC LIMIT 1", (key, since))
        return rows[0] if rows else None

    def fail_interrupted(self) -> None:
        self._exec("UPDATE jobs SET status='failed', error='server restarted' "
                   "WHERE status IN ('queued','printing')")

    def png_path(self, job_id: int) -> str:
        return os.path.join(self.png_dir, "%d.png" % job_id)

    # --- schedules ---------------------------------------------------------
    @staticmethod
    def _sched(r: Dict[str, Any]) -> Dict[str, Any]:
        r["enabled"] = bool(r["enabled"])
        r["params"] = json.loads(r["params"] or "{}")
        return r

    def schedules(self) -> List[Dict[str, Any]]:
        return [self._sched(r) for r in self._all("SELECT * FROM schedules ORDER BY id")]

    def schedule(self, sid: int) -> Optional[Dict[str, Any]]:
        rows = self._all("SELECT * FROM schedules WHERE id=?", (sid,))
        return self._sched(rows[0]) if rows else None

    def add_schedule(self, spec: str, job: str, params: dict, enabled: bool = True) -> Dict[str, Any]:
        cur = self._exec("INSERT INTO schedules (enabled, spec, job, params, created) VALUES (?,?,?,?,?)",
                         (int(enabled), spec, job, json.dumps(params), time.time()))
        return self.schedule(cur.lastrowid)

    def update_schedule(self, sid: int, **fields) -> None:
        if "enabled" in fields:
            fields["enabled"] = int(fields["enabled"])
        cols = ", ".join("%s=?" % k for k in fields)
        self._exec("UPDATE schedules SET %s WHERE id=?" % cols, tuple(fields.values()) + (sid,))

    def delete_schedule(self, sid: int) -> bool:
        return self._exec("DELETE FROM schedules WHERE id=?", (sid,)).rowcount > 0

    # --- settings ----------------------------------------------------------
    def stored_settings(self) -> Dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self._all("SELECT * FROM settings")}

    def put_settings(self, values: Dict[str, Any]) -> None:
        for k, v in values.items():
            self._exec("INSERT INTO settings (key, value) VALUES (?,?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))
