# Folder watcher

`minixprint watch DIR` prints whatever shows up in a folder. It polls every 2 s (no inotify or
watchdog dependency, so it works on network shares, iCloud/AirDrop folders and the Pi alike) and
sends each new file to a running `minixprint serve` over the HTTP API, so it shares the print
queue, history and dashboard with everything else.

```
minixprint watch DIR [--server URL] [--dither fs|atkinson|none] [--delete | --move-to DIR]
                     [--once] [--interval SECONDS]
```

| Option | |
|---|---|
| `--server URL` | print server, default `http://127.0.0.1:8090`. On the Pi use the default (the local port, no `/print`); over Tailscale `https://swap-pi.<tailnet>.ts.net/print`. |
| `--dither` | for images and PDFs; default `atkinson` (cleanest on thermal paper) |
| `--delete` / `--move-to DIR` | what to do with a file once it printed. Default: leave it (the seen index stops a reprint). `--move-to` never overwrites (`a-2.png`). Mutually exclusive. |
| `--once` | print what is pending and exit: 0 if all printed, 1 if anything failed or the server was down |
| `--interval S` | poll period, default 2 |

## What gets printed

| Files | How |
|---|---|
| `.png .jpg .jpeg` | `POST /api/print/image?dither=…` as-is |
| `.heic .heif .gif .bmp .webp .tif` | converted to PNG first: Pillow, or `sips` on macOS if Pillow can't read it (HEIC) |
| `.pdf` | all pages rasterised to 384 px and stacked by `minixprint/raster.py` (poppler `pdftoppm`, then `gs`, then macOS `qlmanage`/`sips` — first page only; see [CUPS.md](CUPS.md#rasterising)), blank space at the bottom of each page trimmed |
| `.txt` | `POST /api/print/text` |
| `.md` | `POST /api/print/markdown` |

Everything else, dotfiles, `.DS_Store`, and in-progress downloads (`.part`, `.crdownload`,
`.download`, `.tmp`, `.icloud`) are ignored. Subfolders are not scanned.

## Behaviour

- **No reprints.** Printed files are recorded in `DIR/.minixprint-seen` (one line per
  `name, size, mtime`). Restarting the watcher is safe; editing or replacing a file with new
  content prints it again. Delete the index to reprint everything.
- **Half-written files.** A file is only picked up once its mtime is more than 1 s old, so AirDrop
  and browser downloads aren't printed mid-transfer.
- **Failures.** Server down or 5xx: the file stays and is retried every poll. A permanent failure
  (server answers 4xx — e.g. 415 unreadable image — an empty text file, no PDF rasteriser) is logged
  and recorded as seen so it doesn't loop; look at the log, fix, and touch the file to retry.
- Logs go to stderr (`printed a.png as job 12`).

## Recipe: AirDrop to the Mac's printer

AirDrop saves to `~/Downloads`; instead of watching all of Downloads, make a dedicated folder and
AirDrop (or Finder-drag, or "Save to" from any app) into it.

```bash
mkdir -p ~/print-inbox/printed
minixprint watch ~/print-inbox --move-to ~/print-inbox/printed
```

Run it at login with a LaunchAgent, `~/Library/LaunchAgents/com.minixprint.watch.plist`
(adjust the paths; the server must be running too, see docs/PI.md for `minixprint serve`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.minixprint.watch</string>
  <key>ProgramArguments</key><array>
    <string>/Users/YOU/thermal-printer/.venv/bin/minixprint</string>
    <string>watch</string><string>/Users/YOU/print-inbox</string>
    <string>--move-to</string><string>/Users/YOU/print-inbox/printed</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/tmp/minixprint-watch.log</string>
</dict></plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.minixprint.watch.plist
```

macOS caveats: a LaunchAgent has no access to Desktop/Documents/Downloads until you grant the
`minixprint` binary (or its Python) Full Disk Access, so keep the inbox in a plain folder such as
`~/print-inbox`. AirDrop always saves to Downloads: either add a Finder "Folder Action" (Automator)
on Downloads that moves files into `~/print-inbox`, or accept that everything downloaded prints and
watch `~/Downloads` with `--move-to ~/Downloads/printed`. HEIC photos from an iPhone are converted
with `sips`.

## Raspberry Pi

`deploy/minixprint-watch.service` watches `~/print-inbox` and moves printed files to
`~/print-inbox/printed`. Install after `minixprint.service`:

```bash
sudo cp deploy/minixprint-watch.service /etc/systemd/system/
sudo systemctl enable --now minixprint-watch
journalctl -u minixprint-watch -f
```

Install `poppler-utils` for PDFs (`sudo apt install poppler-utils`). To drop files in from another
machine over Tailscale: `scp photo.jpg swap-pi:print-inbox/` (or a Samba/Syncthing share).
