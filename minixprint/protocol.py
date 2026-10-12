"""Seznik MiniX / LuckJingle S1 wire protocol: command bytes, builders, decoders.

Single source of truth; PROTOCOL.md documents the same bytes.
"""
from typing import Dict, List, Optional

from .render.compose import to_rows as pack_rows  # noqa: F401  (re-exported)

WIDTH = 384
WIDTH_BYTES = WIDTH // 8

# --- fixed commands ---------------------------------------------------------
WAKE = b"\x00" * 12
ENABLE = b"\x10\xff\xf1\x03"          # enter Lujiang mode
STOP = b"\x10\xff\xf1\x45"            # end of job (no reply on this firmware)
RESET = b"\x10\xff\x04"               # recovery / reset (replies OK)
QUERY_INFO = b"\x10\xff\x70"          # name|mac|hw|fw|serial|battery
QUERY_MODEL = b"\x10\xff\x20\xf0"
QUERY_FIRMWARE = b"\x10\xff\x20\xf1"
QUERY_SERIAL = b"\x10\xff\x20\xf2"
QUERY_BATTERY = b"\x10\xff\x50\xf1"   # -> 00 00 <percent>
QUERY_STATUS = b"\x10\xff\x40"        # -> status bitfield
QUERY_DENSITY = b"\x10\xff\x11"

ACK = b"OK"

DENSITY_LIGHT, DENSITY_NORMAL, DENSITY_DARK = 0, 1, 2

STATUS_FLAGS = [(0x01, "printing"), (0x02, "cover-open"), (0x04, "paper-empty"),
                (0x08, "low-battery"), (0x20, "charging")]
STATUS_OVERHEAT = 0x50  # bit 4 or bit 6


# --- builders ---------------------------------------------------------------
def density(level: int) -> bytes:
    if level not in (0, 1, 2):
        raise ValueError("density must be 0, 1 or 2, got %r" % (level,))
    return bytes([0x10, 0xFF, 0x10, 0x00, level])


def raster_header(n_rows: int) -> bytes:
    """GS v 0 header for n_rows rows of WIDTH_BYTES bytes."""
    if not 0 < n_rows <= 0xFFFF:
        raise ValueError("row count out of range: %d" % n_rows)
    return bytes([0x1D, 0x76, 0x30, 0x00, WIDTH_BYTES, 0x00, n_rows & 0xFF, n_rows >> 8])


def feed(dots: int) -> bytes:
    if not 0 <= dots <= 255:
        raise ValueError("feed must be 0..255 dots, got %r" % (dots,))
    return bytes([0x1B, 0x4A, dots])


# --- decoders ---------------------------------------------------------------
def decode_status(byte: int) -> List[str]:
    flags = [name for bit, name in STATUS_FLAGS if byte & bit]
    if byte & STATUS_OVERHEAT:
        flags.append("overheat")
    return flags or ["ready"]


def parse_info(raw: str) -> Dict[str, object]:
    """Parse the `10 FF 70` reply: name|mac|hw|fw|serial|battery%."""
    name, mac, hw, fw, serial, batt = (raw.strip().split("|") + [""] * 6)[:6]
    battery: Optional[int] = int(batt) if batt.strip().isdigit() else None
    return dict(name=name, mac=mac, hardware=hw, firmware=fw, serial=serial, battery=battery)
