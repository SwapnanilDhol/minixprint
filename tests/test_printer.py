import pytest
from PIL import Image

from minixprint import protocol as P
from minixprint.printer import MiniX
from minixprint.transport import Transport

INFO = "Seznik MiniX_513E_LE|51:3e:37:33:22:10|V1.5.0|V1.9.9|P2528602697|98"


class FakeTransport(Transport):
    """Records writes; replies is a list of (trigger-prefix, reply) consumed on read."""

    def __init__(self, replies=None, status=None):
        self.writes = []
        self.replies = dict(replies or {})
        self.pending = b""
        self._status = status
        self.opened = self.closed = False

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        for prefix, reply in self.replies.items():
            if data.startswith(prefix):
                self.pending += reply
        if data.startswith(P.raster_header(1)[:4]):  # raster block
            self.pending += b"OK"  # ack after the raster block

    def read(self, timeout):
        out, self.pending = self.pending, b""
        return out

    @property
    def status_byte(self):
        return self._status


def test_print_bitmap_exact_bytes():
    t = FakeTransport({P.density(2): b"OK"})
    rows = b"\xff" * 48 + b"\x00" * 48 + b"\xaa" * 48
    with MiniX(t) as p:
        ack, end = p.print_bitmap(rows, density=2, feed=100)
    assert ack == b"OK" and end == b""
    assert b"".join(t.writes) == (
        bytes(12) + bytes.fromhex("10fff103") + bytes.fromhex("10ff100002")
        + bytes.fromhex("1d76300030000300") + rows
        + bytes.fromhex("1b4a64") + bytes.fromhex("10fff145"))
    assert t.opened and t.closed


def test_print_bitmap_validates():
    p = MiniX(FakeTransport())
    with pytest.raises(ValueError):
        p.print_bitmap(b"\x00" * 47)
    with pytest.raises(ValueError):
        p.print_bitmap(b"")


def test_info_and_battery():
    t = FakeTransport({P.QUERY_INFO: INFO.encode(), P.QUERY_MODEL: b"S1_LYiN48D_IND",
                       P.QUERY_BATTERY: b"\x00\x62"})
    p = MiniX(t)
    d = p.info()
    assert d["battery"] == 98 and d["firmware"] == "V1.9.9" and d["model"] == "S1_LYiN48D_IND"
    assert p.battery() == 0x62


def test_status_from_reply_and_side_channel():
    assert MiniX(FakeTransport({P.QUERY_STATUS: b"\x05"})).status() == (5, ["printing", "paper-empty"])
    assert MiniX(FakeTransport(status=0)).status() == (0, ["ready"])
    assert MiniX(FakeTransport()).status() is None


def test_feed():
    t = FakeTransport()
    MiniX(t).feed(40)
    assert t.writes == [bytes.fromhex("1b4a28")]


def test_print_image_scales_and_packs():
    t = FakeTransport()
    MiniX(t).print_image(Image.new("L", (192, 10), 0), density=1, feed=0)
    blob = b"".join(t.writes)
    assert bytes.fromhex("1d763000300014" "00") in blob  # 192x10 scaled to 384x20 -> 0x14 rows
    assert blob.endswith(bytes.fromhex("1b4a00") + P.STOP)
