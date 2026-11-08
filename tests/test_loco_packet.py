import struct

import pytest

pytest.importorskip("bson", reason="optional LOCO extra is not installed")
from bson import Int64

from kabot.loco.packet import HEADER_SIZE, LocoPacket, PacketDecoder, PacketError


def test_packet_matches_independently_encoded_wire_fixture():
    # <u32 id><i16 signed status><11 byte method><u8 type><u32 length>
    # BSON document: length21, int64(userId)=42, document terminator.
    fixture = bytes.fromhex(
        "04030201fbff434845434b494e0000000000150000001500000012757365724964002a0000000000000000"
    )
    packet = LocoPacket(0x01020304, "CHECKIN", {"userId": Int64(42)}, status_code=-5)
    assert packet.encode() == fixture
    decoded = LocoPacket.decode(fixture)
    assert decoded.packet_id == 0x01020304
    assert decoded.status_code == decoded.status == -5
    assert type(decoded.body["userId"]) is Int64
    assert decoded.body["userId"] == 42


def test_large_int64_and_nested_binary_are_preserved():
    packet = LocoPacket(
        1,
        "LOGINLIST",
        {"userId": Int64(2**60 + 123), "small64": Int64(1), "nested": {"rp": b"\x00\xff"}},
    )
    decoded = LocoPacket.decode(packet.encode())
    assert decoded.body["userId"] == 2**60 + 123
    assert type(decoded.body["small64"]) is Int64
    assert decoded.body["nested"]["rp"] == b"\x00\xff"


def test_status_prefers_integer_body_and_rejects_boolean_as_status():
    assert LocoPacket(1, "A", {"status": -950}, status_code=-4).status == -950
    assert LocoPacket(1, "A", {"status": True}, status_code=-4).status == -4
    assert LocoPacket(1, "A", {"status": "0"}, status_code=-4).status == -4


def test_stream_decoder_handles_one_byte_chunks_and_coalesced_packets():
    a = LocoPacket(1, "PING").encode()
    b = LocoPacket(2, "MSG", {"text": "한글"}).encode()
    decoder = PacketDecoder()
    packets = []
    for byte in a + b:
        packets.extend(decoder.feed(bytes([byte])))
    assert [p.packet_id for p in packets] == [1, 2]
    assert packets[1].body["text"] == "한글"
    assert decoder.buffered_bytes == 0
    decoder.finish()
    assert [p.packet_id for p in PacketDecoder().feed(a + b)] == [1, 2]


def test_decoder_retains_incomplete_body_and_detects_eof():
    wire = LocoPacket(1, "A", {"hello": "world"}).encode()
    decoder = PacketDecoder()
    assert decoder.feed(wire[:-1]) == []
    with pytest.raises(PacketError, match="incomplete"):
        decoder.finish()
    assert decoder.feed(wire[-1:])[0].body == {"hello": "world"}
    decoder.finish()


def test_oversized_prefix_rejected_before_buffering_body_and_decoder_poisoned():
    decoder = PacketDecoder(max_body_size=32)
    header = struct.pack("<Ih11sBI", 1, 0, b"A", 0, 33)
    with pytest.raises(PacketError, match="limit"):
        decoder.feed(header)
    assert decoder.buffered_bytes == 0
    with pytest.raises(PacketError, match="invalid"):
        decoder.feed(LocoPacket(2, "PING").encode())
    decoder.reset()
    assert decoder.feed(LocoPacket(2, "PING").encode())[0].packet_id == 2


@pytest.mark.parametrize("method", ["", "A" * 12, "한글", "A\0B", "A B", "\n"])
def test_method_validation(method):
    with pytest.raises(PacketError):
        LocoPacket(1, method).encode()


def test_exact_packet_bounds_and_malformed_bson():
    wire = LocoPacket(1, "A").encode()
    for invalid in (wire[:10], wire[:-1], wire + b"extra"):
        with pytest.raises(PacketError):
            LocoPacket.decode(invalid)
    corrupt = bytearray(wire)
    corrupt[-1] = 1
    with pytest.raises(PacketError, match="BSON"):
        LocoPacket.decode(corrupt)
    corrupt = bytearray(wire)
    corrupt[HEADER_SIZE] = 6
    with pytest.raises(PacketError, match="BSON"):
        LocoPacket.decode(corrupt)


def test_empty_body_reference_compatibility_and_nonzero_padding_rejected():
    empty = struct.pack("<Ih11sBI", 0, 0, b"PING", 0, 0)
    assert LocoPacket.decode(empty).body == {}
    assert PacketDecoder().feed(empty)[0].method == "PING"
    bad_padding = struct.pack("<Ih11sBI", 0, 0, b"A\0B", 0, 0)
    with pytest.raises(PacketError, match="padding"):
        LocoPacket.decode(bad_padding)


@pytest.mark.parametrize(
    "packet",
    [
        LocoPacket(-1, "A"),
        LocoPacket(2**32, "A"),
        LocoPacket(1, "A", status_code=-32769),
        LocoPacket(1, "A", body_type=256),
        LocoPacket(True, "A"),
    ],
)
def test_wire_integer_ranges(packet):
    with pytest.raises(PacketError):
        packet.encode()
