# iOS Shortcuts

Base URL: `https://swap-pi.<tailnet>.ts.net/print` (the iPhone must be on the tailnet; the Tailscale
app's VPN toggle on). No auth header is needed — Tailscale identifies you.

## 1. Print any photo/image from the Share Sheet

1. Shortcuts app → **+** → name it **Print on MiniX**.
2. Tap the ⓘ (shortcut details) → enable **Show in Share Sheet** → *Share Sheet Types*: **Images**
   (and optionally Photos / Screenshots).
3. Add action **Get Contents of URL**:
   - URL: `https://swap-pi.<tailnet>.ts.net/print/api/print/image?dither=atkinson&gamma=1.1`
   - Tap **Show More** → Method: **POST** → Request Body: **Form**.
   - **Add new field** → type **File** → Key: `file` → Value: **Shortcut Input**.
4. (Optional) Add **Show Notification** with the result so you see `queued`.

Query parameters: `dither` = `fs` | `atkinson` | `none`, `gamma` (0.4–2.4, higher = lighter),
`invert` = `true|false`, `density` = `0|1|2`.

## 2. Print text (Share Sheet text, or ask)

1. New shortcut **Print text**; Share Sheet Types: **Text**, **URLs**.
2. Add **Get Contents of URL**:
   - URL: `https://swap-pi.<tailnet>.ts.net/print/api/print/text`
   - Method **POST**, Request Body **JSON**.
   - Add fields: `text` (Text) = **Shortcut Input**; `size` (Number) = `30`; optionally `align` (Text) = `left`,
     `bold` (Boolean).
   - (For a stand-alone shortcut, put **Ask for Input** first and use its result as `text`.)

## 3. Other bodies

All JSON, `POST`, `Content-Type: application/json` (Shortcuts sets it for the JSON body type):

| Endpoint | Body |
|---|---|
| `/api/print/text` | `{"text": "Hello", "size": 28, "align": "left", "bold": false, "mono": false}` |
| `/api/print/markdown` | `{"markdown": "# Title\n- item"}` |
| `/api/print/qr` | `{"data": "https://example.com", "caption": "scan me"}` |
| `/api/print/receipt` | `{"title": "T", "items": [{"name": "x", "qty": 1, "price": 10}], "currency": "INR"}` |
| `/api/jobs/fortune/run` | `{}` |
| `/api/jobs/puzzle.sudoku/run` | `{"difficulty": "medium"}` (see `GET /api/jobs` and [JOBS.md](JOBS.md)) |
| `/api/feed` | `{"dots": 120}` |

Tip: a **Print a fortune** shortcut is just one *Get Contents of URL* (POST, JSON `{}`) to
`/api/jobs/fortune/run` — put it on the Home Screen or Lock Screen.

Test from a Mac first: `curl -X POST https://swap-pi.<tailnet>.ts.net/print/api/jobs/fortune/run -H 'content-type: application/json' -d '{}'`.
