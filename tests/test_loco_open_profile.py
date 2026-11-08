import asyncio

import pytest

pytest.importorskip("bson")
pytest.importorskip("cryptography")

from bson import Int64

from kabot.loco import (
    Credentials,
    LocoPacket,
    LocoStatusError,
    OpenChatProfile,
    PacketError,
    PersonalClient,
)


class Session:
    closed = False

    def __init__(self, info=None, *, fail_write=False):
        self.calls = []
        self.info = info if info is not None else {"chatId": Int64(7), "li": Int64(2**60)}
        self.fail_write = fail_write

    async def request(self, method, body):
        self.calls.append((method, body))
        if method == "CHATINFO":
            return LocoPacket(1, method, {"chatInfo": self.info})
        if method == "UPLINKPROF":
            if self.fail_write:
                raise LocoStatusError(method, -203)
            return LocoPacket(2, method, {"status": 0})
        if method == "SYNCLINK":
            return LocoPacket(3, method, {"ols": [{"li": Int64(2**60 + 1), "ln": "봇"}]})
        assert method == "MEMBER"
        return LocoPacket(
            4, method, {"chatId": Int64(7), "members": [{"userId": Int64(8), "nickName": "봇"}]}
        )


def client_with(session):
    client = PersonalClient(Credentials(8, "token", "uuid", "26.8.2", "android"))
    client.session = session
    return client


@pytest.mark.parametrize(
    "profile,expected",
    [
        (OpenChatProfile.main(), {"ptp": 1}),
        (
            OpenChatProfile.anonymous("봇", "/existing/image"),
            {"ptp": 2, "nn": "봇", "pp": "/existing/image"},
        ),
        (OpenChatProfile.link(2**60 + 1), {"ptp": 16, "pli": Int64(2**60 + 1)}),
    ],
)
def test_switch_uses_room_link_not_chat_id_and_preserves_int64(profile, expected):
    session = Session()
    assert asyncio.run(client_with(session).change_open_profile(7, profile)) == {"status": 0}
    assert session.calls == [
        ("CHATINFO", {"chatId": Int64(7)}),
        ("UPLINKPROF", {"li": Int64(2**60), **expected}),
    ]
    assert isinstance(session.calls[0][1]["chatId"], Int64)
    assert isinstance(session.calls[1][1]["li"], Int64)
    if profile.kind == "link":
        assert isinstance(session.calls[1][1]["pli"], Int64)


@pytest.mark.parametrize(
    "info", [{"chatId": 9, "li": 100}, {"chatId": True, "li": 100}, {"chatId": 7}, {"li": True}]
)
def test_rejects_wrong_or_non_open_room_before_mutation(info):
    session = Session(info)
    with pytest.raises((ValueError, PacketError)):
        asyncio.run(client_with(session).change_open_profile(7, OpenChatProfile.main()))
    assert [method for method, _ in session.calls] == ["CHATINFO"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "other"},
        {"kind": "main", "nickname": "oops"},
        {"kind": "link", "profile_link_id": True},
        {"kind": "link", "profile_link_id": 2**63},
        {"kind": "anonymous", "nickname": "x", "profile_path": "https://example.com/a"},
        {"kind": "anonymous", "nickname": "x", "profile_path": "C:\\photo.png"},
        {"kind": "anonymous", "nickname": "x\n", "profile_path": "/a"},
        {"kind": "anonymous", "nickname": "", "profile_path": "/a"},
    ],
)
def test_invalid_profile_rejected_locally(kwargs):
    with pytest.raises(ValueError):
        OpenChatProfile(**kwargs)


def test_profile_queries_are_read_only():
    session = Session()
    client = client_with(session)
    assert asyncio.run(client.list_open_links())[0]["li"] == 2**60 + 1
    assert asyncio.run(client.get_open_profile(7))["nickName"] == "봇"
    assert [method for method, _ in session.calls] == ["SYNCLINK", "CHATINFO", "MEMBER"]
    assert isinstance(session.calls[-1][1]["memberIds"][0], Int64)


def test_loop_rotates_exact_count_without_final_sleep(monkeypatch):
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    session = Session()
    client = client_with(session)
    count = asyncio.run(
        client.loopchange(
            7, [OpenChatProfile.main(), OpenChatProfile.link(100)], interval=3, max_changes=3
        )
    )
    assert count == 3
    assert [body["ptp"] for method, body in session.calls if method == "UPLINKPROF"] == [1, 16, 1]
    assert sleeps == [3, 3]


def test_loop_server_error_stops_without_retry():
    session = Session(fail_write=True)
    with pytest.raises(LocoStatusError):
        asyncio.run(client_with(session).loopchange(7, [OpenChatProfile.main()], max_changes=4))
    assert [method for method, _ in session.calls].count("UPLINKPROF") == 1


def test_loop_uncertain_write_never_retries():
    class UncertainSession(Session):
        async def request(self, method, body):
            if method == "UPLINKPROF":
                self.calls.append((method, body))
                raise TimeoutError("Response lost after request was sent")
            return await super().request(method, body)

    session = UncertainSession()
    with pytest.raises(TimeoutError):
        asyncio.run(client_with(session).loopchange(7, [OpenChatProfile.main()], max_changes=4))
    assert [method for method, _ in session.calls].count("UPLINKPROF") == 1


def test_loop_stop_event_interrupts_long_wait():
    async def run():
        event = asyncio.Event()
        session = Session()
        client = client_with(session)
        original = client.change_open_profile

        async def change(*args):
            result = await original(*args)
            event.set()
            return result

        client.change_open_profile = change
        assert (
            await asyncio.wait_for(
                client.loopchange(7, [OpenChatProfile.main()], interval=3600, stop_event=event),
                timeout=1,
            )
            == 1
        )
        assert len(session.calls) == 2
        assert await client.loopchange(7, [OpenChatProfile.main()], stop_event=event) == 0

    asyncio.run(run())


def test_loop_task_cancellation_stops_future_writes():
    async def run():
        session = Session()
        task = asyncio.create_task(
            client_with(session).loopchange(7, [OpenChatProfile.main()], interval=3600)
        )
        await asyncio.sleep(0)
        assert len(session.calls) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(session.calls) == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "options",
    [{"interval": 0}, {"interval": float("nan")}, {"max_changes": True}, {"max_changes": 0}],
)
def test_loop_rejects_bad_options_before_network(options):
    session = Session()
    with pytest.raises(ValueError):
        asyncio.run(client_with(session).loopchange(7, [OpenChatProfile.main()], **options))
    assert not session.calls
