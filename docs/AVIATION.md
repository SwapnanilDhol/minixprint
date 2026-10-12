# Aviation integration

The Pi (`swap-pi`) is an aviation receiver station. This doc
records what's there (inspected 2026-10-12) and how the printer plugs into it.

## What runs on the Pi

| Thing | Where | Notes |
|---|---|---|
| `dump1090-fa` | systemd, RTL-SDR `0bda:2838` | writes `/run/dump1090-fa/aircraft.json` every second (location in `receiver.json`) |
| **aviation_bot** | `~/aviation_bot` (github.com/SwapnanilDhol/aviation_bot), `aviation-bot.service`, `python3 main.py` | Telegram bot + web dashboard on **:8070**; SQLite store; home airport **VOMM / MAA** (Chennai) |
| ACARS Hub | Docker `acarshub`, web :8081 | ACARS / VDL2 via `acarsdec`, `dumpvdl2`, UDP relay 5550→5551,5560 |
| Icecast | :8888 | ATC audio stream, `/radio` on tailscale serve |
| CUPS | :631 | already running — virtual-printer backend is easy here |
| Tailscale serve | `https://swap-pi.<tailnet>.ts.net` | `/` → 127.0.0.1:8070 (bot), `/radio` → 8888. **The print server will take `/print` → 8090.** |

Bluetooth controller present (`88:A2:9E:A9:32:52`); Python 3.13.5; Pillow 11.1; 8 GB RAM.

## Bot data we can print from

