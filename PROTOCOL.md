# Seznik MiniX (LuckJingle S1) — protocol notes

The byte constants and builders live in `minixprint/protocol.py` (single source of truth);
transports in `minixprint/transport/`, CLI in `docs/CLI.md`. The old `minix.py` is a shim.

Reverse-engineered 2026-10-12 against the physical unit on this desk.

## Identity (from the printer itself)

| Query | Response |
|---|---|
| `10 FF 20 F0` model | `S1_LYiN48D_IND` |
| `10 FF 20 F2` serial | `P2528602697` |
| `10 FF 20 F1` firmware | `V1.9.9` |
| `10 FF 70` all-info | `Seznik MiniX_513E_LE\|51:3e:37:33:22:10\|V1.5.0\|V1.9.9\|P2528602697\|98` (name \| BLE MAC \| hw \| fw \| serial \| battery %) |
| `10 FF 50 F1` battery | `00 62` on USB serial (`00 00 62` seen elsewhere); last byte 0x62 = 98 % |
| `10 FF 11` density get | `02 00 00` → 2 (0 light, 1 normal, 2 dark) |
| `10 FF 13` auto-shutdown get | `00` |

Chipset family: **LuckPrinter SDK, Lujiang "BaseNormalDevice"** (same as DP_D1 / LuckP_D1 /
DP-L1S). USB descriptor: vendor `PPS1`, product `LJPrt ComPort`, VID `0x3021` PID `0x6001`.

## Transports

| Transport | Path on this Mac | Notes |
|---|---|---|
| USB CDC serial | `/dev/cu.usbmodemb1203000011` | **Primary.** Full command set, replies come back on the same port. Prints `OK` on open. |
| USB printer class (7/1/2) | `usb://PPS1/?serial=b120300001` | IEEE-1284 ID says `COMMAND SET:ESC/POS`. Accepts bytes (via `/usr/libexec/cups/backend/usb`), no replies seen. macOS no longer allows raw CUPS queues. |
| Bluetooth LE | name `Seznik MiniX_513E_LE`, service `FF00` | **Working** (`minixprint --ble`). write `FF02` (props write + write-no-response, bleak reports MTU 240), notify `FF01` (acks + query replies, same bytes as USB serial), notify `FF03` (status frames). Use write-with-response. See *BLE details* below. |
| Bluetooth Classic SPP | `/dev/cu.SeznikMiniX_513E` | Pairs as "Display". Accepts bytes, never replies. Not useful. |

## Print job sequence (Lujiang mode)

```
00 ×12                       wake
10 FF F1 03                  enable, Lujiang mode (wrong mode => "accepts data silently, never prints")
10 FF 10 00 nn               density 0..2 (optional; replies OK)
1D 76 30 m wL wH hL hH       GS v 0 raster header; m=0, wL=0x30 wH=0x00 (384 px), h = rows
<rows × 48 bytes>            1 bpp, MSB first, 1 = black
1B 4A nn                     feed nn dots (printer replies 00 then "OK" after image on USB)
10 FF F1 45                  stop; wait for AA or "OK" (up to 60 s)
```

Over BLE and USB serial: 128-byte chunks, ~35 ms apart (write-with-response on BLE). On
both transports the printer answers `OK` (`4F 4B`) after the density command and again after
the last raster chunk; `1B 4A` and `10 FF F1 45` get no reply on this firmware.

## Status

