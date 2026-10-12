"""ACARS feed: classifier, acarsdec/dumpvdl2 UDP listener, libacars rendering, binary filtering."""
import json
import os
import socket
import time

import pytest
from aviation_fakes import make_ctx

from minixprint import feeds
from minixprint.feeds import acars
from minixprint.feeds import acars_decode as dec
from minixprint.feeds import acars_udp as udp

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "feeds", "acarsdec_samples.jsonl")
SAMPLES = [json.loads(line) for line in open(FIX, encoding="utf-8") if line.strip()]
BY_FLIGHT = {}
for _s in SAMPLES:
    BY_FLIGHT.setdefault(_s.get("flight") or _s["vdl2"]["avlc"]["acars"]["flight"], []).append(_s)

H1_T1 = [
    "BDz5hFCy9H7/3nlv3E8P+b3riZa1COQFi/lrnhVZec1Ic/3TJPrS7Xaj0cTnetIbGwgOfyaCRWo9Op//G3P30XSYLKbR3WI0ixOazO/iNoefwfBPjlHregMhXEoCGQoHN09XWV7xNZsOBwsgBZaLdPuSZ3N3zigw1qxZt7OnJ6AddshH7fDzOL4bRYvhWV3MWRnn0eB2lkTj+D",
    "0qO6CX+9jvPcQuwP4xy3ERp0/55vmPsjZ7zF7SQ/l6yCLwtz+UfVB2DoY3zjw9HDZvad7an00mJ/5OQkdfeowQfbI5zp4XJYSJN9t2jqzLdVdQyJG7HLM3YKnGh5N+nhZFxRvATbdZedisj8oX/ba4c6p/vWQN/8lkGLsibHZFme7WDZu7tPK4Le8AeJ0daAIVr05t6fX6N5z7",
    "yAYe5GWcS3x5ojeNVIEY2PBP70mvwgo6ZFEjBlYILIp6IbN6cDUepSTRPDKZXuAqGguJGwo3+JcSbrB8y8Pl5bkorc7Dz/HpdKR/ijeWzvvT8Xzqnr5yYOeG7DBXGHpfwRChyrseqm8Y9zvch5SSo47D+NiNww+18Jff9NDN3Q==",
]


class FakeCtx:
    def __init__(self):
        self.base = make_ctx()

    def setting(self, k, d=None):
        return self.base.setting(k, d)

    def now(self):
        return time.time()


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def port():
    p = free_port()
    yield p
    udp.close_all()


def send(port, *payloads):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for p in payloads:
        s.sendto(p if isinstance(p, bytes) else json.dumps(p).encode(), ("127.0.0.1", port))
    s.close()


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def sample(flight, i=0):
    return BY_FLIGHT[flight][i]


# --- classifier ----------------------------------------------------------------------------

@pytest.mark.parametrize("text,decoded,want", [
    (H1_T1[0], False, "binary"),
    (H1_T1[1], False, "binary"),
    (H1_T1[2], False, "binary"),
    ("POS N12.93E080.10,FL350", False, "readable"),
    ("PRESENT POSITION REPORT \r\nDMY 22AUG26,UTC 111901,LAT N 13.390,LON E 80.295", False, "readable"),
    ("01 WXRQ   2794/22 VOPB/VOBL .VT-BXV\r\n/TYP 1/STA VOMM", False, "readable"),
    ("A04/A32004,1,1/CC4R-MRE,AUG22,112016,VOMM,VCBI,0128/C105,21002,4000,07,0000,0,0000,00,X", False, "readable"),
    ("VOMMVOCB1122\r\n001FE22112204N1259.3E08011.40131900054", False, "readable"),
    ("SHORTBLOB+/=", False, "readable"),                        # < 40 chars: too short to call
    ("", False, "readable"),
    (H1_T1[0], True, "decoded"),                                 # libacars/decoded text beats everything
    ("\x01\x02\x03\x04\x05\x06 garbage\x07\x08", False, "binary"),
])
def test_classify(text, decoded, want):
    assert dec.classify(text, decoded) == want


def test_classify_real_fixture_samples():
    classes = {s["msgno"]: dec.classify(s["text"], bool(s.get("libacars"))) for s in SAMPLES if "msgno" in s}
    assert classes["181C"] == classes["181B"] == classes["180C"] == "binary"
    assert classes["M98A"] == "readable"
    assert classes["J77A"] == "decoded"


def test_payload_bytes():
    assert dec.payload_bytes(H1_T1[2]) == len(__import__("base64").b64decode(H1_T1[2]))
    assert dec.payload_bytes("not base64!!") == len("notbase64!!")


# --- UDP listener ----------------------------------------------------------------------------

