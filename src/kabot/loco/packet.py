"""Experimental LOCO BSON framing, based on the pinned openkakao-cli reference.

Wire format only; this does not establish compatibility with a live Kakao server.
See docs/THIRD_PARTY_NOTICES.md for source identity and license.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

try:
    from bson import BSON
    from bson.errors import BSONError
except ImportError as error:
    raise ImportError(
        'LOCO requires optional dependencies: pip install "kabot-python[loco]"'
    ) from error

HEADER_SIZE = 22
MAX_BODY_SIZE = 16 * 1024 * 1024
_HEADER = struct.Struct("<Ih11sBI")


class PacketError(ValueError):
    """Invalid or unsupported LOCO packet framing/BSON."""


def _limit(value: int) -> int:
    if type(value) is not int or not 5 <= value <= 100 * 1024 * 1024:
        raise ValueError("max_body_size must be between 5 bytes and 100 MiB")
    return value


def _integer(value: int, minimum: int, maximum: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PacketError(f"{name} is outside its wire integer range")


def _method(value: str) -> bytes:
    if not isinstance(value, str) or not 1 <= len(value) <= 11:
        raise PacketError("method must contain 1 to 11 printable ASCII characters")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        raise PacketError("method must contain printable ASCII characters") from None
    if any(byte < 0x21 or byte > 0x7E for byte in encoded):
        raise PacketError("method must contain printable ASCII characters")
    return encoded


@dataclass(frozen=True)
class PacketHeader:
    packet_id: int
    status_code: int
    method: str
    body_type: int
    body_length: int


@dataclass(frozen=True)
class LocoPacket:
    packet_id: int
    method: str
    body: Mapping[str, Any] = field(default_factory=dict)
    status_code: int = 0
    body_type: int = 0

    @property
    def status(self) -> int:
        """Reference precedence: integer body.status, otherwise signed header status."""
        value = self.body.get("status")
        return (
            int(value)
            if isinstance(value, int) and not isinstance(value, bool)
            else self.status_code
        )

    def encode(self, *, max_body_size: int = MAX_BODY_SIZE) -> bytes:
        limit = _limit(max_body_size)
        _integer(self.packet_id, 0, 0xFFFFFFFF, "packet_id")
        _integer(self.status_code, -32768, 32767, "status_code")
        _integer(self.body_type, 0, 255, "body_type")
        method = _method(self.method)
        if not isinstance(self.body, Mapping):
            raise PacketError("body must be a BSON document mapping")
        try:
            payload = BSON.encode(dict(self.body))
        except (BSONError, OverflowError, TypeError, ValueError, RecursionError):
            raise PacketError("body cannot be encoded as BSON") from None
        if len(payload) > limit:
            raise PacketError("packet body exceeds configured limit")
        return (
            _HEADER.pack(self.packet_id, self.status_code, method, self.body_type, len(payload))
            + payload
        )

    @staticmethod
    def decode_header(
        data: bytes | bytearray | memoryview, *, max_body_size: int = MAX_BODY_SIZE
    ) -> PacketHeader:
        limit = _limit(max_body_size)
        if len(data) < HEADER_SIZE:
            raise PacketError("truncated LOCO header")
        packet_id, status, padded, body_type, length = _HEADER.unpack_from(data)
        method, separator, padding = padded.partition(b"\0")
        if separator and any(padding):
            raise PacketError("method has nonzero bytes after null padding")
        try:
            method_text = method.decode("ascii")
        except UnicodeDecodeError:
            raise PacketError("method is not ASCII") from None
        _method(method_text)
        if length > limit:
            raise PacketError("packet body exceeds configured limit")
        if 0 < length < 5:
            raise PacketError("BSON document must contain at least 5 bytes")
        return PacketHeader(packet_id, status, method_text, body_type, length)

    @classmethod
    def decode(
        cls, data: bytes | bytearray | memoryview, *, max_body_size: int = MAX_BODY_SIZE
    ) -> LocoPacket:
        """Decode exactly one packet. Trailing bytes require PacketDecoder instead."""
        header = cls.decode_header(data, max_body_size=max_body_size)
        if len(data) != HEADER_SIZE + header.body_length:
            raise PacketError("packet length does not match its header")
        payload = bytes(data[HEADER_SIZE:])
        if not payload:
            body: dict[str, Any] = {}
        else:
            if struct.unpack_from("<i", payload)[0] != header.body_length or payload[-1] != 0:
                raise PacketError("invalid BSON document length or terminator")
            try:
                body = BSON(payload).decode()
            except (BSONError, OverflowError, TypeError, ValueError, RecursionError):
                raise PacketError("invalid BSON document") from None
        return cls(header.packet_id, header.method, body, header.status_code, header.body_type)


class PacketDecoder:
    """Incremental plaintext parser; holds at most one bounded wire packet.

    After malformed input it fails closed until reset(). Do not reset and reuse
    an untrusted network connection whose byte alignment is no longer known.
    """

    def __init__(self, *, max_body_size: int = MAX_BODY_SIZE):
        self.max_body_size = _limit(max_body_size)
        self._buffer = bytearray()
        self._expected = HEADER_SIZE
        self._failed = False

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self._expected = HEADER_SIZE
        self._failed = False

    def finish(self) -> None:
        """Check clean end-of-stream, rejecting a truncated final packet."""
        if self._failed or self._buffer:
            raise PacketError("stream ended with invalid or incomplete packet")

    def feed(self, data: bytes | bytearray | memoryview) -> list[LocoPacket]:
        if self._failed:
            raise PacketError("decoder is invalid; close the connection")
        view = memoryview(data)
        packets = []
        position = 0
        try:
            while position < len(view):
                count = min(self._expected - len(self._buffer), len(view) - position)
                self._buffer.extend(view[position : position + count])
                position += count
                if len(self._buffer) < self._expected:
                    break
                if self._expected == HEADER_SIZE:
                    header = LocoPacket.decode_header(
                        self._buffer, max_body_size=self.max_body_size
                    )
                    self._expected = HEADER_SIZE + header.body_length
                    if header.body_length:
                        continue
                packets.append(LocoPacket.decode(self._buffer, max_body_size=self.max_body_size))
                self._buffer.clear()
                self._expected = HEADER_SIZE
        except PacketError:
            self._buffer.clear()
            self._failed = True
            raise
        return packets
