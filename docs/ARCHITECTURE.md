# Architecture

A print server + web dashboard for the Seznik MiniX (LuckJingle S1) thermal printer,
designed to run on a Raspberry Pi and be reached over Tailscale. Protocol details live
in [../PROTOCOL.md](../PROTOCOL.md).

## Topology

```
 iPhone (Shortcut) ─┐
 Mac (dev, CLI)    ─┼─ tailnet (HTTPS via `tailscale serve`) ─▶ swap-pi : minix server
 aviation bot (Pi) ─┘                                               │
                                                                    ├─ USB serial ──▶ MiniX
                                                                    └─ BLE (fallback)
```

The printer is attached to the Pi (USB preferred: full duplex command channel, charges the
battery; BLE as fallback). One process owns the printer. Everything else — dashboard, CLI,
Shortcuts, the aviation bot — talks HTTP to that process.

## Package layout

Python package name is `minixprint` (avoids clashing with the legacy `minix.py` script).

```
minixprint/
  protocol.py        command bytes, status-bit decoding (single source of truth)
  transport/
    usb.py           /dev/cu.usbmodem* (macOS) / /dev/ttyACM* (Linux)
    ble.py           bleak: service FF00, write FF02, notify FF01/FF03
  printer.py         MiniX class: transport-agnostic (info/status/print_bitmap)
  render/            everything that produces a 384-px-wide 1-bit PIL image
    text.py          wrapped text, fonts, alignment
    markdown.py      headings / lists / rules / bold / code
    receipt.py       data-driven receipts (items, taxes, footer)
    image.py         resize + dither (Floyd–Steinberg, Atkinson), gamma
    codes.py         QR codes, Code128 barcodes
    compose.py       stack blocks vertically into one bitmap
  jobs/              things that *generate* content on demand or on a schedule
    morning.py       calendar / weather / todos slip
    puzzles.py       sudoku, maze
    aviation.py      METAR/TAF strip, aircraft-overhead card (readsb + aviationweather.gov)
    fortune.py
  server/
    app.py           FastAPI; REST under /api, static dashboard at /
    queue.py         single worker thread; SQLite history; rendered PNG archive
    scheduler.py     cron-style schedules for jobs (stored in SQLite)
    static/          dashboard (vanilla HTML/JS, no build step)
  cli.py             `minix` command: text | image | md | receipt | qr | status | pipe (stdin)
  watch.py           folder watcher ("photo booth"): drop a file, it prints
deploy/
  minix.service      systemd unit for the Pi
  tailscale.md       `tailscale serve` setup
  cups/              virtual-printer backend (Linux + macOS)
  ios-shortcut.md    Share-sheet → print
docs/
```

## HTTP API (v1)

| Method | Path | Body | Effect |
|---|---|---|---|
| GET | `/api/status` | — | printer info, battery, status bits, queue depth |
| POST | `/api/print/text` | `{text, size, align, density}` | render + enqueue |
| POST | `/api/print/markdown` | `{markdown}` | |
| POST | `/api/print/receipt` | receipt JSON | |
| POST | `/api/print/image` | multipart file, `?dither=fs` | |
| POST | `/api/print/qr` | `{data, caption}` | |
| POST | `/api/print/raw` | 1-bit PNG, 384 px wide | for external renderers / CUPS backend |
| POST | `/api/jobs/{name}/run` | job params | e.g. `aviation.metar`, `morning` |
| GET/POST/DELETE | `/api/schedules` | cron spec + job | |
| GET | `/api/history` | — | past jobs with PNG thumbnails |
| POST | `/api/preview/*` | same as print | returns PNG, nothing printed |
| POST | `/api/feed` | `{dots}` | |

Every print endpoint has a matching `/api/preview/...` so the dashboard shows exactly
what will come out before committing paper.

## Dashboard

Single page: live printer status (battery, paper, busy), a composer (text / markdown /
receipt / image / QR tabs with live preview), one-click "fun" buttons (aviation card,
METAR strip, sudoku, fortune), schedules editor, and a history strip of thumbnails.
No framework or bundler — plain HTML, CSS and fetch, so it runs from the Pi untouched.

## Aviation integration

The Pi already runs an ADS-B receiver + bot (overhead aircraft, METAR/TAF). Integration is
HTTP both ways:

- The print server reads `readsb`/`dump1090` `aircraft.json` on the Pi and
  `https://aviationweather.gov/api/data/{metar,taf}?ids=XXXX&format=json`
  (100 req/min limit, custom User-Agent required).
- The bot can `POST /api/jobs/aviation.overhead/run` when it sees something notable
  (rare type, military, heavy, low pass) → a boarding-pass-style card prints.
- Scheduled: morning METAR/TAF strip for home airports.

Hook points, bot API endpoints and the job catalogue are in [AVIATION.md](AVIATION.md);
Pi service, USB and `tailscale serve` details are in [PI.md](PI.md). The server listens on
**127.0.0.1:8090** on the Pi and is published at `/print` (the bot already owns `/`).

## Deployment

- Pi: `python3 -m venv`, `pip install -e .`, systemd unit, `tailscale serve --bg 8080` →
  `https://swap-pi.<tailnet>.ts.net`. Tailscale identity headers can gate writes.
- Mac (dev): same server, printer over USB or BLE, `tailscale serve` works identically.

## Phases

0. Protocol + USB driver (done), BLE transport (in progress).
1. Package restructure, `render/`, CLI with stdin pipe.
2. Server, queue, history, dashboard, previews.
3. Pi bring-up: USB on Pi, systemd, tailscale serve.
4. Jobs: aviation, morning slip, puzzles, fortune; scheduler.
5. Shortcuts doc, CUPS virtual printer, folder watcher.
6. Open-source polish: README, screenshots, CONTRIBUTING, CI lint.
