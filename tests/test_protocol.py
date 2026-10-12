import pytest

from minixprint import protocol as P
from minixprint.render.compose import to_rows

INFO = "Seznik MiniX_513E_LE|51:3e:37:33:22:10|V1.5.0|V1.9.9|P2528602697|98"


def test_constants():
    assert P.WAKE == bytes(12)
    assert P.ENABLE == bytes.fromhex("10fff103")
    assert P.STOP == bytes.fromhex("10fff145")
    assert P.QUERY_INFO == bytes.fromhex("10ff70")
    assert P.QUERY_STATUS == bytes.fromhex("10ff40")
    assert P.QUERY_BATTERY == bytes.fromhex("10ff50f1")


def test_builders():
    assert P.density(2) == bytes.fromhex("10ff100002")
    assert P.raster_header(300) == bytes.fromhex("1d763000" "3000" "2c01")
    assert P.feed(100) == bytes.fromhex("1b4a64")
    for bad in (3, -1):
        with pytest.raises(ValueError):
            P.density(bad)
    with pytest.raises(ValueError):
        P.feed(256)
    with pytest.raises(ValueError):
        P.raster_header(0)


def test_decode_status():
    assert P.decode_status(0) == ["ready"]
    assert P.decode_status(0x05) == ["printing", "paper-empty"]
    assert P.decode_status(0x28) == ["low-battery", "charging"]
    assert P.decode_status(0x10) == ["overheat"]
    assert P.decode_status(0x40) == ["overheat"]


def test_parse_info():
    d = P.parse_info(INFO)
    assert d == dict(name="Seznik MiniX_513E_LE", mac="51:3e:37:33:22:10", hardware="V1.5.0",
                     firmware="V1.9.9", serial="P2528602697", battery=98)
    assert P.parse_info("")["battery"] is None


def test_pack_rows_reexport():
    assert P.pack_rows is to_rows
