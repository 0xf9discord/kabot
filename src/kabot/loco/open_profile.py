"""Open-chat profile switching; schemas from node-kakao 8512e469 (MIT).

This changes the profile used in an existing room, not the underlying account
profile or a saved open profile. No image upload or automatic write retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from bson import Int64

from .client import positive_id
from .packet import PacketError


@dataclass(frozen=True)
class OpenChatProfile:
    kind: Literal["main", "anonymous", "link"]
    nickname: str | None = field(default=None, repr=False)
    profile_path: str | None = field(default=None, repr=False)
    profile_link_id: int | None = None

    def __post_init__(self):
        if self.kind == "main":
            if any(v is not None for v in (self.nickname, self.profile_path, self.profile_link_id)):
                raise ValueError("Main profile does not accept nickname, path or link ID")
        elif self.kind == "link":
            positive_id(self.profile_link_id, "profile_link_id")
            if self.nickname is not None or self.profile_path is not None:
                raise ValueError("Link profile does not accept nickname or path")
        elif self.kind == "anonymous":
            if self.profile_link_id is not None:
                raise ValueError("Anonymous profile does not accept a link ID")
            if (
                not isinstance(self.nickname, str)
                or not self.nickname.strip()
                or len(self.nickname) > 100
                or any(not c.isprintable() for c in self.nickname)
            ):
                raise ValueError("Nickname must contain 1..100 printable characters")
            path = self.profile_path
            if (
                not isinstance(path, str)
                or not path.strip()
                or len(path) > 2048
                or any(not c.isprintable() for c in path)
                or ":" in path
                or "\\" in path
                or path.startswith("//")
            ):
                raise ValueError(
                    "profile_path must be an existing Kakao image path, not a URL/file"
                )
        else:
            raise ValueError("Profile kind must be main, anonymous or link")

    @classmethod
    def main(cls) -> OpenChatProfile:
        return cls("main")

    @classmethod
    def anonymous(cls, nickname: str, profile_path: str) -> OpenChatProfile:
        return cls("anonymous", nickname=nickname, profile_path=profile_path)

    @classmethod
    def link(cls, profile_link_id: int) -> OpenChatProfile:
        return cls("link", profile_link_id=profile_link_id)

    def to_body(self) -> dict:
        if self.kind == "main":
            return {"ptp": 1}
        if self.kind == "link":
            return {"ptp": 16, "pli": positive_id(self.profile_link_id, "profile_link_id")}
        return {"ptp": 2, "nn": self.nickname, "pp": self.profile_path}


async def room_link_id(session, chat_id: int) -> Int64:
    chat_id = positive_id(chat_id, "chat_id")
    response = await session.request("CHATINFO", {"chatId": chat_id})
    info = response.body.get("chatInfo")
    if not isinstance(info, dict):
        raise PacketError("CHATINFO has no chatInfo document")
    if "chatId" in info:
        try:
            returned = positive_id(info["chatId"], "chat_id")
        except ValueError:
            raise PacketError("CHATINFO contains an invalid chat ID") from None
        if returned != chat_id:
            raise PacketError("CHATINFO returned a different room")
    try:
        return positive_id(info.get("li"), "room_link_id")
    except ValueError:
        raise ValueError("The selected room has no valid open-chat link ID") from None


async def collect_open_links(session) -> list[dict]:
    """Fetch account-associated links from a fresh sync, including saved profiles."""
    response = await session.request("SYNCLINK", {"ltk": 0})
    rows = response.body.get("ols", [])
    if not isinstance(rows, list):
        raise PacketError("SYNCLINK ols must be a list")
    for row in rows:
        if not isinstance(row, dict):
            raise PacketError("SYNCLINK contains an invalid link")
        try:
            positive_id(row.get("li"), "link_id")
        except ValueError:
            raise PacketError("SYNCLINK contains an invalid link ID") from None
    return rows
