"""One reader dispatches response IDs and preserves interleaved push events."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from .packet import LocoPacket
from .transport import LocoConnectionError, LocoTransport


class LocoStatusError(Exception):
    def __init__(self, method: str, status: int):
        self.method, self.status = method, status
        super().__init__(f"LOCO {method} failed (status={status})")


class EventOverflowError(LocoConnectionError):
    """The event consumer fell behind; the connection closes instead of dropping silently."""


@dataclass
class Pending:
    method: str
    future: asyncio.Future


class LocoSession:
    def __init__(
        self, transport: LocoTransport, *, command_timeout: float = 10, event_capacity: int = 256
    ):
        if not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("command_timeout must be finite and positive")
        if type(event_capacity) is not int or event_capacity < 1:
            raise ValueError("event_capacity must be positive")
        self.transport, self.command_timeout = transport, command_timeout
        self._pending: dict[int, Pending] = {}
        self._events: asyncio.Queue[LocoPacket] = asyncio.Queue(event_capacity)
        self._closed = asyncio.Event()
        self._error: BaseException = LocoConnectionError("Session closed")
        self._next_id = 1
        self._reader_task = asyncio.create_task(self._read_loop(), name="kabot-loco-reader")

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def _finish(self, error: BaseException) -> None:
        if not self.closed:
            self._error = error
            self._closed.set()
            for pending in self._pending.values():
                if not pending.future.done():
                    pending.future.set_exception(error)

    async def _read_loop(self) -> None:
        try:
            while True:
                packet = await self.transport.receive()
                pending = self._pending.get(packet.packet_id)
                if pending is not None:
                    if packet.method != pending.method:
                        raise LocoConnectionError("Response method does not match request")
                    if not pending.future.done():
                        pending.future.set_result(packet)
                else:
                    try:
                        self._events.put_nowait(packet)
                    except asyncio.QueueFull:
                        raise EventOverflowError(
                            "LOCO event queue full; connection stopped"
                        ) from None
        except asyncio.CancelledError:
            self._finish(LocoConnectionError("Session closed"))
        except Exception as exc:
            # Exception text never includes packet bodies or session credentials.
            error = (
                exc
                if isinstance(exc, EventOverflowError)
                else LocoConnectionError(f"LOCO receive failed ({type(exc).__name__})")
            )
            self._finish(error)
        finally:
            await self.transport.close()

    async def request(self, method: str, body: dict[str, Any] | None = None) -> LocoPacket:
        if self.closed:
            raise self._error
        packet_id = self._next_id
        self._next_id += 1
        if self._next_id >= 0xFFFFFFFF:
            self._next_id = 1
        while packet_id in self._pending:
            packet_id = self._next_id
            self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[packet_id] = Pending(method, future)
        # Encode before entering the send path so validation failures cannot mutate wire state.
        packet = LocoPacket(packet_id, method, body or {})
        try:
            packet.encode(max_body_size=self.transport.max_body_size)
            async with asyncio.timeout(self.command_timeout):
                try:
                    await self.transport.send(packet)
                    result = await future
                except BaseException:
                    # A canceled/partial send makes connection state ambiguous. No auto retries.
                    await self.close()
                    raise
            if result.status != 0:
                raise LocoStatusError(method, result.status)
            return result
        finally:
            self._pending.pop(packet_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # consume a concurrent close failure on canceled request

    async def next_event(self) -> LocoPacket:
        if not self._events.empty():
            return self._events.get_nowait()
        if self.closed:
            raise self._error
        event = asyncio.create_task(self._events.get())
        closed = asyncio.create_task(self._closed.wait())
        try:
            await asyncio.wait((event, closed), return_when=asyncio.FIRST_COMPLETED)
            if event.done():
                return event.result()
            raise self._error
        finally:
            for task in (event, closed):
                if not task.done():
                    task.cancel()
            await asyncio.gather(event, closed, return_exceptions=True)

    async def events(self) -> AsyncIterator[LocoPacket]:
        """One consumer per session. Disconnect errors are surfaced, never silently ignored."""
        while True:
            yield await self.next_event()

    async def close(self) -> None:
        self._finish(LocoConnectionError("Session closed"))
        if self._reader_task is not asyncio.current_task():
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)

    async def __aenter__(self) -> LocoSession:
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()
