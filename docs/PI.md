# Raspberry Pi deployment

Target: `swap-pi` — Raspberry Pi 5, Debian 13 (trixie), Python 3.13.5, user
`swapnanildhol`, reachable as `swap-pi` over Tailscale (SSH key auth already works
from the Mac).

## Layout on the Pi

```
~/minixprint/            rsync of this repo (no git on the Pi; `./deploy/deploy.sh`)
~/minixprint/.venv/      python3 -m venv; pip install -e .
~/.local/share/minixprint/   SQLite history + rendered PNG archive
/etc/systemd/system/minixprint.service
```

## Printer connection

**USB (preferred).** The MiniX enumerates as a CDC-ACM device (`PPS1 LJPrt ComPort`,
VID `3021` PID `6001`) → `/dev/ttyACM0`. It also exposes a USB printer-class interface
that `usblp` may claim; that's harmless, we only use the ACM port.

- Add the user to `dialout` (`sudo usermod -aG dialout swapnanildhol`).
- udev rule for a stable name:
  `SUBSYSTEM=="tty", ATTRS{idVendor}=="3021", ATTRS{idProduct}=="6001", SYMLINK+="minix"`
  → `/dev/minix`.
- The driver's port auto-detect must accept `/dev/ttyACM*` and `/dev/minix` on Linux as
  well as `/dev/cu.usbmodem*` on macOS.
- USB also charges the printer, so it's always at 100 %.

**BLE.** Pi 5 has a BT controller; `pip install bleak` into the venv. The printer only
advertises when USB is unplugged (power-cycle it after unplugging — BLE stays off until
reboot), and only one host can hold the BLE connection, so stop any Mac server first.
BlueZ refuses to connect with `br-connection-profile-unavailable` because the MiniX
advertises as dual-mode (BR/EDR + LE) and BlueZ tries a Classic profile first. Fix: run the
adapter LE-only — in `/etc/bluetooth/main.conf` under `[General]` set
`ControllerMode = le`, `sudo systemctl restart bluetooth`, `bluetoothctl remove <printer addr>`,
restart minixprint. Verified 2026-10-12 on swap-pi. Downside vs USB: battery only (no charging).

## Service

`deploy/minixprint.service`:

```
[Unit]
Description=MiniX thermal print server
After=network-online.target
Wants=network-online.target

[Service]
User=swapnanildhol
WorkingDirectory=/home/swapnanildhol/minixprint
ExecStart=/home/swapnanildhol/minixprint/.venv/bin/minixprint serve --host 127.0.0.1 --port 8090 --root-path /print
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Bind to loopback only; Tailscale is the front door.

## Tailscale

The Pi already serves `/` → :8070 (aviation bot) and `/radio` → :8888. Add a path:

```
sudo tailscale serve --bg --set-path /print http://127.0.0.1:8090
```

→ `https://swap-pi.<tailnet>.ts.net/print/`. Consequences for the app:

- FastAPI must run with `root_path="/print"` so generated links and the OpenAPI docs are
  correct; the dashboard must use relative URLs.
- Tailscale adds `Tailscale-User-Login` / `Tailscale-User-Name` headers; show the name in
  the dashboard and log it with each job. No other auth needed on the tailnet.
- Do **not** enable Funnel (public internet) — a printer that anyone can feed paper into is
  a bad idea.

## What actually happened (2026-10-12)

- `./deploy/deploy.sh` from the Mac: rsync → venv → `pip install -e .` → unit + udev rule
  installed with sudo (passwordless sudo works on the Pi) → `systemctl enable`/`restart` →
  waits for `/api/status`. The user was already in `dialout`.
- Printer is on the Mac, so the Pi reports `"fake": true`. Its `error` field says
  `BLE needs bleak` — the BLE fallback was tried and `bleak` isn't installed on the Pi.
  Harmless in fake mode; `pip install bleak` only if BLE is wanted on the Pi.
- `sudo tailscale serve --bg --set-path /print http://127.0.0.1:8090`; `/` and `/radio`
  were untouched. The Mac is on the tailnet, so `curl https://swap-pi.<tailnet>.ts.net/print/api/status`
  works and `user` shows the Tailscale display name.
- Gotcha: Tailscale serves **`/print` (no slash) with the same page**, so relative
  `style.css`/`app.js` resolved to `/style.css` (the aviation bot). Fixed with a tiny
  redirect script at the top of `index.html`; `/print` now lands on `/print/`.
- Gotcha: `PUT /api/settings` ignored `aircraft_json` / `aviation_bot_url`; they're now
  accepted (defaults already match the Pi: `/run/dump1090-fa/aircraft.json`,
  `http://127.0.0.1:8070`). `aviation.now` printed real aircraft from the Pi's dump1090.
- Observer location (`home_lat`/`home_lon`) is set per machine via `PUT /api/settings` and lives only in the Pi's SQLite, not in git.
- Verified: `fortune`, `aviation.metar`, `aviation.now`, `aviation.runway` all `done`;
  history PNGs are 384 px wide.

## Other Pi niceties

- CUPS is running: install `deploy/cups/minix` backend so `lp -d minix file.pdf` works
  from any tailnet machine that adds the IPP queue.
- The aviation bot lives on the same box, so its printer hook can call
  `http://127.0.0.1:8090` directly (see AVIATION.md).

## Bring-up checklist

1. `git clone` → venv → `pip install -e .` → `minixprint info` with the printer on USB.
2. `minixprint stripes` prints.
3. Install + enable the service; `curl http://127.0.0.1:8090/api/status`.
4. `tailscale serve --set-path /print …`; open the dashboard from the Mac and the iPhone.
5. Print from the iOS Shortcut over the tailnet.
