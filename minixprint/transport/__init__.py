"""Byte pipes to the printer."""
import abc
from typing import Optional

CHUNK = 128
GAP = 0.035  # seconds between chunks


class TransportError(RuntimeError):
    """Printer unreachable or connection failed."""


class Transport(abc.ABC):
    """Subclasses chunk writes themselves (128 B, 35 ms apart)."""

    @abc.abstractmethod
    def open(self) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    @abc.abstractmethod
    def write(self, data: bytes) -> None: ...

    @abc.abstractmethod
    def read(self, timeout: float) -> bytes:
        """Collect whatever arrives within `timeout` seconds."""

    @property
    def status_byte(self) -> Optional[int]:
        """Latest status delivered on a side channel (BLE FF03), else None."""
        return None

    def clear_status(self) -> None:
        pass
