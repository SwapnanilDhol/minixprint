"""Job registry.

A *job* generates something printable on demand or on a schedule: a METAR strip, a
boarding-pass card for an aircraft overhead, the morning slip, a sudoku.

Every module in this package declares a module-level ``JOBS`` mapping::

    JOBS = {"aviation.metar": metar_job}

    def metar_job(params: dict, ctx: JobContext) -> PIL.Image.Image:
        ...

The callable must return a Pillow mode-"1" image exactly ``minixprint.render.WIDTH`` px
wide (use the ``minixprint.render`` helpers). ``params`` comes straight from the HTTP
request / schedule and may be empty; every job must have sensible defaults.
``discover()`` imports each module and merges the mappings, so adding a job means adding
a module — nothing else to register.
"""
import importlib
import pkgutil
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover
    import PIL.Image

try:  # requests is a declared dependency, but keep import-time failures soft
    import requests
except ImportError:  # pragma: no cover
    requests = None

USER_AGENT = "minixprint/0.1 (+https://github.com/SwapnanilDhol/minixprint)"


@dataclass
class JobContext:
    """What a job may need beyond its params. Built once by the server/CLI."""

    settings: Dict[str, object] = field(default_factory=dict)
    http: Optional[object] = None  # requests.Session with the User-Agent set

    def __post_init__(self):
        if self.http is None and requests is not None:
            self.http = requests.Session()
            self.http.headers["User-Agent"] = USER_AGENT

    def now(self) -> float:
        return time.time()

    def setting(self, key: str, default=None):
        return self.settings.get(key, default)


DEFAULT_SETTINGS = {
    # Home station default: Chennai airport (VOMM). Set your real location via settings.
    "home_lat": 12.9941,
    "home_lon": 80.1709,
    "home_airport": "VOMM",
    "airports": ["VOMM"],
    "aviation_bot_url": "http://127.0.0.1:8070",
    "aircraft_json": "/run/dump1090-fa/aircraft.json",
    "timezone": "Asia/Kolkata",
}

JobFn = Callable[[dict, JobContext], "PIL.Image.Image"]


def discover() -> Dict[str, JobFn]:
    """Import every module in this package and collect their JOBS mappings."""
    found: Dict[str, JobFn] = {}
    for mod in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{mod.name}")
        for name, fn in getattr(module, "JOBS", {}).items():
            if name in found:
                raise ValueError(f"duplicate job name {name!r} in {mod.name}")
            found[name] = fn
    return found


def run(name: str, params: Optional[dict] = None, ctx: Optional[JobContext] = None):
    jobs = discover()
    if name not in jobs:
        raise KeyError(f"unknown job {name!r}; available: {sorted(jobs)}")
    return jobs[name](params or {}, ctx or JobContext(settings=dict(DEFAULT_SETTINGS)))
