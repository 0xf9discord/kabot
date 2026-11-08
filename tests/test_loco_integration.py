"""Real loopback TCP with RSA handshake/AES-GCM; never contacts Kakao servers."""

import asyncio
import struct

import pytest

pytest.importorskip("bson")
pytest.importorskip("cryptography")

from bson import Int64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kabot import Bot
from kabot.loco import (
    Credentials,
    Endpoint,
    LocoEncryptor,
    LocoPacket,
    LocoStatusError,
    LocoTransport,
    PacketDecoder,
    PersonalClient,
    received_messages,
    run_personal_bot,
)

USER = 1234567890123456
CHAT = 9007199254740997
AUTHOR = 9007199254740999


def test_full_discovery_authentication_push_to_command_reply_over_encrypted_tcp():
    async def run():
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        writes, endpoints, server_errors = [], [], []
        replied = asyncio.Event()
        peers = set()

        async def peer(reader, writer):
            peers.add(writer)
            try:
                header = await reader.readexactly(12)
                assert struct.unpack("<III", header) == (256, 16, 3)
                key = private.decrypt(
                    await reader.readexactly(256),
                    padding.OAEP(
                        mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None
                    ),
                )
                cipher = LocoEncryptor(key=key, public_key_der=public)
                decoder = PacketDecoder()

                async def send(packet):
                    raw = packet.encode()
                    # A single LOCO header may cross encrypted record boundaries.
                    writer.write(cipher.encrypt(raw[:9]) + cipher.encrypt(raw[9:]))
                    await writer.drain()

                async def push(log, *, chat=CHAT, author=AUTHOR, message="/echo hello", kind=1):
                    await send(
                        LocoPacket(
                            0,
                            "MSG",
                            {
                                "chatId": Int64(chat),
                                "chatLog": {
                                    "logId": Int64(log),
                                    "authorId": Int64(author),
                                    "type": kind,
                                    "message": message,
                                },
                            },
                        )
                    )

                while True:
                    prefix = await reader.readexactly(4)
                    frame = await reader.readexactly(cipher.frame_body_size(prefix))
                    for packet in decoder.feed(cipher.decrypt(frame)):
                        if packet.method == "GETCONF":
                            assert isinstance(packet.body["userId"], Int64)
                            await send(
                                LocoPacket(
                                    packet.packet_id,
                                    packet.method,
                                    {"ticket": {"lsl": ["ticket.test"]}},
                                )
                            )
                        elif packet.method == "CHECKIN":
                            await send(
                                LocoPacket(
                                    packet.packet_id,
                                    packet.method,
                                    {"host": "chat.test", "port": 995},
                                )
                            )
                        elif packet.method == "LOGINLIST":
                            assert packet.body["oauthToken"] == "local-test-token"
                            assert packet.body["duuid"] == "local-test-device"
                            assert isinstance(packet.body["lastTokenId"], Int64)
                            await push(100, author=USER)
                            await push(101, chat=CHAT + 1)
                            await push(102, message="ordinary chat")
                            await push(103)
                            await push(103)  # same message redelivered
                            await push(104, kind=2)
                            await send(
                                LocoPacket(
                                    packet.packet_id,
                                    packet.method,
                                    {"userId": Int64(USER), "chatDatas": []},
                                )
                            )
                        elif packet.method == "CHATONROOM":
                            assert packet.body["chatId"] == CHAT
                            assert isinstance(packet.body["chatId"], Int64)
                            await send(
                                LocoPacket(packet.packet_id, packet.method, {"t": "MultiChat"})
                            )
                        elif packet.method == "WRITE":
                            writes.append(packet.body)
                            await send(
                                LocoPacket(
                                    packet.packet_id,
                                    packet.method,
                                    {"logId": Int64(9007199254741100)},
                                )
                            )
                            replied.set()
                        else:
                            raise AssertionError(packet.method)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                pass
            except Exception as exc:
                server_errors.append(exc)
            finally:
                peers.discard(writer)
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(peer, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def connector(endpoint):
            endpoints.append(endpoint)
            return await LocoTransport.connect(Endpoint("127.0.0.1", port), public_key_der=public)

        creds = Credentials(USER, "local-test-token", "local-test-device", "test-profile")
        client = PersonalClient(creds, connector=connector)
        bot = Bot()

        @bot.command("echo")
        async def echo(ctx):
            assert ctx.metadata["chat_id"] == CHAT
            return ctx.args

        runner = None
        try:
            async with client:
                result = await client.connect()
                assert result["userId"] == USER
                runner = asyncio.create_task(run_personal_bot(bot, client, chat_ids={CHAT}))
                await asyncio.wait_for(replied.wait(), 3)
                await asyncio.sleep(0.03)
                assert writes == [
                    {"chatId": Int64(CHAT), "msg": "hello", "type": 1, "noSeen": False}
                ]
                assert endpoints == [
                    Endpoint("booking-loco.kakao.com", 443, True),
                    Endpoint("ticket.test", 995),
                    Endpoint("chat.test", 995),
                ]
                assert not server_errors
        finally:
            if runner:
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
            await client.close()
            for writer in list(peers):
                writer.close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_nested_and_batch_message_validation():
    row = {
        "chatId": Int64(CHAT),
        "logId": Int64(9007199254741000),
        "authorId": Int64(AUTHOR),
        "type": 1,
        "message": "hi",
    }
    packets = [
        LocoPacket(0, "MSG", row),
        LocoPacket(0, "MSG", {"chatId": Int64(CHAT), "chatLog": row}),
        LocoPacket(0, "SYNCMSG", {"chatId": Int64(CHAT), "chatLogs": [row, row]}),
    ]
    assert [len(received_messages(packet)) for packet in packets] == [1, 1, 2]
    assert received_messages(packets[0])[0].chat_id == CHAT
    for body in [
        {"chatId": CHAT + 1, "chatLog": row},
        {"chatLog": []},
        {"chatLogs": [row, {**row, "authorId": True}]},
    ]:
        with pytest.raises(ValueError):
            received_messages(LocoPacket(0, "SYNCMSG", body))
    assert "local-test-token" not in repr(Credentials(USER, "local-test-token", "device", "test"))


def test_login_rejection_is_not_retried():
    from test_loco_session import FakeTransport

    async def run():
        transport = FakeTransport()
        count = 0

        async def connector(endpoint):
            nonlocal count
            count += 1
            return transport

        client = PersonalClient(Credentials(USER, "token", "device", "test"), connector=connector)
        task = asyncio.create_task(client.connect(endpoint=Endpoint("local.test", 995)))
        login = await transport.sent.get()
        await transport.incoming.put(LocoPacket(login.packet_id, "LOGINLIST", {}, status_code=-950))
        with pytest.raises(LocoStatusError):
            await task
        assert count == 1 and transport.closed and client.session is None
        assert transport.sent.empty()
        await client.close()

    asyncio.run(run())