def test_parse_acarsdec_record():
    m = udp.parse_record(sample("IX2007", 0))
    assert (m["registration"], m["callsign"], m["label"], m["sublabel"], m["link"]) == ("VT-BWT", "IX2007", "H1", "T1", "acars")
    assert m["freq_mhz"] == 131.725 and m["libacars"] is None and m["text"].startswith("yAYe")


def test_parse_dumpvdl2_record():
    rec = [s for s in SAMPLES if "vdl2" in s and "arinc622" in s["vdl2"]["avlc"]["acars"]][0]
    m = udp.parse_record(rec)
    assert m["link"] == "vdl2" and m["registration"] == "VT-BWT" and m["callsign"] == "IX2007"
    assert m["freq_mhz"] == pytest.approx(136.975) and m["level_db"] == -22.4
    assert m["libacars"]["arinc622"]["msg_type"] == "adsc_msg"
    assert m["ts"] == pytest.approx(1787670420.123456)
    assert udp.parse_record({"vdl2": {"avlc": {"x25": {}}}}) is None   # non-ACARS VDL2 frame
    assert udp.parse_record({"hello": 1}) is None


def test_datagram_with_several_records_and_junk():
    blob = (json.dumps(sample("IX2007", 0)) + "\nnot json\n" + json.dumps(sample("3U9643", 0)) + "\n").encode()
    assert [m["callsign"] for m in udp.parse_datagram(blob)] == ["IX2007", "3U9643"]
    assert udp.parse_datagram(b"\xff\xfe") == []


def test_listener_receives_both_shapes(port):
    lst = udp.get_listener(port)
    assert udp.get_listener(port) is lst                          # one shared socket per port
    assert not udp.traffic_seen(port)
    vdl2 = [s for s in SAMPLES if "vdl2" in s][0]
    send(port, sample("IX2007", 0), vdl2)
    assert wait_for(lambda: len(lst.buffer) == 2)
    assert udp.traffic_seen(port)
    got = lst.since(None)
    assert [m["link"] for m in got] == ["acars", "vdl2"] and got[0]["id"] < got[1]["id"]
    assert lst.since(got[0]["id"]) == [got[1]]                    # reading doesn't drain
    assert lst.since(got[1]["id"]) == []


def test_bind_failure_is_a_poll_error(port):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", port))
    try:
        with pytest.raises(RuntimeError, match="cannot listen"):
            acars.poll(feeds.validate(acars, {"source": "acarsdec", "udp_port": port}), None, FakeCtx())
    finally:
        blocker.close()


# --- feed behaviour over UDP -------------------------------------------------------------------

def test_poll_acarsdec_filters_binary_by_default(port):
    p = feeds.validate(acars, {"source": "acarsdec", "udp_port": port})
    ctx = FakeCtx()
    items, cur = acars.poll(p, None, ctx)                         # binds; nothing yet
    assert items == [] and cur > 10 ** 11
    send(port, sample("IX2007", 0), sample("3U9643", 0), sample("ZD0001", 0))
    assert wait_for(lambda: len(udp.get_listener(port).buffer) == 3)
    items, cur2 = acars.poll(p, cur, ctx)
    flights = [g["flight"] for g in items]
    assert "IX2007" not in flights and "3U9643" in flights and "ZD0001" in flights
    assert cur2 > cur
    assert acars.poll(p, cur2, ctx)[0] == []


def test_print_binary_prints_placeholder_not_blob(port):
    ctx = FakeCtx()
    p = feeds.validate(acars, {"source": "acarsdec", "udp_port": port, "print_binary": True})
    cur = acars.poll(p, None, ctx)[1]
    send(port, sample("IX2007", 0))
    assert wait_for(lambda: len(udp.get_listener(port).buffer) == 1)
    items, _ = acars.poll(p, cur, ctx)
    assert len(items) == 1 and items[0]["messages"][0]["class"] == "binary"
    text_blocks = acars._body(items[0]["messages"][0], None, None)
    assert len(text_blocks) == 1 and text_blocks[0].height < 40   # one short line, not a wall of base64
    img = acars.render(items[0], p, ctx)
    assert img.width == 384 and img.height < 250


def test_auto_source_switches_once_traffic_seen(port):
    ctx = FakeCtx()
    p = feeds.validate(acars, {"udp_port": port})
    assert acars.resolve_source(p) == "bot"                       # nothing heard yet (and it starts listening)
    send(port, sample("3U9643", 0))
    assert wait_for(lambda: udp.traffic_seen(port))
    assert acars.resolve_source(p) == "acarsdec"
    assert acars.resolve_source(dict(p, source="bot")) == "bot"
    items, _ = acars.poll(p, None, ctx)
    assert len(items) == 1


