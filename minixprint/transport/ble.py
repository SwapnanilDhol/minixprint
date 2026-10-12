"""Bluetooth LE transport via bleak (imported lazily so USB-only installs work).

bleak is asyncio-only, so an event loop runs on a daemon thread and the public
write()/read() block on it.

Service FF00: FF02 write (with response), FF01 notify (acks and query replies,
same bytes as USB serial), FF03 notify (status frames `01 <bits>`, plus
`02 C8 00` at connect).
"""
import logging
import queue
import threading
import time
from typing import Optional

from . import CHUNK, GAP, Transport, TransportError

log = logging.getLogger("minixprint.ble")

SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb"
WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"
ACK = "0000ff01-0000-1000-8000-00805f9b34fb"
STATUS = "0000ff03-0000-1000-8000-00805f9b34fb"


class BleTransport(Transport):
    def __init__(self, name_prefix: str = "Seznik MiniX", scan_timeout: float = 12.0):
        self.name_prefix = name_prefix
        self.scan_timeout = scan_timeout
        self.rx = queue.Queue()
        self.client = None
        self.loop = None
        self.thread = None
        self._status = None  # type: Optional[int]

    @property
    def status_byte(self) -> Optional[int]:
        return self._status

    def clear_status(self) -> None:
        self._status = None

    def open(self) -> None:
        if self.client is not None:
            return
        try:
            import asyncio

            import bleak  # noqa: F401
        except ImportError:
            raise TransportError("BLE needs bleak: pip install bleak")
        self._asyncio = asyncio
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self._run(self._connect())

    def _run(self, coro, timeout=None):
        return self._asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _connect(self):
        from bleak import BleakClient, BleakScanner
        prefix = self.name_prefix

        def match(dev, adv):
            name = adv.local_name or dev.name or ""
            return name.startswith(prefix) or SERVICE in (adv.service_uuids or [])

        log.debug("BLE scanning for '%s*' / service FF00 (%.0fs)", prefix, self.scan_timeout)
        dev = await BleakScanner.find_device_by_filter(match, timeout=self.scan_timeout)
        if dev is None:
            raise TransportError("printer not found over BLE (is it on, and unplugged from USB?)")
        log.debug("BLE found %s %s", dev.name, dev.address)
        client = BleakClient(dev, disconnected_callback=lambda c: log.debug("BLE disconnected"))
        await client.connect()
        log.debug("BLE connected, MTU %s", client.mtu_size)
        await client.start_notify(ACK, self._on_notify)
        await client.start_notify(STATUS, self._on_notify)
        await self._asyncio.sleep(0.3)  # let the connect-time status frames land
        self.client = client

    def _on_notify(self, char, data):
        data = bytes(data)
        ch = char.uuid[4:8].upper()
        log.debug("BLE %s rx %s", ch, data.hex(" "))
        if ch == "FF03":
            # status side channel: `01 <bits>`; never part of a reply
            if len(data) == 2 and data[0] == 0x01:
                self._status = data[1]
            return
        self.rx.put(data)

    async def _write(self, data):
        for i in range(0, len(data), CHUNK):
            part = data[i:i + CHUNK]
            await self.client.write_gatt_char(WRITE, part, response=True)
            log.debug("BLE tx %4d %s", len(part), part[:16].hex(" "))
            await self._asyncio.sleep(GAP)

    def write(self, data: bytes) -> None:
        self._run(self._write(bytes(data)))

    def read(self, timeout: float) -> bytes:
        out, end = b"", time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                return out
            try:
                out += self.rx.get(timeout=left)
            except queue.Empty:
                return out

    def close(self) -> None:
        if self.client is not None:
            try:
                self._run(self.client.disconnect(), timeout=5)
            except Exception as e:  # best-effort
                log.debug("BLE disconnect error: %s", e)
            self.client = None
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
            self.loop = None
