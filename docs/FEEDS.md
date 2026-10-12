# Feeds

A **feed** is a long-running watcher: it polls a source on an interval and prints every new
item until you stop it. Schedules (docs/API.md) print "something at 07:30"; feeds print
"whenever something new happens".

| Kind | Params | Default interval | Prints |
|---|---|---|---|
| `metar` | `station` (ICAO, required) | 300 s | a compact strip when the station issues a new observation: flight-category badge, decoded wind / vis / weather / clouds / temp / QNH, raw text |
| `acars` | `source` `bot`\|`acarshub` (default `bot`), `skip_labels` (default `Q0, _d, Q1`), `min_text_len` (default 1) | 15 s | a ticket per message: callsign / registration, time, label·sublabel, frequency, text in mono. Messages from the same flight within 20 s are collapsed into one ticket |

`acars` reads `GET <aviation_bot_url>/api/messages` (the aviation bot, setting `aviation_bot_url`).
The bot only decodes ACARS while in its `/acars` mode, so quiet periods are normal: an empty poll
is not an error. `source: acarshub` reads the same message shape from `http://127.0.0.1:8081`; stock ACARS Hub serves its data over a websocket, not that REST
route, so this is only useful behind a compatible shim and otherwise records an error on the feed.

## How it works

* Feeds live in the `feeds` table (id, kind, params, interval_s, enabled, cursor, last_poll,
  last_item_ts, printed, error). Enabled feeds resume after a server restart where they left off.
* One thread (`server/feeds.py`) wakes every second and polls each enabled feed that is due
  (`now - last_poll >= interval_s`). A poll calls the kind's `poll(params, cursor, ctx)`, renders
  each returned item and submits it to the print queue with
  `dedupe="feed:<feed id>:<item key>"` (the queue drops duplicates inside its 30 min window,
  so a lost cursor can't reprint). Then the new cursor, counters and any error are saved.
* Errors (source down, bad data, render failure) are stored in the feed's `error` and shown in
  the dashboard; the feed keeps running and the cursor is not advanced past a failed fetch.
* **Cursor semantics.** `metar`: the last raw METAR text; unchanged text prints nothing. `acars`:
  the highest message id seen; only newer ids print, and skipped (filtered) messages still move
  the cursor. A brand-new feed prints the current METAR, or at most the newest 3 ACARS messages
  (never the backlog).
* Intervals are at least 5 s. Poll and preview never run concurrently with the loop's poll.

API: `GET /api/feeds/kinds`, `GET|POST /api/feeds`, `POST /api/feeds/{id}/start|stop|poll`,
`DELETE /api/feeds/{id}`, `GET /api/feeds/{id}/preview` (see docs/API.md). CLI:
`minixprint feeds [list|kinds|add KIND [VALUE|key=value ...]|start ID|stop ID|poll ID|rm ID]`.
The dashboard's **Live** panel renders the add form from each kind's `PARAMS`.

## Adding a kind

Drop a module in `minixprint/feeds/`; nothing else to register (`feeds.discover()` imports every
module that defines `KIND`).

```python
KIND = "tides"
DESCRIPTION = "Print the tide table when a new one is published"
PARAMS = {"port": {"type": "text", "required": True, "label": "Port"}}
# field types: icao, text, int, enum (+ "options"), list; also required / default / label
DEFAULT_INTERVAL_S = 3600

def poll(params, cursor, ctx):
    """-> (items oldest first, new_cursor). Only items not seen before; raise on failure."""
    ...
    return [{"key": "2026-10-12", "ts": 1791800000.0, "table": ...}], "2026-10-12"

def render(item, params, ctx):
    """-> mode-"1" PIL image 384 px wide (minixprint.render helpers)."""
```

Rules: `item["key"]` must be stable across restarts (it is the dedupe key; do not use `hash()`);
`cursor` must be JSON-serialisable and `None` on a new feed; cap what the first poll returns;
use `ctx.http` / `minixprint.jobs._aviation_data.get_json` (5 s timeout, `None` on failure) and
raise `RuntimeError` when the source is unreachable so the feed shows the error. An optional
`validate(params) -> params` runs after the schema check. Test with a `FakeSession`
(see tests/test_feeds.py).
