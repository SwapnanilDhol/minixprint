# Contributing

Thanks for helping! The most valuable contribution is a **printer report** for a model we haven't
tested: run `minixprint info` and open an issue with the *Printer report* template.

## Dev setup

```bash
git clone https://github.com/SwapnanilDhol/minixprint && cd minixprint
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip              # editable installs of pyproject.toml need pip >= 21.3
pip install -e ".[dev]"         # add ",ble" if you work on the BLE transport
pytest                          # no printer, network or Bluetooth needed
ruff check .
```

Fonts: rendering uses DejaVu (`fonts-dejavu` on Debian/Ubuntu; bundled system fonts on macOS).
Try the server without hardware: `minixprint serve --fake --port 8091`.

## Ground rules

- **Python 3.9 compatible** (the Pi runs whatever Debian ships). No `X | Y` annotations at runtime,
  no `match`, use `typing.Optional`/`List`. CI runs 3.9 and 3.13.
- **No new dependencies without discussion** — open an issue first. The install has to stay easy on
  a Raspberry Pi.
- Match the surrounding style; `ruff check .` must pass (line length 100 for new code).
- Add or update a test for behaviour you change, and a line in `CHANGELOG.md`.
- Keep personal data (serials, MAC addresses, hostnames) out of docs, fixtures and tests.

## Add a job

1. Create `minixprint/jobs/<name>.py` — nothing else to register.
2. Export a `JOBS` mapping of name → `fn(params, ctx) -> PIL.Image` (mode `"1"`, 384 px wide):

```python
from ..render import render_text, rule, stack

def hello(params, ctx):
    """Say hello (the first docstring line is the dashboard tooltip)."""
    return stack(render_text(params.get("name", "world"), size=32, align="center"), rule())

JOBS = {"demo.hello": hello}
```

3. Give every job function a **one-line docstring**; a test requires distinct, non-empty
   descriptions in `GET /api/jobs`.
4. Defaults for every param; network calls get timeouts and degrade instead of raising.
5. Add a test (use fixtures, never the live network) and a sample in `scripts/make_fun_samples.py`;
   document it in [docs/JOBS.md](docs/JOBS.md).

## Add a render block

Blocks are functions returning a mode-`"1"` image exactly `render.WIDTH` px wide, built from
`render_text`, `stack`, `pad`, `rule` and friends in `minixprint/render/`. Put it in a module there,
export it from `minixprint/render/__init__.py`, add it to the "all blocks are 384 px wide" test in
`tests/test_render.py`, and document it in [docs/RENDER.md](docs/RENDER.md). If it needs an
endpoint, add it in `minixprint/server/app.py` (print + preview share one handler) and a CLI
subcommand in `minixprint/cli.py`.

## Add a transport

Subclass `minixprint.transport.Transport` (`open`, `close`, `write`, `read`; optionally
`status_byte`), chunking writes at 128 bytes with ~35 ms gaps. Wire it into `connect()` in
`minixprint/printer.py` and the `--usb/--ble` flags in the CLI. Test it against the fake transport
in `tests/test_printer.py`; hardware specifics belong in [PROTOCOL.md](PROTOCOL.md).

## Pull requests

Small, focused PRs with a description of what you tested (hardware model if relevant). Protocol
discoveries should include the raw bytes you observed.
