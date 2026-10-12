"""UDP listener for acarsdec / dumpvdl2 JSON, shared by every ``acars`` feed using the same port.

acarsdec (``--output json:udp:host=127.0.0.1,port=N``) sends one flat JSON object per
datagram; dumpvdl2 wraps ACARS under ``vdl2.avlc.acars``. Datagrams may also hold several
newline-separated records. Parsed messages go into a small ring buffer with ids that grow
with wall-clock milliseconds, so a feed cursor stays valid across server restarts and several
feeds can read the same buffer without draining it. Not a feed kind (no ``KIND``).
"""
import collections
import json
import logging
import socket
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("minixprint.feeds.acars_udp")

DEFAULT_PORT = 5570
BUFFER = 500
HOST = "127.0.0.1"
_LIBACARS_KEYS = ("arinc622", "adsc", "cpdlc", "miam", "media-adv", "ohma")


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _s(v: Any) -> Optional[str]:
    v = None if v is None else str(v).strip()
    return v or None


def parse_record(rec: Any) -> Optional[Dict[str, Any]]:
    """Normalise one acarsdec or dumpvdl2 record to the bot's message shape; None if not ACARS."""
    if not isinstance(rec, dict):
        return None
    if isinstance(rec.get("vdl2"), dict):
        v = rec["vdl2"]
        acars = (v.get("avlc") or {}).get("acars")
        if not isinstance(acars, dict):
            return None
        t = v.get("t") or {}
        freq = _f(v.get("freq"))
        lib = {k: acars[k] for k in _LIBACARS_KEYS if isinstance(acars.get(k), dict)}
        src = (v.get("avlc") or {}).get("src") or {}
        return {
            "ts": (_f(t.get("sec")) or time.time()) + (_f(t.get("usec")) or 0) / 1e6,
            "link": "vdl2",
            "icao": _s(src.get("addr")) if src.get("type") == "Aircraft" else None,
            "registration": _s(acars.get("reg")).lstrip(".") if _s(acars.get("reg")) else None,
            "callsign": _s(acars.get("flight")),
            "label": _s(acars.get("label")), "sublabel": _s(acars.get("sublabel")),
            "freq_mhz": None if freq is None else freq / 1e6 if freq > 1e6 else freq,
            "level_db": _f(v.get("sig_level")),
            "text": acars.get("msg_text") or "", "libacars": lib or None,
            "message_no": _s(acars.get("msg_num")),
        }
    if "text" not in rec and "libacars" not in rec and "label" not in rec:
        return None
    lib = rec.get("libacars")
    if isinstance(lib, str):
        try:
            lib = json.loads(lib)
        except ValueError:
            lib = None
    reg = _s(rec.get("tail"))
    return {
        "ts": _f(rec.get("timestamp")) or time.time(),
        "link": "acars",
        "icao": None,
        "registration": reg.lstrip(".") if reg else None,
        "callsign": _s(rec.get("flight")),
        "label": _s(rec.get("label")), "sublabel": _s(rec.get("sublabel")),
        "freq_mhz": _f(rec.get("freq")),
        "level_db": _f(rec.get("level")),
        "text": rec.get("text") or "",
        "libacars": lib if isinstance(lib, dict) and lib else None,
        "message_no": _s(rec.get("msgno")),
    }


def parse_datagram(data: bytes) -> List[Dict[str, Any]]:
    out = []
    text = data.decode("utf-8", "replace").strip()
    try:  # a single (possibly pretty-printed) object
        msg = parse_record(json.loads(text))
        return [msg] if msg else []
    except ValueError:
        pass
    for chunk in text.splitlines():
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            msg = parse_record(json.loads(chunk))
        except ValueError:
            continue
        if msg:
            out.append(msg)
    return out


class Listener:
    """One bound socket + reader thread + ring buffer for a port."""

    def __init__(self, port: int, host: str = HOST):
        self.port, self.host = port, host
        self.buffer = collections.deque(maxlen=BUFFER)  # type: Deque[Dict[str, Any]]
        self.seen_ever = False
        self._last_id = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)
        self._sock.bind((host, port))
        self.port = self._sock.getsockname()[1]  # resolves port 0
        self._thread = threading.Thread(target=self._run, name="acars-udp-%d" % self.port, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            for msg in parse_datagram(data):
                self.add(msg)

    def add(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._last_id = max(self._last_id + 1, int(time.time() * 1000))
            msg["id"] = self._last_id
            self.buffer.append(msg)
            self.seen_ever = True
        return msg

    def since(self, cursor: Optional[int]) -> List[Dict[str, Any]]:
        with self._lock:
            return [m for m in self.buffer if cursor is None or m["id"] > cursor]

    def latest_id(self) -> Optional[int]:
        with self._lock:
            return self._last_id or None

    def close(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(1)


_listeners = {}  # type: Dict[int, Listener]
_reg_lock = threading.Lock()


def get_listener(port: int) -> Listener:
    """The shared listener for ``port``, bound on first use. Raises RuntimeError if it can't bind."""
    with _reg_lock:
        lst = _listeners.get(port)
        if lst is None:
            try:
                lst = Listener(port)
            except OSError as e:
                raise RuntimeError("cannot listen for acarsdec on UDP %s:%s: %s" % (HOST, port, e))
            _listeners[port] = lst
        return lst


def traffic_seen(port: int = DEFAULT_PORT) -> bool:
    """True once any datagram with an ACARS record arrived on ``port`` in this process."""
    with _reg_lock:
        lst = _listeners.get(port)
    return bool(lst and lst.seen_ever)


def close_all() -> None:
    with _reg_lock:
        items = list(_listeners.values())
        _listeners.clear()
    for lst in items:
        lst.close()
