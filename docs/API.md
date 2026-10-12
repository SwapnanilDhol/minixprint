# HTTP API

`minixprint serve` (default `127.0.0.1:8090`) exposes a JSON/PNG API under `/api`. Examples use
`H=http://127.0.0.1:8090`; behind Tailscale replace it with `https://swap-pi.<tailnet>.ts.net/print`.
Errors are `{"detail": "..."}` with a conventional status (404 unknown job/schedule, 413 over
`max_height_px`, 415 unreadable image, 422 bad parameters).

Every print job records the submitter: `Tailscale-User-Name`, else `Tailscale-User-Login`, else `local`.

All `POST /api/print/...` endpoints enqueue and return
`{"id": 7, "status": "queued", "height_px": 95, "queue_depth": 1, "skipped_of": null}`.
Each has a twin `POST /api/preview/...` taking the same input and returning `image/png`
(nothing is printed or recorded). Optional `density` (0–2) overrides the default setting.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/status` | printer info, battery, flags, queue depth, last job, `fake` |
| POST | `/api/print/text` | `{text, size=28, align=left, bold, mono, density}` |
| POST | `/api/print/markdown` | `{markdown, size=24}` |
| POST | `/api/print/receipt` | receipt JSON ([RENDER.md](RENDER.md)); `?density=` |
| POST | `/api/print/qr` | `{data, caption}` |
| POST | `/api/print/image` | multipart `file`; `?dither=fs\|atkinson\|none&gamma=1.0&invert=false` |
| POST | `/api/print/raw` | multipart `file`: PNG exactly 384 px wide (thresholded to 1-bit) |
| GET | `/api/jobs` | `[{name, description}]` |
| POST | `/api/jobs/{name}/run` | JSON params; `?dedupe=KEY` skips if KEY printed in the last 30 min |
| POST | `/api/feed` | `{dots}` |
| GET | `/api/history?limit=30` | newest first |
| GET | `/api/history/{id}.png` | the archived bitmap |
| GET/POST | `/api/schedules` | |
| PATCH/DELETE | `/api/schedules/{id}` | |
| GET/PUT | `/api/settings` | |

Previews: `/api/preview/{text,markdown,receipt,qr,image,raw}` and `/api/preview/jobs/{name}`.

```bash
curl $H/api/status
```
```json
{"fake": false, "connected": true, "transport": "usb", "battery": 100, "flags": ["ready"],
 "info": {"name": "...", "firmware": "V1.9.9"}, "queue_depth": 0, "last_job": null,
 "user": "local", "timezone": "Asia/Kolkata"}
```
Printer info/battery are cached for 30 s, flags for 5 s (refreshed by the worker while idle).

## Print

```bash
curl -X POST $H/api/print/text -H 'content-type: application/json' \
  -d '{"text":"Hello!","size":32,"align":"center","bold":true}'

curl -X POST $H/api/print/markdown -H 'content-type: application/json' \
  -d '{"markdown":"# Shopping\n- eggs\n- tea"}'

curl -X POST $H/api/print/receipt -H 'content-type: application/json' \
  -d '{"title":"DOSA & CO.","items":[{"name":"Masala Dosa","qty":2,"price":180}],"taxes":[{"label":"GST","rate":5}],"currency":"INR"}'

curl -X POST $H/api/print/qr -H 'content-type: application/json' \
  -d '{"data":"https://example.com","caption":"scan me"}'

curl -X POST "$H/api/print/image?dither=atkinson&gamma=1.2" -F file=@photo.jpg

curl -X POST $H/api/print/raw -F file=@strip384.png

curl -X POST $H/api/preview/text -H 'content-type: application/json' \
  -d '{"text":"Hello!"}' -o preview.png
