"""Read-only chat pagination and canonical names from LCHATLIST/CHATINFO/INFOLINK.

Field semantics follow pinned agent-messenger protocol/session.ts and client.ts.
No CHATONROOM, NOTIREAD, joins or writes are used for listing.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from bson import Int64

from .packet import PacketError
from .session import LocoStatusError
from .transport import LocoConnectionError


def _number(value: Any, *, positive=False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value) if (1 if positive else 0) <= value < 2**63 else None


def chat_id(row) -> int | None:
    return (
        _number(row.get("c", row.get("chatId")), positive=True) if isinstance(row, dict) else None
    )


def _canonical_title(info: dict) -> str | None:
    metas = info.get("chatMetas")
    if isinstance(metas, list):
        for meta in metas:
            if isinstance(meta, dict) and _number(meta.get("type")) == 3:
                content = meta.get("content")
                if isinstance(content, str) and content.strip():
                    return content
    name = info.get("name")
    return name if isinstance(name, str) and name.strip() else None


def _open_room(row) -> bool:
    kind = row.get("t", row.get("type", ""))
    return isinstance(kind, str) and (kind.casefold() in {"om", "od"} or "open" in kind.casefold())


async def collect_chats(
    session, login_data: dict, *, resolve_names=True, max_pages=10, max_chats=500
) -> list[dict]:
    if type(max_pages) is not int or not 1 <= max_pages <= 50:
        raise ValueError("max_pages must be between 1 and 50")
    if type(max_chats) is not int or not 1 <= max_chats <= 5000:
        raise ValueError("max_chats must be between 1 and 5000")
    rows: dict[int, dict] = {}

    def merge(page):
        if not isinstance(page, list):
            raise PacketError("Chat list has no chatDatas array")
        for row in page:
            identity = chat_id(row)
            if identity is not None:
                rows[identity] = {**rows.get(identity, {}), **deepcopy(row)}
                if len(rows) > max_chats:
                    raise LocoConnectionError("Chat list exceeds configured room limit")

    merge(login_data.get("chatDatas", []))
    cursor = (0, 0)
    for _ in range(max_pages):
        result = await session.request(
            "LCHATLIST",
            {
                "chatIds": [],
                "maxIds": [],
                "lastTokenId": Int64(cursor[0]),
                "lastChatId": Int64(cursor[1]),
            },
        )
        body = result.body
        page = body.get("chatDatas")
        merge(page)
        if body.get("eof") is True:
            break
        token, last = _number(body.get("lastTokenId")), _number(body.get("lastChatId"))
        if not page or token is None or last is None or (token, last) == cursor:
            raise LocoConnectionError("Chat pagination did not provide an advancing cursor")
        cursor = (token, last)
    else:
        raise LocoConnectionError("Chat pagination exceeded max_pages before EOF")
    if not resolve_names:
        return list(rows.values())
    link_names: dict[int, str] = {}
    for identity, row in rows.items():
        try:
            result = await session.request("CHATINFO", {"chatId": Int64(identity)})
        except LocoStatusError:
            continue
        info = result.body.get("chatInfo")
        if not isinstance(info, dict):
            continue
        if "chatId" in info and _number(info["chatId"], positive=True) != identity:
            raise PacketError("CHATINFO identity conflicts with the requested room")
        previous = row.get("chatInfo") if isinstance(row.get("chatInfo"), dict) else {}
        details = {**previous, **deepcopy(info)}
        row["chatInfo"] = details
        if isinstance(info.get("type"), str):
            row["t"] = info["type"]
        latest = _number(info.get("lastLogId"))
        if latest is not None:
            row["s"] = Int64(max(latest, _number(row.get("s")) or 0))
        title = _canonical_title(info)
        link = _number(info.get("li", row.get("li")), positive=True)
        if title is None and _open_room(row) and link is not None:
            if link not in link_names:
                try:
                    links = await session.request("INFOLINK", {"lis": [Int64(link)]})
                except LocoStatusError:
                    links = None
                items = links.body.get("ols") if links is not None else None
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    name = items[0].get("ln")
                    if isinstance(name, str) and name.strip():
                        link_names[link] = name
            title = link_names.get(link)
        if title:
            details["name"] = title
        elif isinstance(info.get("displayMembers"), list):
            names = [
                member.get("nickName")
                for member in info["displayMembers"]
                if isinstance(member, dict) and isinstance(member.get("nickName"), str)
            ]
            if names:
                row["k"] = names
    return list(rows.values())
