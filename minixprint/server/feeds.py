"""Feed manager: polls every enabled feed on its interval and enqueues new items to print.

State lives in the ``feeds`` table (cursor, counters, last error), so an enabled feed
resumes after a restart exactly where it left off. One thread polls all feeds; a poll
never raises out of the loop, errors are recorded on the feed row. See docs/FEEDS.md.
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .. import feeds as kinds
from ..jobs import JobContext
from .queue import PrintQueue
from .store import Store

log = logging.getLogger("minixprint.feeds")

TICK = 1.0
MIN_INTERVAL_S = 5
SOURCE_BACKOFF_S = 60   # extra wait after a failed poll, capped at the interval anyway


class FeedError(ValueError):
    pass


class FeedManager:
    def __init__(self, store: Store, queue: PrintQueue, settings: Callable[[], Dict[str, Any]]):
        self.store, self.queue, self._settings = store, queue, settings
        self._lock = threading.RLock()       # one poll at a time (loop vs. "poll now")
        self._stop = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="feeds", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("feed tick failed")
            self._stop.wait(TICK)

    def tick(self, now: Optional[float] = None) -> List[int]:
        """Poll every enabled feed that is due; returns the ids polled."""
        now = time.time() if now is None else now
        done = []
        for f in self.store.feeds():
            if f["enabled"] and (f["last_poll"] is None or now - f["last_poll"] >= f["interval_s"]):
                self.poll(f["id"])
                done.append(f["id"])
            if self._stop.is_set():
                break
        return done

    # --- CRUD --------------------------------------------------------------
    def ctx(self) -> JobContext:
        return JobContext(settings=self._settings())

    def create(self, kind: str, params: Optional[dict], interval_s: Optional[int] = None,
               enabled: bool = False) -> Dict[str, Any]:
        try:
            mod = kinds.get(kind)
            clean = kinds.validate(mod, params)
        except KeyError as e:
            raise FeedError(str(e.args[0]))
        except ValueError as e:
            raise FeedError(str(e))
        interval = int(interval_s or mod.DEFAULT_INTERVAL_S)
        if interval < MIN_INTERVAL_S:
            raise FeedError("interval_s must be at least %d" % MIN_INTERVAL_S)
        return self.store.add_feed(kind, clean, interval, enabled)

    def view(self, f: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in f.items() if k != "cursor"}

    # --- polling -----------------------------------------------------------
    def poll(self, fid: int) -> Optional[Dict[str, Any]]:
        """Poll one feed now, enqueue what is new, persist. Never raises."""
        with self._lock:
            f = self.store.feed(fid)
            if not f:
                return None
            now = time.time()
            error = None  # type: Optional[str]
            printed, last_ts, cursor = 0, f["last_item_ts"], f["cursor"]
            try:
                mod = kinds.get(f["kind"])
                ctx = self.ctx()
                items, cursor = mod.poll(f["params"], f["cursor"], ctx)
                for item in items:
                    try:
                        img = mod.render(item, f["params"], ctx)
                        job = self.queue.submit("feed:" + f["kind"], img, self._summary(f, item), "feed",
                                                self._settings()["density"],
                                                dedupe=dedupe_key(fid, item["key"]))
                        if job.get("status") != "skipped":
                            printed += 1
                    except Exception as e:  # one bad item must not stall the cursor
                        error = "%s: %s" % (type(e).__name__, e)
                        log.exception("feed %s item %s failed", fid, item.get("key"))
                    last_ts = item.get("ts") or now
            except Exception as e:
                error = "%s: %s" % (type(e).__name__, e)
                log.warning("feed %s poll failed: %s", fid, error)
            # the row may have been deleted while polling
            if self.store.feed(fid):
                self.store.update_feed(fid, cursor=cursor, last_poll=now, last_item_ts=last_ts,
                                       printed=f["printed"] + printed, error=error)
            return self.store.feed(fid)

    @staticmethod
    def _summary(f: Dict[str, Any], item: Dict[str, Any]) -> str:
        who = f["params"].get("station") or item.get("flight") or ""
        return ("%s %s" % (f["kind"], who)).strip()

    def preview(self, fid: int):
        """Render the latest item without printing or touching the cursor; None if nothing."""
        f = self.store.feed(fid)
        if not f:
            raise KeyError(fid)
        mod = kinds.get(f["kind"])
        ctx = self.ctx()
        items, _ = mod.poll(f["params"], None, ctx)
        return mod.render(items[-1], f["params"], ctx) if items else None


def dedupe_key(fid: int, item_key: Any) -> str:
    return "feed:%s:%s" % (fid, item_key)