```

## Jobs

```bash
curl $H/api/jobs
curl -X POST $H/api/jobs/fortune/run -H 'content-type: application/json' -d '{}'
curl -X POST "$H/api/jobs/aviation.overhead/run?dedupe=A1B2C3" -H 'content-type: application/json' \
  -d '{"hex":"A1B2C3"}'     # second call within 30 min -> {"status":"skipped","skipped_of":12,...}
curl -X POST $H/api/preview/jobs/puzzle.sudoku -H 'content-type: application/json' -d '{}' -o sudoku.png
```
Job functions receive the settings (home airport, timezone, …) in their context. A job that raises
returns 500 (422 for `ValueError`).

## Feed, history

```bash
curl -X POST $H/api/feed -H 'content-type: application/json' -d '{"dots":120}'
curl "$H/api/history?limit=5"
curl $H/api/history/7.png -o job7.png
```
History rows: `{id, ts, kind, summary, user, height_px, status, error}`; `status` is
`queued → printing → done | failed` (`error` holds the text). Jobs left queued when the server
stops are marked `failed: server restarted`.

## Schedules

Spec grammar, evaluated in the configured timezone (default `Asia/Kolkata`):
`daily HH:MM`, `weekly MON,FRI HH:MM`, `every 30m` (or `2h`).

```bash
curl -X POST $H/api/schedules -H 'content-type: application/json' \
  -d '{"spec":"daily 07:30","job":"morning","params":{}}'
curl $H/api/schedules
curl -X PATCH $H/api/schedules/1 -H 'content-type: application/json' -d '{"enabled":false}'
curl -X DELETE $H/api/schedules/1
```
A 30-second ticker runs due schedules (`last_run` persisted). A daily/weekly slot missed by more
than 10 minutes (server was down) is skipped rather than printed late; `every` schedules catch up once.

## Feeds

Long-running watchers that poll a source and print each new item (docs/FEEDS.md).

```bash
curl $H/api/feeds/kinds          # [{kind, description, params: {name: {type, required, default}}, default_interval_s}]
curl -X POST $H/api/feeds -H 'content-type: application/json' \
  -d '{"kind":"metar","params":{"station":"VOMM"},"enabled":true}'   # interval_s optional, enabled defaults false
curl $H/api/feeds                # id, kind, params, interval_s, enabled, last_poll, last_item_ts, printed, error
curl -X POST $H/api/feeds/1/start    # also /stop
curl -X POST $H/api/feeds/1/poll     # poll now, returns the updated feed
curl $H/api/feeds/1/preview -o p.png # latest item rendered, nothing printed, cursor untouched
curl -X DELETE $H/api/feeds/1
```
Bad kind/params/interval (< 5 s) → 422; unknown id → 404; preview: 404 if there is nothing yet,
502 if the source is unreachable. Printed jobs appear in history as kind `feed:<kind>`, user `feed`.

## Settings

```bash
curl $H/api/settings
curl -X PUT $H/api/settings -H 'content-type: application/json' \
  -d '{"home_airport":"VOMM","airports":["VOMM","VOBL"],"density":2,"timezone":"Asia/Kolkata","max_height_px":4000}'
```
Partial updates. `max_height_px` (default 4000) is a paper-saving safety cap: any rendered image
taller than that is refused with 413, for previews too.

## Running

```bash
minixprint serve [--host 127.0.0.1] [--port 8090] [--root-path /print] [--fake]
```
`--root-path` (or `MINIXPRINT_ROOT_PATH`) sets FastAPI's `root_path`; it works with proxies that strip
the prefix (Tailscale) and with ones that keep it. Data (SQLite DB + `png/<id>.png`) lives in
`~/.local/share/minixprint/`, override with `MINIXPRINT_DATA_DIR`. With no printer found at startup,
or `--fake`, the queue runs in **fake mode**: jobs are archived and marked done, nothing is printed,
`/api/status` has `"fake": true`. If the printer was absent at boot it is retried with backoff and
the server switches to real printing when it appears; on transport errors mid-job the connection is
re-opened and the job retried once.
