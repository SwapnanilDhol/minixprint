# Feeds

A **feed** is a long-running watcher: it polls a source on an interval and prints every new
item until you stop it. Schedules (docs/API.md) print "something at 07:30"; feeds print
"whenever something new happens".

| Kind | Params | Default interval | Prints |
|---|---|---|---|
| `metar` | `station` (ICAO, required) | 300 s | a compact strip when the station issues a new observation: flight-category badge, decoded wind / vis / weather / clouds / temp / QNH, raw text |
| `acars` | `source` `auto`\|`acarsdec`\|`bot`\|`acarshub` (default `auto`), `udp_port` (default `5570`), `print_binary` (default `false`), `skip_labels` (default `Q0, _d, Q1`), `min_text_len` (default 1) | 15 s | a ticket per message that a human can read or libacars decoded: callsign / registration, time, label·sublabel, frequency, link (ACARS / VDL2), then decoded content or text. Messages from the same flight within 20 s are collapsed into one ticket; a ticket is cut at ~600 px ("+N more messages") |

### ACARS sources

* **`acarsdec`** (UDP, preferred): the server binds `127.0.0.1:<udp_port>` and parses the JSON that
  `acarsdec` (`--output json:udp:...`) or `dumpvdl2` (`--output decoded:json:udp:...`, ACARS under
  `vdl2.avlc.acars`) sends, one record per datagram or several newline-separated. One socket per
  port is shared by all feeds; messages sit in a 500-entry ring buffer (ids are epoch
  milliseconds, so cursors survive restarts and reading never drains). This is the only source
  that carries acarsdec's `libacars` object (ADS-C, CPDLC, MIAM, media advisory, ARINC-622).
  Add the destination to the relay that fans UDP 5550 out (`~/relay.py`):
  ```python
  DESTINATIONS = [
      ("127.0.0.1", 5551), #acarshub
      ("127.0.0.1", 5560), #telegram script
      ("127.0.0.1", 5570), #minixprint
  ]
  ```
  then restart the relay. The listener starts at server boot for enabled acarsdec/auto feeds.
* **`bot`**: `GET <aviation_bot_url>/api/messages`. The bot keeps only its own `decoded` text (ADS-C
  groups, CPDLC) and `summary`, not the libacars object. Use `decoded`, then a `summary` that differs
  from `text`, then readable `text`. The bot decodes ACARS only in its `/acars` mode.
* **`acarshub`**: same shape from `http://127.0.0.1:8081`; stock ACARS Hub serves a websocket, so
  this only works behind a shim.
* **`auto`** (default): `acarsdec` once any ACARS datagram has been received on `udp_port` in this
  server process, else `bot`. It is not persisted: after a restart the feed reads the bot until the
  first datagram arrives. Create the feed with `source: acarsdec` to pin it. Switching sources is
  safe: a cursor from the other source is ignored (UDP ids are > 10^11, bot ids are row numbers).

### What gets printed

Each message is classified (`minixprint/feeds/acars_decode.py`):

| Class | Rule | Printed as |
|---|---|---|
| `decoded` | a `libacars` object or bot `decoded` text exists | ADS-C: position, distance/bearing from home, altitude (FL), time, speed/track/Mach, wind, next waypoints, projections. CPDLC: uplink/downlink, FANS-1/A, message elements, msg id. MIAM: inner text or "compressed MIAM, N bytes". Media advisory: current link and available links. ARINC-622 other / unknown structures: compact `key: value` dump, max 20 lines |
| `readable` | has whitespace, or >= 25 % of `/ . - ,`, or is shorter than 40 chars | the text |
| `binary` | >= 40 chars, >= 95 % of `[A-Za-z0-9+/=]`, no whitespace (or mostly control characters) | skipped; with `print_binary`: `encrypted/binary payload · N bytes` (decoded length when it is valid base64, else characters) |

Filtered messages still advance the cursor. Without libacars (bot source), airline H1/T1 blobs
from encrypted operators are all `binary`.

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
  (never the backlog). With `acarsdec` the cursor is the id (epoch ms) of the newest buffered message.
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
# field types: icao, text, int, bool, enum (+ "options"), list; also required / default / label
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
