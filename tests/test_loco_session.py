import asyncio

import pytest

pytest.importorskip("bson")
pytest.importorskip("cryptography")

from kabot.loco import EventOverflowError, LocoPacket, LocoSession, LocoStatusError


class FakeTransport:
    max_body_size = 4096

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = asyncio.Queue()
        self.closed = False

    async def send(self, packet):
        await self.sent.put(packet)

    async def receive(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True


def test_concurrent_response_ids_interleaved_pushes_and_signed_errors():
    async def run():
        transport = FakeTransport()
        async with LocoSession(transport) as session:
            first = asyncio.create_task(session.request("FIRST"))
            second = asyncio.create_task(session.request("SECOND"))
            a, b = await transport.sent.get(), await transport.sent.get()
            await transport.incoming.put(LocoPacket(0, "MSG", {"text": "push"}))
            await transport.incoming.put(LocoPacket(b.packet_id, "SECOND", {"value": 2}))
            await transport.incoming.put(LocoPacket(a.packet_id, "FIRST", {"value": 1}))
            assert (await first).body["value"] == 1
            assert (await second).body["value"] == 2
            assert (await session.next_event()).body["text"] == "push"
            bad = asyncio.create_task(session.request("LOGINLIST"))
            packet = await transport.sent.get()
            await transport.incoming.put(
                LocoPacket(packet.packet_id, "LOGINLIST", {}, status_code=-950)
            )
            with pytest.raises(LocoStatusError) as failure:
                await bad
            assert failure.value.status == -950
            assert transport.sent.empty()  # no automatic retry
            assert not session.closed  # server rejection does not corrupt framing
        assert transport.closed

    asyncio.run(run())


def test_timeout_and_cancellation_close_connection_without_resending():
    async def run():
        for cancel in (False, True):
            transport = FakeTransport()
            session = LocoSession(transport, command_timeout=0.03)
            request = asyncio.create_task(session.request("WRITE", {"msg": "test"}))
            assert (await transport.sent.get()).method == "WRITE"
            if cancel:
                request.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
                await request
            assert session.closed and transport.closed
            assert transport.sent.empty()
            assert not session._pending

    asyncio.run(run())


def test_event_overflow_is_visible_after_preserved_events():
    async def run():
        transport = FakeTransport()
        session = LocoSession(transport, event_capacity=1)
        await transport.incoming.put(LocoPacket(0, "MSG", {"value": 1}))
        await transport.incoming.put(LocoPacket(0, "MSG", {"value": 2}))
        await asyncio.wait_for(session._reader_task, 1)
        assert (await session.next_event()).body["value"] == 1
        with pytest.raises(EventOverflowError):
            await session.next_event()
        await session.close()

    asyncio.run(run())


def test_invalid_packet_does_not_write_or_poison_session():
    async def run():
        transport = FakeTransport()
        async with LocoSession(transport) as session:
            with pytest.raises(ValueError):
                await session.request("TOO_LONG_COMMAND", {})
            assert transport.sent.empty()
            assert not session.closed
            assert not session._pending

    asyncio.run(run())
