import asyncio

import pytest

pytest.importorskip("bson")
pytest.importorskip("cryptography")

from bson import Int64

from kabot.loco import LocoConnectionError, LocoPacket, PacketError
from kabot.loco.chats import collect_chats


def test_complete_paginated_list_and_canonical_open_chat_name():
    calls = []

    class Session:
        async def request(self, method, body):
            calls.append((method, body))
            if method == "LCHATLIST":
                assert isinstance(body["lastTokenId"], Int64)
                if body["lastChatId"] == 0:
                    return LocoPacket(
                        1,
                        method,
                        {
                            "chatDatas": [{"c": Int64(2), "t": "OM", "s": Int64(12)}],
                            "eof": False,
                            "lastTokenId": Int64(42),
                            "lastChatId": Int64(2),
                        },
                    )
                assert body["lastTokenId"] == 42 and body["lastChatId"] == 2
                return LocoPacket(
                    2, method, {"chatDatas": [{"c": Int64(3), "t": "MultiChat"}], "eof": True}
                )
            if method == "CHATINFO":
                identity = body["chatId"]
                assert isinstance(identity, Int64)
                if identity == 1:
                    info = {
                        "chatId": identity,
                        "type": "DirectChat",
                        "displayMembers": [{"nickName": "회원"}],
                    }
                elif identity == 2:
                    info = {
                        "chatId": identity,
                        "type": "OM",
                        "li": Int64(500),
                        "lastLogId": Int64(15),
                    }
                else:
                    info = {
                        "chatId": identity,
                        "type": "MultiChat",
                        "chatMetas": [{"type": Int64(3), "content": "공식 방 제목"}],
                    }
                return LocoPacket(3, method, {"chatInfo": info})
            assert method == "INFOLINK"
            assert body == {"lis": [Int64(500)]}
            return LocoPacket(4, method, {"ols": [{"ln": "2026testkakao"}]})

    rows = asyncio.run(
        collect_chats(Session(), {"chatDatas": [{"c": Int64(1), "t": "DirectChat"}]})
    )
    by_id = {row["c"]: row for row in rows}
    assert set(by_id) == {1, 2, 3}
    assert by_id[2]["chatInfo"]["name"] == "2026testkakao"
    assert by_id[2]["s"] == 15  # don't replay an earlier command during selection
    assert by_id[3]["chatInfo"]["name"] == "공식 방 제목"
    assert by_id[1]["k"] == ["회원"]
    assert all(method not in {"WRITE", "CHATONROOM", "NOTIREAD"} for method, _ in calls)


@pytest.mark.parametrize("max_pages", [1, 2])
def test_pagination_must_advance_and_is_bounded(max_pages):
    class Session:
        calls = 0

        async def request(self, method, body):
            self.calls += 1
            return LocoPacket(
                1,
                method,
                {"chatDatas": [{"c": 1}], "eof": False, "lastTokenId": 0, "lastChatId": 0},
            )

    session = Session()
    with pytest.raises(LocoConnectionError):
        asyncio.run(collect_chats(session, {}, max_pages=max_pages))
    assert session.calls == 1


def test_detail_identity_mismatch_is_rejected():
    class Session:
        async def request(self, method, body):
            if method == "LCHATLIST":
                return LocoPacket(1, method, {"chatDatas": [{"c": Int64(2)}], "eof": True})
            return LocoPacket(2, method, {"chatInfo": {"chatId": Int64(999), "name": "wrong"}})

    with pytest.raises(PacketError):
        asyncio.run(collect_chats(Session(), {}))