Read-only HTTP on `http://127.0.0.1:8070` (bot's `web_dashboard.py`):

| Endpoint | Content |
|---|---|
| `/api/state` | `bot.get_web_state()` — mode, counters, recent contacts |
| `/api/aircraft` | live enriched contacts (registration, type, route, distance) |
| `/api/metar?station=VOMM` | cached METAR (bot's `metar.py`) |
| `/api/runways/summary`, `/api/runways/history` | active runway, switch history with wind at the time |
| `/api/routes/recent`, `/api/routes/patterns` | flown routes |
| `/api/messages` | ACARS/VDL messages |
| `/api/health` | RTL + service health |

Raw: `/run/dump1090-fa/aircraft.json` (fields: hex, flight, alt_baro, gs, track, lat, lon,
category, squawk, rssi).

External: `https://aviationweather.gov/api/data/metar?ids=VOMM&format=json` and
`.../taf?ids=VOMM&format=json` — 100 req/min, set a User-Agent, no browser CORS.

Bot internals worth mirroring (not importing — different process):
- `alerts.AlertEngine.evaluate(contact)` → `Alert(priority, reasons, contact)`; reasons include
  watchlist hits (`/watch` by reg/type/hex/callsign), military, emergency squawks
  (`config.EMERGENCY_SQUAWKS`), records (farthest/highest/best signal), overhead passes.
- `digest.build_digest(store)` — evening summary (contacts, airframes, messages, new
  airframes, farthest). `weekly_report.build_weekly_report(store)` — 7-day station report.
- `bot._notify_runway_change`, `_notify_flight_event` (go-arounds, holds, formations),
  `_notify_tropo` (ducting) — all currently go to Telegram via `telegram.send_telegram`.

## Printer-side jobs (`minixprint/jobs/aviation.py`)

All jobs pull from the bot API / aircraft.json / aviationweather.gov and render with
`minixprint.render`. Each is runnable on demand (`POST /api/jobs/<name>/run`), from the
dashboard button, or on a schedule.

| Job | Output (384 px wide) |
|---|---|
| `aviation.overhead` | **Boarding-pass card** for one aircraft: big callsign, reg + type, route (origin→dest with IATA), alt/speed/track, distance + bearing from home, a QR to the bot dashboard contact page or FR24. Perforation-style dashed rule. |
| `aviation.metar` | METAR + TAF strip for VOMM (configurable list): decoded wind/vis/clouds/QNH in big type, raw text in mono below, flight-category badge (VFR/MVFR/IFR/LIFR). |
| `aviation.runway` | Active runway with a compass rose glyph, wind arrow, time since last switch. |
| `aviation.digest` | Evening digest / weekly report in receipt layout (counts table, "new to the logbook" list, farthest contact). |
| `aviation.now` | "What's overhead right now": top N aircraft by distance in a table. |

## Bot → printer push (the fun part)

Add a tiny, optional notifier in the bot (separate PR in the aviation_bot repo):
when an `Alert` has priority ≥ configured threshold (military, emergency squawk, watchlist,
new record) it `POST`s the `contact` dict to
`http://127.0.0.1:8090/api/jobs/aviation.overhead/run`. Also hook `_notify_runway_change`
→ `aviation.runway`, and the digest/weekly timers → `aviation.digest`. All fire-and-forget
with a 2 s timeout so the bot never blocks on the printer. Env flag
`AVIATION_BOT_PRINTER_URL` enables it; unset = no-op.

Dedup/cooldown lives on the printer side too (same hex within 30 min → skip) so a chatty
bot can't drain a paper roll.

## Known issue in the bot (not ours)

`aviation-bot.service` failed at the 2026-10-12 boot: `TimeoutError: timed out waiting for
store commit` from `runway_archive.recover_intervals` during `AviationBot.__init__`,
10 s after boot with load average 5.6. The unit has `Restart=no`, so it stays down until
started by hand. Likely fix: `Restart=on-failure` + a longer `ExecStartPre` sleep or a
bigger store commit timeout during recovery.

## Jobs

Implemented in `minixprint/jobs/aviation.py` (drawing) and `minixprint/jobs/_aviation_data.py`
(fetching, parsing, haversine/bearing, flight category). All HTTP goes through `ctx.http`
with a 5 s timeout; any failure degrades to a "no data"/"unknown" card instead of raising.
Samples are rendered from `tests/fixtures/aviation/` by `scripts/make_aviation_samples.py`
into `docs/samples/aviation_*.png` (fixture provenance: `tests/fixtures/aviation/README.md`).

Settings used: `home_lat`, `home_lon`, `home_airport`, `airports`, `aviation_bot_url`,
`aircraft_json` (a file path, or an http(s) URL when printing from a machine that isn't the
Pi), `timezone`.

### `aviation.overhead` — boarding-pass card
Params (all optional):
- `contact` — dict as the bot posts it: `hex`, `flight`/`callsign`, `registration`,
  `type`/`type_code`, `type_name`, `origin`/`dest` (IATA), `origin_city`/`dest_city`,
  `alt_baro`, `gs`, `track`, `lat`, `lon`, `squawk`, `is_military`, `reasons` (list).
  No network is used when `contact` is given. Missing fields just drop their line.
- `hex` — look the aircraft up in aircraft.json (enriched from the bot's `/api/aircraft`).
- neither — the closest aircraft with a position right now; "NOTHING OVERHEAD" if none.

Layout: one inverted badge per reason (`MILITARY` is added from `is_military`; squawk
7500/7600/7700 adds `EMERGENCY <squawk>`), callsign (40 px bold), `REG · type`, `MAA → DXB`
with cities, ALT / GS / TRK columns (FL above 18 000 ft), distance + 16-point bearing from
home, time, dashed tear line, QR to `https://globe.adsbexchange.com/?icao=<hex>`.

### `aviation.metar` — decoded METAR + raw + TAF
Params: `stations` (list or "VOMM VIDP"; default `settings.airports`).
Source: `aviationweather.gov/api/data/metar` and `/taf` (`format=json`); METAR falls back to the
bot's `/api/metar?station=`. A failed fetch gives a "NO DATA" card for that station; a report
older than 3 h gets a `STALE · Nh OLD` badge but is still shown. TAF has no fallback.

Flight category uses the **US FAA rules** (the same thresholds aviationweather.gov's `fltCat`
applies; India doesn't define its own). The worse of visibility and ceiling wins; ceiling is the
lowest BKN/OVC/VV layer:

| Category | Visibility | Ceiling |
|---|---|---|
| LIFR | < 1 SM | < 500 ft |
| IFR | 1 to < 3 SM | 500 to < 1000 ft |
| MVFR | 3 to 5 SM | 1000 to 3000 ft |
| VFR | > 5 SM | > 3000 ft or none |

The feed's own `fltCat` is used when present; `flight_category()` computes it otherwise.

### `aviation.runway` — active runway + rose
No params. Source: bot `/api/runways/summary` (queried for the last 36 h with ISO-8601
`start`/`end`, which the endpoint requires) — its `timeline` entries with a `runway` give the
current runway, when it started, and the number of switches since local midnight. Falls back to
the `runway` block in `/api/state` (flagged `LAST KNOWN` when the decoder has no live fix).
Wind comes from the METAR. The 96 px rose shows N, the runway line (heading ≈ runway number
× 10, not magnetic-corrected) and a wind arrow; head/tail and crosswind components are listed.
Bot down → "RUNWAY UNKNOWN".

### `aviation.now` — traffic table
Params: `limit` (1–12, default 12). Source: `aircraft.json` (+ type/reg from the bot). Columns:
callsign, type, alt, km, bearing, sorted by distance. The header shows the count and msg/s.
aircraft.json only carries a running `messages` total, so msg/s is the delta against the
previous reading in the same process; on the first call it shows the total instead.

### `aviation.digest` — receipt summary
Params: `kind` = `daily` (default) | `weekly`. Source: bot `/api/state` (`logbook`: airframes,
sightings, messages, farthest, highest — all-time totals) and `/api/routes/recent` filtered to
the last 24 h / 7 days (flown-route count, distinct airframes, top routes, recent airframes).
The bot has no "new airframes" list over HTTP, so the recent-airframes list stands in for it.
Bot down → what aircraft.json says right now (tracked, farthest, highest, message total).
