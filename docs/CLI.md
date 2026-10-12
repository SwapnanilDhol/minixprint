# minixprint CLI

Install: `pip install -e .` (add `.[ble]` for Bluetooth). Entry point: `minixprint`
(`python -m minixprint.cli` and the deprecated `minix.py` shim do the same).

```
minixprint [--usb|--ble] [--port PATH] [--name PREFIX] [--density 0|1|2] [-v] COMMAND ...
```

| Flag | Meaning |
|---|---|
| `--usb` / `--ble` | force a transport. Default: USB if `/dev/minix`, `/dev/ttyACM*` or `/dev/cu.usbmodem*` exists (in that order), else BLE. BLE needs the printer unplugged from USB. |
| `--port PATH` | explicit USB serial port |
| `--name PREFIX` | BLE advertised-name prefix (default `Seznik MiniX`) |
| `--density N` | 0 light, 1 normal, 2 dark (default 2) |
| `-v` | log every byte to stderr |

Every print command also takes `--out x.png` (write a preview PNG, don't touch the printer)
and `--feed DOTS` (paper feed after printing, default 100).

## Commands

| Command | Example |
|---|---|
| `info` — name, MAC, versions, serial, model, battery | `minixprint info` |
| `status` — `(byte, [flags])`, e.g. `(0, ['ready'])` | `minixprint status` |
| `text "…"` — `--size --align left\|center\|right --bold --mono`; `-` reads stdin | `minixprint text "Hello" --align center --bold` |
| `pipe` — stdin as text (same text options) | `cal \| minixprint pipe --mono --size 20` |
| `md FILE\|-` — Markdown | `minixprint md notes.md` |
| `receipt FILE.json` — see docs/RENDER.md for the schema | `minixprint receipt order.json --out r.png` |
| `image FILE [--dither fs\|atkinson\|none]` | `minixprint image photo.jpg --dither atkinson` |
| `qr DATA [--caption TEXT]` | `minixprint qr https://example.com --caption site` |
| `feed [dots]` — default 80 | `minixprint feed 200` |
| `stripes` — test pattern | `minixprint stripes` |

Exit status is 1 (message on stderr) if the printer can't be reached or an argument is invalid.

## Watching a folder

| Command | Example |
|---|---|
| `watch DIR [--server URL] [--dither fs\|atkinson\|none] [--delete \| --move-to DIR] [--once] [--interval S]` — print every new image, PDF, `.txt` and `.md` that appears in `DIR` through the HTTP server (default `http://127.0.0.1:8090`; dither default `atkinson`) | `minixprint watch ~/print-inbox --move-to ~/print-inbox/printed` |

Unlike the commands above it talks to a running `minixprint serve`, not the printer. See
[WATCH.md](WATCH.md).

## Feeds

Manage live feeds on a running server (docs/FEEDS.md); `--server URL` defaults to `http://127.0.0.1:8090`.

```
minixprint feeds                      # list
minixprint feeds kinds
minixprint feeds add metar VOMM       # add and start; --interval S, --paused
minixprint feeds add acars skip_labels=Q0,_d source=bot
minixprint feeds start|stop|poll|rm ID
```
