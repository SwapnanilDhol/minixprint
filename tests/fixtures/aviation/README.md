# Aviation fixtures

Captured 2026-10-12 from the Pi (`swap-pi`) and aviationweather.gov unless marked synthetic.

| File | Origin |
|---|---|
| `awc_metar_vomm.json`, `awc_taf_vomm.json` | **real** — aviationweather.gov `?ids=VOMM&format=json` |
| `bot_metar.json`, `bot_state.json` (coverage/flight_events trimmed), `bot_routes_recent.json` (first 10 items) | **real** — aviation bot on :8070 |
| `aircraft_empty_real.json`, `bot_aircraft_empty_real.json` | **real** — the sky was empty at capture time (night, 0 aircraft) |
| `aircraft.json` | **synthetic** — dump1090-fa schema, 12 made-up aircraft around Chennai (one on the ground, one without position) |
| `bot_aircraft.json` | **synthetic** — enrichment for three of those hexes. The real endpoint returned an empty list, so the per-contact field names are a best guess; `norm_aircraft` accepts aliases |
| `bot_runways_summary.json` | **synthetic** — the real response had no active runway interval (decoder idle). Timeline entries follow the real `timeline` shape with `runway` set |

`tests/test_jobs_aviation.py` uses `now = 1791813446.6` (the capture time) so ages are stable.
