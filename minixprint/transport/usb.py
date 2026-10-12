"""USB CDC serial transport (raw termios, no pyserial)."""
import glob
import logging
import os
import select
import termios
import time
from typing import Optional

from . import CHUNK, GAP, Transport, TransportError

log = logging.getLogger("minixprint.usb")

PORT_PATTERNS = ["/dev/minix", "/dev/ttyACM*", "/dev/cu.usbmodem*"]


def find_port() -> Optional[str]:
    for pat in PORT_PATTERNS:
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[0]
    return None


class UsbTransport(Transport):
    def __init__(self, port: Optional[str] = None):
        self.port = port
        self.fd = None  # type: Optional[int]

    def open(self) -> None:
        if self.fd is not None:
            return
        self.port = self.port or find_port()
        if not self.port:
            raise TransportError("printer not found on USB (no /dev/minix, /dev/ttyACM*, /dev/cu.usbmodem*)")
        try:
            self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as e:
            raise TransportError("cannot open %s: %s" % (self.port, e))
        attr = termios.tcgetattr(self.fd)
        attr[2] |= termios.CLOCAL
        attr[3] &= ~termios.ECHO
        termios.tcsetattr(self.fd, termios.TCSANOW, attr)
        log.debug("serial open %s", self.port)
        self.read(0.5)  # swallow the "OK" greeting

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read(self, timeout: float) -> bytes:
        if self.fd is None:
            raise TransportError("serial port closed")
        out, end = b"", time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.1)
            if r:
                try:
                    out += os.read(self.fd, 4096)
                except BlockingIOError:
                    pass
        if out:
            log.debug("serial rx %s", out.hex(" "))
        return out

    def write(self, data: bytes) -> None:
        if self.fd is None:
            raise TransportError("serial port closed")
        i = 0
        while i < len(data):
            try:
                n = os.write(self.fd, data[i:i + CHUNK])
            except BlockingIOError:
                time.sleep(0.01)
                continue
            log.debug("serial tx %4d %s", n, data[i:i + min(n, 16)].hex(" "))
            i += n
            time.sleep(GAP)