`10 FF 40` → 1 byte bitfield (reply seen on the BLE `FF03` channel as `01 <byte>`;
over USB serial the printer didn't answer the query directly).

| bit | meaning |
|---|---|
| 0 | printing / busy |
| 1 | cover open |
| 2 | paper empty |
| 3 | low battery |
| 5 | charging |
| 4 or 6 | overheating |

Observed: `01 05` on BLE connect (busy + paper-empty), `01 01` after a job (busy).
`02 C8 00` also arrives on `FF03` at connect — meaning unknown (0xC8 = 200).

LED, per LuckJingle docs: flashing red = low battery, steady red = charging / no paper /
cover open / overheat. On this unit it flashed red at 98 % battery while reporting
busy + paper-empty, so treat flashing red as "error state" and power-cycle.
**Flashing green = healthy, idle.**

Confirmed working 2026-10-12: after a power cycle the printer answers `OK OK` (density +
raster) on USB serial and prints `minixprint stripes` / `minixprint text`. The stop command
`10 FF F1 45` never replies on USB on this firmware — don't wait for it. The earlier wedge
(acks but no output, red flash) was a stuck busy/paper-empty state from the very first
malformed ESC/POS text job; only a power cycle cleared it (`10 FF 04` did not).

## BLE details (observed 2026-10-12 with bleak 3.0 on macOS, `minixprint --ble -v`)

Connection: scan for local name prefix `Seznik MiniX` (or service `FF00`), connect, enable
notifications on `FF01` and `FF03`. Every write goes to `FF02` with response, ≤128 bytes,
~35 ms apart; each write-with-response completes in ~15 ms, so a 120-row stripes job
(5.7 KB) takes ~2 s. No write ever failed or needed a retry. Advertised address on this
Mac: CoreBluetooth UUID `CEB3E049-3F34-AD91-B492-3B1F4B8A5411` (not the MAC).

Traffic seen on a text job:

```
connect     FF03 <- 01 05          (busy + paper-empty; appears on every connect, meaningless)
            FF03 <- 02 C8 00       (unknown, every connect)
-> 10 FF 40 FF03 <- 01 01, FF01 <- 00            status query: status frame + ack
-> 10 FF 70 FF01 <- "Seznik MiniX_513E_LE|51:3e:...|V1.5.0|V1.9.9|P2528602697|100"
-> 00 x12, 10 FF F1 03             FF03 <- 01 01 after each write
-> 10 FF 10 00 02                  FF01 <- 4F 4B ("OK")
-> 1D 76 30 ... + raster chunks    FF03 <- 01 01 after EVERY 128-byte chunk
   (last chunk)                    FF01 <- 4F 4B ("OK")   <- the ack to wait for
-> 1B 4A 64                        nothing
-> 10 FF F1 45                     FF03 <- 01 01 twice, no FF01 reply
```

So `FF01` carries exactly the bytes the USB serial port would return and `FF03` is a
side channel: a `01 <status>` frame after every chunk written while a job is active, which
is what `minixprint status` decodes. `01 01` (busy) stays set for a couple of seconds after
a job. Nothing on BLE ever reported the job finished; wait for the `OK` after the raster
block and move on, as on USB.

Advertising: the printer *did* advertise and accept a BLE connection today while the USB
cable was plugged in (serial port not held open by anyone). An earlier session saw no
advertisement with USB connected; the difference is probably whether a USB serial session
was open at the time. Unplug USB if the scan times out.

macOS caveat: any process that touches CoreBluetooth is killed with SIGABRT unless the
*responsible app* has `NSBluetoothAlwaysUsageDescription` in its Info.plist. Run
`minixprint --ble` from Terminal.app or the Claude desktop app's Terminal panel (both fine);
the Claude Code helper bundle lacks the key, so shells it spawns cannot use BLE.

## Other commands (from the LuckPrinter SDK, untested here)

| Bytes | Purpose |
|---|---|
| `10 FF 04` | recovery / reset (replies OK) |
| `10 FF 12 hi lo` / `10 FF 13` | auto-shutdown set / get |
| `10 FF C0 n` / `10 FF 20 A0` | print speed set / get |
| `10 FF 15 lo hi` | print width |
| `10 FF 30 27 n` | printer mode |
| `1F 70 01 n` | heating |
| `1F 80 type param` | paper type (label/black-mark/continuous) |
| `1B BB CC` / `1B BB AA` / `1B BB BB` | batch markers first / middle / last |
| `1D 0C` | position to next label |
| `1F 11 51` / `1F 11 50` | label auto-adjust start / end |

Things that do **not** work: ESC/POS text (no font; printer only renders bitmaps),
`DLE EOT` status, `GS I` identity queries.

## Sources

- https://github.com/rhutikcodes/seznik-printer-api (BLE, same command bytes)
- https://lsong.org/luckjingle-d1-printer (web-bluetooth reference implementation)
- https://github.com/ChiaraCannolee/thermal-pocket-printer-basic — PROTOCOL.md (decompiled LuckPrinter SDK)
- https://github.com/0xMH/fichero-printer/blob/main/docs/PROTOCOL.md (AiYin sibling, Lujiang notes)
- https://www.luckjingle.com/faq (LED meanings)
