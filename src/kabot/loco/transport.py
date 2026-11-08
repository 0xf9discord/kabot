"""Experimental LOCO stream transport. No native client or credentials are discovered."""

from __future__ import annotations

import asyncio
import math
import ssl
from collections import deque
from dataclasses import dataclass

from .crypto import LocoEncryptor
from .packet import HEADER_SIZE, MAX_BODY_SIZE, LocoPacket, PacketDecoder


class LocoConnectionError(ConnectionError):
    """A connection failed; sending again may duplicate an earlier write."""


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    tls: bool = False
    server_name: str | None = None

    def __post_init__(self):
        if not isinstance(self.host, str) or not self.host or any(c.isspace() for c in self.host):
            raise ValueError("Endpoint host must be a non-empty host name or address")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("Endpoint port must be between 1 and 65535")
        if type(self.tls) is not bool:
            raise ValueError("Endpoint tls must be a boolean")
        if self.server_name is not None:
            if not self.tls or not isinstance(self.server_name, str) or not self.server_name:
                raise ValueError("server_name requires TLS and a nonempty DNS name")
            if any(c.isspace() or c in "/\\:@*" or ord(c) < 32 for c in self.server_name):
                raise ValueError("server_name must be a DNS name, without URL syntax or wildcards")


class LocoTransport:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        encryptor: LocoEncryptor | None,
        idle_timeout: float = 90,
        max_body_size: int = MAX_BODY_SIZE,
    ):
        if not math.isfinite(idle_timeout) or idle_timeout <= 0:
            raise ValueError("idle_timeout must be finite and positive")
        self.reader, self.writer = reader, writer
        self.encryptor = encryptor
        self.idle_timeout = idle_timeout
        self.max_body_size = max_body_size
        self.decoder = PacketDecoder(max_body_size=max_body_size)
        self.ready: deque[LocoPacket] = deque()
        self._write_lock = asyncio.Lock()

    @classmethod
    async def connect(
        cls,
        endpoint: Endpoint,
        *,
        timeout: float = 10,
        idle_timeout: float = 90,
        public_key_der: bytes | None = None,
        max_body_size: int = MAX_BODY_SIZE,
    ) -> LocoTransport:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not math.isfinite(idle_timeout) or idle_timeout <= 0:
            raise ValueError("idle_timeout must be finite and positive")
        PacketDecoder(max_body_size=max_body_size)  # validate bounds before opening a socket
        # TLS always validates the CA chain and host name. No protocol downgrade.
        context = ssl.create_default_context() if endpoint.tls else None
        encryptor = (
            None
            if endpoint.tls
            else LocoEncryptor(
                public_key_der=public_key_der, max_plaintext_size=max_body_size + HEADER_SIZE
            )
        )
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(
                endpoint.host,
                endpoint.port,
                ssl=context,
                server_hostname=(endpoint.server_name or endpoint.host) if context else None,
            )
            transport = cls(
                reader,
                writer,
                encryptor=encryptor,
                idle_timeout=idle_timeout,
                max_body_size=max_body_size,
            )
            try:
                if encryptor is not None:
                    writer.write(encryptor.build_handshake_packet())
                    await writer.drain()
                return transport
            except BaseException:
                await transport.close()
                raise

    async def send(self, packet: LocoPacket) -> None:
        encoded = packet.encode(max_body_size=self.max_body_size)
        async with self._write_lock:
            if self.encryptor is not None:
                encoded = self.encryptor.encrypt(encoded)
            self.writer.write(encoded)
            await self.writer.drain()

    async def receive(self) -> LocoPacket:
        async with asyncio.timeout(self.idle_timeout):
            while not self.ready:
                if self.encryptor is not None:
                    prefix = await self.reader.readexactly(4)
                    length = self.encryptor.frame_body_size(prefix)
                    body = await self.reader.readexactly(length)
                    plaintext = self.encryptor.decrypt(body)
                else:
                    header = await self.reader.readexactly(HEADER_SIZE)
                    parsed = LocoPacket.decode_header(header, max_body_size=self.max_body_size)
                    plaintext = header + await self.reader.readexactly(parsed.body_length)
                self.ready.extend(self.decoder.feed(plaintext))
            return self.ready.popleft()

    async def close(self) -> None:
        self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (OSError, TimeoutError):
            pass
