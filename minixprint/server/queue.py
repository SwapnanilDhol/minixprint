"""Print queue: one worker thread owns the printer; every job is archived as a PNG."""
import logging
import queue as _queue
import threading
import time
from typing import Any, Callable, Dict, Optional

from ..printer import MiniX, connect
from ..transport import TransportError
from .store import Store

log = logging.getLogger("minixprint.queue")

DEDUPE_WINDOW = 30 * 60
INFO_TTL = 30.0       # seconds between info/battery refreshes
STATUS_TTL = 5.0      # seconds between status-flag refreshes (idle only)
RECONNECT_MIN = 2.0
RECONNECT_MAX = 30.0


class PrintQueue:
    def __init__(self, store: Store, settings: Callable[[], Dict[str, Any]], fake: bool = False,
                 connect_fn: Optional[Callable[[], MiniX]] = None):
        self.store = store
        self._settings = settings
        self.forced_fake = fake
        self._connect_fn = connect_fn or (lambda: connect(prefer=self._settings().get("transport", "auto")))
        self._q = _queue.Queue()  # type: _queue.Queue
        self._printer = None  # type: Optional[MiniX]
        self._thread = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._backoff = RECONNECT_MIN
        self._next_try = 0.0
        self._lost = False  # had a printer and lost it: jobs wait instead of faking
        self._cache = {"info": None, "battery": None, "flags": None, "status_byte": None,
                       "info_ts": 0.0, "status_ts": 0.0, "error": None}  # type: Dict[str, Any]
        self._cache_lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self.store.fail_interrupted()
        self._thread = threading.Thread(target=self._run, name="print-worker", daemon=True)
        self._thread.start()
        self._ready.wait(15)

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread:
            self._thread.join(5)
        if self._printer:
            try:
                self._printer.close()
            except Exception:  # pragma: no cover
                pass

    @property
    def fake(self) -> bool:
        return self.forced_fake or (self._printer is None and not self._lost)

    # --- producer side -----------------------------------------------------
    def submit(self, kind: str, image, summary: str, user: str = "local", density: int = 2,
               dedupe: Optional[str] = None) -> Dict[str, Any]:
        """Archive and enqueue. Returns the job row; status 'skipped' on a dedupe hit."""
        if dedupe:
            hit = self.store.recent_dedupe(dedupe, time.time() - DEDUPE_WINDOW)
            if hit:
                log.info("dedupe %r: skipping (job %s)", dedupe, hit["id"])
                return dict(hit, status="skipped", skipped_of=hit["id"])
        job_id = self.store.add_job(kind, summary, user, image.height if image is not None else 0,
                                    dedupe=dedupe)
        if image is not None:
            image.save(self.store.png_path(job_id))
        self._q.put({"id": job_id, "kind": kind, "density": density, "image": image})
        return self.store.job(job_id)

    def submit_feed(self, dots: int, user: str = "local") -> Dict[str, Any]:
        job_id = self.store.add_job("feed", "feed %d dots" % dots, user, 0)
        self._q.put({"id": job_id, "kind": "feed", "dots": dots})
        return self.store.job(job_id)

    def record_failure(self, kind: str, summary: str, user: str, error: str) -> int:
        return self.store.add_job(kind, summary, user, 0, status="failed", error=error)

    # --- status ------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._cache_lock:
            c = dict(self._cache)
        hist = self.store.history(1)
        return {
            "fake": self.fake,
            "connected": self._printer is not None,
            "transport": type(self._printer.t).__name__.replace("Transport", "").lower()
            if self._printer else None,
            "info": c["info"], "battery": c["battery"], "flags": c["flags"],
            "status_byte": c["status_byte"], "error": c["error"],
            "queue_depth": self.store.depth(),
            "last_job": hist[0] if hist else None,
        }

    # --- worker ------------------------------------------------------------
    def _run(self) -> None:
        try:
            if not self.forced_fake:
                self._connect()
        except Exception:  # pragma: no cover
            log.exception("initial connect crashed")
        self._ready.set()
        while not self._stop.is_set():
            try:
                if self._lost and not self.forced_fake:
                    # printer went away: hold queued jobs until it is back
                    self._idle()
                    self._stop.wait(0.5)
                    continue
                try:
                    item = self._q.get(timeout=1.0)
                except _queue.Empty:
                    self._idle()
                    continue
                if item is None:
                    break
                self._process(item)
            except Exception:
                log.exception("worker loop error")
                self._stop.wait(1.0)

    def _connect(self) -> bool:
        now = time.time()
        try:
            self._printer = self._connect_fn()
            self._backoff = RECONNECT_MIN
            self._lost = False
            log.info("printer connected")
            self._refresh(force=True)
            return True
        except Exception as e:
            self._printer = None
            self._next_try = now + self._backoff
            self._backoff = min(self._backoff * 2, RECONNECT_MAX)
            with self._cache_lock:
                self._cache["error"] = str(e)
            log.warning("no printer (%s); %s, retrying in %.0fs", e,
                        "waiting" if self._lost else "fake mode", self._next_try - now)
            return False

    def _drop(self, error: Optional[str] = None) -> None:
        """Printer lost: close the transport, report disconnected, schedule a reconnect."""
        if self._printer:
            try:
                self._printer.close()
            except Exception:
                pass
        self._printer = None
        self._lost = not self.forced_fake
        self._next_try = time.time() + self._backoff
        if error is not None:
            with self._cache_lock:
                self._cache["error"] = error

    def _idle(self) -> None:
        if self.forced_fake:
            return
        if self._printer is None:
            if time.time() >= self._next_try:
                self._connect()
        else:
            self._refresh()

    def _refresh(self, force: bool = False) -> None:
        p = self._printer
        if p is None:
            return
        now = time.time()
        try:
            with self._cache_lock:
                info_stale = force or now - self._cache["info_ts"] > INFO_TTL
                status_stale = force or now - self._cache["status_ts"] > STATUS_TTL
            if info_stale:
                info, bat = p.info(), p.battery()
                with self._cache_lock:
                    self._cache.update(info=info, battery=bat, info_ts=now, error=None)
            if status_stale:
                st = p.status()
                with self._cache_lock:
                    self._cache.update(status_byte=st[0] if st else None,
                                       flags=st[1] if st else None, status_ts=now)
        except Exception as e:  # OSError/TransportError/ValueError on a closed fd, bleak errors...
            log.warning("status refresh failed: %s", e)
            self._drop("%s: %s" % (type(e).__name__, e))

    def _write(self, item: Dict[str, Any]) -> None:
        if item["kind"] == "feed":
            self._printer.feed(item["dots"])
        else:
            self._printer.print_image(item["image"], item["density"])

    def _process(self, item: Dict[str, Any]) -> None:
        jid = item["id"]
        self.store.set_job(jid, "printing")
        if self.fake:
            log.info("[fake] job %s (%s) archived, not printed", jid, item["kind"])
            self.store.set_job(jid, "done")
            return
        error = None
        try:
            self._write(item)
        except (TransportError, OSError) as e:
            error = "%s: %s" % (type(e).__name__, e)
            log.warning("job %s failed, printer lost: %s", jid, error)
            self._drop(error)
        except Exception as e:
            error = "%s: %s" % (type(e).__name__, e)
            log.exception("job %s failed", jid)
        if error:
            self.store.set_job(jid, "failed", error)
        else:
            self.store.set_job(jid, "done")
            with self._cache_lock:
                self._cache["status_ts"] = 0.0
