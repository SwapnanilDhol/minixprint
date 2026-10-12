# CUPS: print from any app

`deploy/cups/` adds a normal printer called **minix** to macOS or Linux. Choose it in any Print
dialog (or `lp -d minix file`) and the page lands on the MiniX through the HTTP server, so it
appears in the dashboard history like every other job.

```
app → CUPS (PDF) → backend "minixprint" → rasterise → POST {server}/api/print/image?dither=atkinson
```

- **`minixprint.ppd`** declares a greyscale 203 dpi roll printer, 48 mm (136 pt, 384 dots) wide,
  no margins, with `*cupsFilter: "application/pdf 0 -"` so CUPS converts everything (text, images,
  PostScript) to PDF and hands it to the backend untouched. Page sizes: 48×100 / 48×200 /
  48×400 mm plus a custom size (width 48 mm, length 20 mm – 2 m); apps that honour roll sizes
  (LibreOffice, Preview, browsers via "Paper size") lay the document out at 48 mm wide, which is
  what makes text legible. On a Letter/A4 page everything is shrunk to 384 px and is tiny.
- **`minixprint-backend`** (installed as `minixprint`) is stdlib Python plus Pillow. It reads the
  PDF, rasterises all pages to 384 px wide greyscale (`minixprint/raster.py`), trims blank paper
  at the bottom of each page, stacks them, and POSTs one PNG. Without arguments it prints the
  discovery line `direct minixprint://localhost:8090 "MiniX" "MiniX thermal printer"`.
- **Device URI** `minixprint://host[:port][/root-path]` selects the server: port 443 or the scheme
  `minixprints://` means https. Examples: `minixprint://localhost:8090`,
  `minixprint://pi.local:8090`, `minixprints://swap-pi.<tailnet>.ts.net/print`.
- Exit codes (cups-backend(7)): 0 done, 6 retry (server unreachable or 5xx — CUPS retries per the
  queue's ErrorPolicy), 1 failed (rasteriser missing, 4xx from the server, bad URI). Progress is
  reported as `STATE:`/`INFO:`/`ERROR:` lines on stderr (visible in `/var/log/cups/error_log` and
  as the job's status in the queue window).

## Rasterising

`raster.rasterise_pdf` tries, in order, and reports the engine in the job's INFO line:

| Engine | Where | Pages | Notes |
|---|---|---|---|
| `pdftoppm -gray -r 203 -scale-to-x 384 -scale-to-y -1` | Pi/Linux (`apt install poppler-utils`), Mac (`brew install poppler`) | all | best quality; preferred |
| `gs -sDEVICE=pnggray -r203` | anywhere ghostscript is installed | all | |
| `qlmanage -t -s 2000` | macOS built-in | **first only** | Quick Look thumbnail, ~1500 px wide: sharp |
| `sips -s format png` | macOS built-in | **first only** | 72 dpi render, soft; last resort |

Tested on this Mac, which has neither poppler nor ghostscript: `qlmanage` is what ran. **Install
poppler on the Mac if you print multi-page documents.**

## Install

Needs sudo. Pillow must be importable by the Python the backend uses (the installer picks the
repo's `.venv`, then Homebrew/system python3; override with `--python`).

```bash
deploy/cups/install.sh                          # server http://localhost:8090
deploy/cups/install.sh --server http://pi.local:8090
deploy/cups/install.sh --uninstall
```

It copies the backend to `/usr/libexec/cups/backend/minixprint` (macOS) or
`/usr/lib/cups/backend/` (Linux), `raster.py` to `/usr/local/lib/minixprint-cups/`, the PPD to
`/Library/Printers/PPDs/Contents/Resources/` or `/usr/share/cups/model/`, and runs
`lpadmin -p minix -E -v minixprint://… -P …/minixprint.ppd`. If sudo is unavailable it prints the
commands for you to run. CUPS runs backends as an unprivileged user (`_lp`/`lp`) which cannot read
your home directory, which is why the files are copied to system locations rather than run from
the checkout. Re-run the installer after changing `raster.py` or the backend.

### On the Pi

```bash
sudo apt install cups poppler-utils python3-pil
deploy/cups/install.sh                          # server is local: http://localhost:8090
lp -d minix ~/note.txt
```

### The Pi's queue from another machine (Tailscale)

Two options. Simplest: install the queue on the *other* machine pointing at the Pi's server —
the backend only needs HTTP, no CUPS on the Pi at all:

```bash
deploy/cups/install.sh --server https://swap-pi.<tailnet>.ts.net/print
```

Alternatively share the Pi's queue over IPP: on the Pi `sudo cupsctl --share-printers
--remote-any` (or `lpadmin -p minix -o printer-is-shared=true`), then on the Mac add
`ipp://swap-pi.<tailnet>.ts.net:631/printers/minix` in System Settings → Printers with
"Generic PostScript Printer"/"IPP Everywhere" driver. Port 631 must be reachable over the tailnet
(don't expose it publicly); page layout then happens on the Mac with the generic driver, so prefer
the first option unless the Mac can't install a backend.

## Limitations

- Output is one-bit via Atkinson dither: fine for text and line art, grainy for photos.
- Anything not sized for 48 mm is scaled down to 384 px; pick a "48 mm" page size for readable text.
- macOS sandbox rules and SIP: the backend directory must be writable (`sudo` works; on a Mac with
  a locked-down `/usr/libexec/cups` the install fails and prints the commands).
- No printer status or feedback to CUPS: it only knows the HTTP server accepted the job. Paper-out
  or a stalled printer show in the dashboard, not in the print queue.
- Copies, duplex, page ranges are handled by CUPS before the backend (it sees the final PDF).
- Without poppler/ghostscript on macOS only the first page of a PDF prints.
