"""High-level printer API: MiniX(transport) plus the connect() factory."""
import threading
from typing import Dict, List, Optional, Tuple

from . import protocol as P
from .render import WIDTH
from .render.compose import to_rows
from .render.image import render_image
from .transport import Transport
from .transport.usb import UsbTransport, find_port


class MiniX:
    """One printer, one job at a time: every public method holds a lock."""

    def __init__(self, transport: Transport):
        self.t = transport
        self.lock = threading.RLock()
        self._open = False

    # --- lifecycle ---------------------------------------------------------
    def open(self) -> "MiniX":
        with self.lock:
            if not self._open:
                self.t.open()
                self._open = True
        return self

    def close(self) -> None:
        with self.lock:
            if self._open:
                self.t.close()
                self._open = False

    def __enter__(self) -> "MiniX":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # --- plumbing ----------------------------------------------------------
    def _query(self, cmd: bytes, timeout: float = 1.5) -> bytes:
        self.t.write(cmd)
        return self.t.read(timeout)

    # --- queries -----------------------------------------------------------
    def info(self) -> Dict[str, object]:
        with self.lock:
            d = P.parse_info(self._query(P.QUERY_INFO, 2.5).decode(errors="replace"))
            d["model"] = self._query(P.QUERY_MODEL).decode(errors="replace")
            return d

    def battery(self) -> Optional[int]:
        """Battery percent, or None if the printer didn't answer."""
        with self.lock:
            r = self._query(P.QUERY_BATTERY)
            return r[-1] if len(r) >= 2 else None  # reply is `00 [00] <percent>`

    def status(self) -> Optional[Tuple[int, List[str]]]:
        """(status byte, flag names), or None if there was no reply."""
        with self.lock:
            self.t.clear_status()
            r = self._query(P.QUERY_STATUS, 1.0)
            s = self.t.status_byte
            if s is None:
                if not r:
                    return None
                s = r[-1]
            return s, P.decode_status(s)

    # --- printing ----------------------------------------------------------
    def feed(self, dots: int = 80) -> None:
        with self.lock:
            self.t.write(P.feed(dots))

    def print_bitmap(self, rows: bytes, density: int = 2, feed: int = 100) -> Tuple[bytes, bytes]:
        """rows: n * 48 bytes, 1 = black, MSB first. Returns (raster ack, end reply)."""
        if not rows or len(rows) % P.WIDTH_BYTES:
            raise ValueError("rows must be a non-empty multiple of %d bytes" % P.WIDTH_BYTES)
        n = len(rows) // P.WIDTH_BYTES
        with self.lock:
            self.t.write(P.WAKE)
            self.t.write(P.ENABLE)
            self.t.write(P.density(density))
            self.t.read(0.3)
            self.t.write(P.raster_header(n) + rows)
            ack = self.t.read(1.0)
            self.t.write(P.feed(feed))
            self.t.write(P.STOP)
            end = self.t.read(5.0)
            return ack, end

    def print_image(self, img, density: int = 2, feed: int = 100) -> Tuple[bytes, bytes]:
        """Print a PIL image. Mode-"1" images already WIDTH px wide go out as-is;
        anything else is scaled and dithered (Floyd-Steinberg) first."""
        if img.mode != "1" or img.width != WIDTH:
            img = render_image(img)
        return self.print_bitmap(to_rows(img), density, feed)


def connect(prefer: str = "auto", port: Optional[str] = None, name: Optional[str] = None) -> MiniX:
    """Open a printer. prefer: "usb", "ble", or "auto" (USB if a port exists, else BLE)."""
    if prefer not in ("auto", "usb", "ble"):
        raise ValueError("prefer must be auto, usb or ble")
    if prefer == "usb" or (prefer == "auto" and (port or find_port())):
        t = UsbTransport(port)  # type: Transport
    else:
        try:
            from .transport.ble import BleTransport
        except ImportError as exc:
            if prefer == "auto":
                raise RuntimeError(
                    "no printer found: no USB serial port (/dev/minix, /dev/ttyACM*, "
                    "/dev/cu.usbmodem*) and BLE unavailable (%s)" % exc
                ) from exc
            raise
        t = BleTransport(name) if name else BleTransport()
    p = MiniX(t)
    try:
        return p.open()
    except Exception:
        p.close()
        raise
