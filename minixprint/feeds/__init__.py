"""Feed kinds: watchers that poll a source and print each new item.

Every module in this package that defines a module-level ``KIND`` is a feed kind::

    KIND = "metar"
    DESCRIPTION = "..."                      # one line, shown in the dashboard
    PARAMS = {"station": {"type": "icao", "required": True}}
    DEFAULT_INTERVAL_S = 300

    def validate(params) -> dict            # optional: normalise + fill defaults, raise ValueError
    def poll(params, cursor, ctx) -> (items, new_cursor)
    def render(item, params, ctx) -> PIL.Image.Image

``poll`` returns only items not seen before, oldest first; each item is a dict with a
unique ``"key"`` (used for the print-queue dedupe key) and ``"ts"`` (unix time, optional).
``cursor`` is any JSON value (None on a brand-new feed) that ``poll`` handed back last
time. ``ctx`` is a ``minixprint.jobs.JobContext``. See docs/FEEDS.md.

PARAMS field ``type`` is one of ``icao``, ``text``, ``int``, ``enum`` (with ``options``)
or ``list`` (list of strings); other keys: ``required``, ``default``, ``label``.
"""
import importlib
import pkgutil
from types import ModuleType
from typing import Any, Dict


def discover() -> Dict[str, ModuleType]:
    """Import every module in this package and collect those that declare KIND."""
    found = {}  # type: Dict[str, ModuleType]
    for mod in pkgutil.iter_modules(__path__):
        module = importlib.import_module("%s.%s" % (__name__, mod.name))
        kind = getattr(module, "KIND", None)
        if kind:
            if kind in found:
                raise ValueError("duplicate feed kind %r in %s" % (kind, mod.name))
            found[kind] = module
    return found


def get(kind: str) -> ModuleType:
    kinds = discover()
    if kind not in kinds:
        raise KeyError("unknown feed kind %r; available: %s" % (kind, sorted(kinds)))
    return kinds[kind]


def validate(module: ModuleType, params: Any) -> Dict[str, Any]:
    """Schema-level check shared by all kinds, then the kind's own ``validate`` if any."""
    params = dict(params or {})
    out = {}  # type: Dict[str, Any]
    for name, spec in module.PARAMS.items():
        v = params.pop(name, None)
        if v is None or v == "":
            if spec.get("required"):
                raise ValueError("param %r is required" % name)
            v = spec.get("default")
        if v is not None:
            out[name] = _coerce(name, spec, v)
    if params:
        raise ValueError("unknown param(s): %s" % ", ".join(sorted(params)))
    fn = getattr(module, "validate", None)
    return fn(out) if fn else out


def _coerce(name: str, spec: Dict[str, Any], v: Any) -> Any:
    t = spec.get("type", "text")
    if t == "icao":
        v = str(v).strip().upper()
        if not (len(v) == 4 and v.isalnum()):
            raise ValueError("param %r must be a 4-character ICAO code" % name)
        return v
    if t == "int":
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ValueError("param %r must be an integer" % name)
    if t == "enum":
        if v not in spec["options"]:
            raise ValueError("param %r must be one of %s" % (name, ", ".join(spec["options"])))
        return v
    if t == "list":
        if isinstance(v, str):
            v = [x for x in v.replace(",", " ").split()]
        if not isinstance(v, (list, tuple)):
            raise ValueError("param %r must be a list" % name)
        return [str(x) for x in v]
    return str(v)
