"""Cron-ish scheduler: a thread that ticks every 30 s and enqueues due schedules.

Spec grammar (evaluated in the configured timezone):
    daily HH:MM
    weekly MON,FRI HH:MM
    every 30m        (also 2h, 45s is not allowed: minutes or hours only)
"""
import logging
import re
import threading
import time
from datetime import datetime, timedelta, tzinfo
from datetime import time as dtime
from typing import Callable, List, Optional, Tuple

from .store import Store

log = logging.getLogger("minixprint.scheduler")

TICK = 30.0
GRACE = 600.0  # a daily/weekly slot missed by more than this (server was down) is skipped
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


class SpecError(ValueError):
    pass


def _hhmm(s: str) -> dtime:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise SpecError("bad time %r (want HH:MM)" % s)
    return dtime(int(m.group(1)), int(m.group(2)))


def parse_spec(spec: str) -> Tuple[str, object]:
    """-> ("every", timedelta) | ("daily", (time, days 0-6)) | ("weekly", (time, days))."""
    parts = spec.strip().split()
    kind = parts[0].lower() if parts else ""
    if kind == "daily" and len(parts) == 2:
        return "daily", (_hhmm(parts[1]), set(range(7)))
    if kind == "weekly" and len(parts) == 3:
        days = set()
        for d in parts[1].upper().split(","):
            if d not in DAYS:
                raise SpecError("bad weekday %r (want MON..SUN)" % d)
            days.add(DAYS.index(d))
        return "weekly", (_hhmm(parts[2]), days)
    if kind == "every" and len(parts) == 2:
        m = re.fullmatch(r"(\d+)([mh])", parts[1].lower())
        if m and int(m.group(1)) > 0:
            n = int(m.group(1))
            return "every", timedelta(minutes=n) if m.group(2) == "m" else timedelta(hours=n)
    raise SpecError("bad schedule %r; use 'daily HH:MM', 'weekly MON,FRI HH:MM' or 'every 30m'" % spec)


def next_run(spec: str, after: datetime, tz: tzinfo) -> datetime:
    """First run strictly after ``after`` (an aware datetime), in ``tz``."""
    kind, arg = parse_spec(spec)
    after = after.astimezone(tz)
    if kind == "every":
        return after + arg  # type: ignore[operator]
    at, days = arg  # type: ignore[misc]
    for offset in range(8):
        day = after.date() + timedelta(days=offset)
        cand = datetime.combine(day, at, tzinfo=tz)
        if day.weekday() in days and cand > after:
            return cand
    raise SpecError("no occurrence found")  # pragma: no cover


class Scheduler:
    def __init__(self, store: Store, submit: Callable[[str, dict], None], tz: Callable[[], tzinfo]):
        self.store, self.submit, self.tz = store, submit, tz
        self._stop = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            self._stop.wait(TICK)

    def tick(self, now: Optional[float] = None) -> List[int]:
        """Run every due schedule once; returns the ids that fired."""
        now = time.time() if now is None else now
        fired = []
        tz = self.tz()
        for s in self.store.schedules():
            if not s["enabled"]:
                continue
            base = s["last_run"] or s["created"]
            try:
                due = next_run(s["spec"], datetime.fromtimestamp(base, tz), tz).timestamp()
            except SpecError:
                continue
            if due > now:
                continue
            self.store.update_schedule(s["id"], last_run=now)
            if not s["spec"].lower().startswith("every") and now - due > GRACE:
                log.info("schedule %s missed its slot; skipping", s["id"])
                continue
            fired.append(s["id"])
            try:
                self.submit(s["job"], s["params"])
            except Exception:
                log.exception("schedule %s (%s) failed", s["id"], s["job"])
        return fired