def test_cursor_from_other_source_is_not_mistaken(port):
    p = feeds.validate(acars, {"source": "acarsdec", "udp_port": port})
    lst = udp.get_listener(port)
    lst.add(dict(udp.parse_record(sample("3U9643", 0))))
    items, _ = acars.poll(p, 40, FakeCtx())                       # a bot-era cursor (row id 40)
    assert len(items) == 1


# --- rendering -------------------------------------------------------------------------------

def item_for(msg, **extra):
    m = udp.parse_record(msg)
    m["id"] = 1
    m["class"] = dec.classify(m["text"], bool(m.get("libacars")))
    m.update(extra)
    return {"key": "1", "flight": m["callsign"], "ts": m["ts"], "messages": [m]}


@pytest.mark.parametrize("flight,i", [("3U9643", 2), ("AI0301", 0), ("AI0301", 1), ("6E0518", 0), ("6E0518", 1),
                                      ("6E0221", 0), ("AI0999", 0), ("IX2007", 3)])
def test_render_each_decoded_type(flight, i):
    msgs = [s for s in BY_FLIGHT[flight] if s.get("libacars") or "vdl2" in s]
    it = item_for(msgs[i if i < len(msgs) else 0])
    img = acars.render(it, {}, make_ctx())
    assert img.mode == "1" and img.width == 384 and 120 < img.height <= 620


def test_render_covers_every_fixture_record():
    for s in SAMPLES:
        img = acars.render(item_for(s), {}, make_ctx())
        assert img.width == 384 and img.height <= 620


def test_adsc_lines_have_position_distance_and_projection():
    msg = [s for s in SAMPLES if s.get("msgno") == "J77A"][0]
    text = "\n".join(t for _, t in dec.describe(msg["libacars"], msg["timestamp"], (12.9941, 80.1709)))
    assert "N13.241 E080.301" in text and "FL350" in text and "from home" in text
    assert "GS 462 kt" in text and "TRK 251" in text and "M0.781" in text
    assert "Next " in text and "Then " in text and "Flight CES6643" in text
    assert "UTC" in text


def test_cpdlc_lines():
    down = [s for s in SAMPLES if s.get("msgno") == "M12A"][0]
    up = [s for s in SAMPLES if s.get("msgno") == "M13A"][0]
    d = "\n".join(t for _, t in dec.describe(down["libacars"], down["timestamp"]))
    u = "\n".join(t for _, t in dec.describe(up["libacars"], up["timestamp"]))
    assert "CPDLC downlink · FANS-1/A" in d and "REQUEST CLIMB TO [altitude]" in d and "380 FL" in d
    assert "CPDLC uplink" in u and "CLIMB TO AND MAINTAIN" in u and "38000 ft" in u


def test_miam_and_media_adv_lines():
    miam_text = "\n".join(t for _, t in dec.describe([s for s in SAMPLES if s.get("msgno") == "D40A"][0]["libacars"]))
    miam_bin = "\n".join(t for _, t in dec.describe([s for s in SAMPLES if s.get("msgno") == "D41A"][0]["libacars"]))
    adv = "\n".join(t for _, t in dec.describe([s for s in SAMPLES if s.get("msgno") == "S01A"][0]["libacars"]))
    assert "A04/A32004" in miam_text
    assert "compressed MIAM, 14 bytes" in miam_bin
    assert "VHF ACARS established" in adv and "Available: VHF ACARS, Default SATCOM" in adv


def test_unknown_structure_dump_is_capped():
    big = {"weird": {"k%d" % i: i for i in range(60)}}
    lines = dec.describe(big)
    assert 0 < len(lines) <= dec.MAX_DUMP_LINES + 8 and lines[0][1] == "weird.k0: 0"
    assert dec.describe(None) == [] and dec.describe({}) == []
    assert dec.describe({"arinc622": "garbage"})                  # odd shapes never raise


def test_bot_item_prefers_decoded_then_differing_summary():
    base = {"id": 1, "ts": 1787670000, "callsign": "AI1", "label": "H1", "text": "RAW TEXT HERE", "class": "readable"}
    out = acars._body(dict(base, decoded="Position: 13.1, 80.2"), None, None)
    assert len(out) == 1
    assert acars._differs("NEW SUMMARY", "RAW TEXT HERE") and not acars._differs("RAW TEXT…", "RAW TEXT HERE")


def test_ticket_height_capped_with_many_messages():
    one = udp.parse_record([s for s in SAMPLES if s.get("msgno") == "J77A"][0])
    msgs = []
    for n in range(12):
        m = dict(one, id=n, ts=one["ts"] + n)
        m["class"] = "decoded"
        msgs.append(m)
    img = acars.render({"key": "x", "flight": "3U9643", "ts": one["ts"], "messages": msgs}, {}, make_ctx())
    assert img.height <= 620
