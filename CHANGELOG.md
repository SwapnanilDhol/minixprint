# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [0.1.0] — 2026-10-12

First release.

### Added
- Reverse-engineered protocol for the Seznik MiniX / LuckJingle S1 (Lujiang mode), documented in
  `PROTOCOL.md`.
- `minixprint` package: protocol builders, USB serial and Bluetooth LE transports, `MiniX` driver
  (info, status, density, raster printing, feed).
- Rendering toolkit: text, Markdown, receipts, dithered images, QR codes and barcodes as 384-px
  1-bit bitmaps.
- `minixprint` CLI (`info`, `status`, `text`, `pipe`, `md`, `receipt`, `image`, `qr`, `feed`,
  `stripes`, `serve`) with `--out` PNG previews; `minix.py` kept as a deprecated shim.
- Job registry with auto-discovery: puzzles (sudoku, maze, word search), morning docket, fortune,
  system status.
- Aviation jobs: overhead boarding-pass cards, METAR/TAF, runway in use, traffic board and
  daily/weekly digest, reading a local ADS-B receiver.
- FastAPI server with print queue, history, scheduler (`daily`, `weekly`, `every`), settings, and a
  no-build mobile-first web dashboard; Raspberry Pi systemd unit and Tailscale/iOS Shortcut notes.
- Documentation, sample bitmaps and a 150+ test suite.
