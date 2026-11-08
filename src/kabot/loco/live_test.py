"""A local-user-approved, bounded, single-reply personal bot validation."""

from __future__ import annotations

import asyncio
import getpass
import math
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .client import PersonalClient
from .interactive import LoginStatus, unlock_session

TEST_REPLY = "퐁! Kabot 연결 테스트 성공."


class ReplyTestWriteError(RuntimeError):
    """A single write was attempted; its delivery is uncertain and is not retried."""


@dataclass(frozen=True)
class _Room:
    chat_id: int
    title: str
    last_log_id: int
    open_chat: bool = False


def _safe_text(value: str) -> str:
    return "".join(character for character in value if character.isprintable())[:120]


def _is_open(row: dict) -> bool:
    return any(
        isinstance(kind, str) and (kind.casefold() in {"om", "od"} or "open" in kind.casefold())
        for kind in (row.get("t"), row.get("type"))
    )


def _unsupported_kind(row: dict, *, allow_open: bool = False) -> str | None:
    for kind in (row.get("t"), row.get("type")):
        if isinstance(kind, str):
            name = kind.casefold()
            if any(word in name for word in ("memo", "secret")) or (
                not allow_open and (name in {"om", "od"} or "open" in name)
            ):
                return _safe_text(kind)
    return None


def _row_title(row: dict) -> str:
    details = row.get("chatInfo")
    title = details.get("name") if isinstance(details, dict) else None
    if not isinstance(title, str) or not title.strip():
        members = row.get("k")
        title = (
            ", ".join(item for item in members if isinstance(item, str))
            if isinstance(members, list)
            else None
        )
    if not isinstance(title, str) or not title.strip():
        title = next(
            (
                row[key]
                for key in ("title", "name")
                if isinstance(row.get(key), str) and row[key].strip()
            ),
            "이름 없는 채팅방",
        )
    return _safe_text(title)


def _rooms(rows, *, allow_open: bool = False) -> list[_Room]:
    if not isinstance(rows, list):
        raise ValueError("Server chat listing did not return a list")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        chat_id = row.get("c", row.get("chatId"))
        if isinstance(chat_id, bool) or not isinstance(chat_id, int) or not 0 < chat_id < 2**63:
            continue
        if _unsupported_kind(row, allow_open=allow_open) is not None or chat_id in seen:
            continue
        last = row.get("s", row.get("lastLogId", 0))
        if isinstance(last, dict):
            last = last.get("logId", last.get("lastLogId", 0))
        if isinstance(last, bool) or not isinstance(last, int) or not 0 <= last < 2**63:
            continue
        seen.add(chat_id)
        result.append(_Room(int(chat_id), _row_title(row), int(last), _is_open(row)))
    return result


async def run_reply_test(
    session_path,
    *,
    status_path=None,
    input_fn=input,
    secret_fn=getpass.getpass,
    print_fn=print,
    client_factory=PersonalClient,
    timeout=300,
    target_name: str | None = None,
    allow_open: bool = False,
):
    """Unlock once, choose a room locally, require START, reply once to new /핑.

    The status file contains phases/counts only. Room identity/title and the exact
    reply are displayed solely through the local print function for user review.
    A failed or timed-out write is ambiguous, is surfaced as ReplyTestWriteError,
    and is never replayed by this runner.
    """
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if target_name is not None and (not isinstance(target_name, str) or not target_name.strip()):
        raise ValueError("target_name must be a nonempty name or None")
    if type(allow_open) is not bool:
        raise ValueError("allow_open must be bool")
    status = LoginStatus(Path(status_path) if status_path else None)
    chat_count = supported_count = replies_sent = send_attempts = 0
    target_matches = supported_target_matches = 0

    def update(phase, **fields):
        status.update(
            phase,
            chat_count=chat_count,
            supported_chat_count=supported_count,
            target_match_count=target_matches,
            supported_target_match_count=supported_target_matches,
            replies_sent=replies_sent,
            send_attempts=send_attempts,
            **fields,
        )

    async def ask(prompt):
        return await asyncio.to_thread(input_fn, prompt)

    try:
        update("waiting_for_session_unlock")
        credentials = await unlock_session(session_path, secret_fn=secret_fn)
        update("connecting")
        async with client_factory(credentials) as client:
            await client.connect()
            status.authenticated = True
            update("loading_chats")
            print_fn("서버 채팅방 목록과 방 이름을 불러오는 중입니다.")
            rows = await client.list_chats(resolve_names=True)
            choices = _rooms(rows, allow_open=allow_open)
            chat_count, supported_count = len(rows), len(choices)
            print_fn(
                f"서버에서 확인한 채팅방 {chat_count}개, "
                f"테스트 가능한 방 {supported_count}개입니다."
            )
            if target_name is not None:
                target = _safe_text(target_name).strip().casefold()
                matching_rows = [
                    row
                    for row in rows
                    if isinstance(row, dict) and _row_title(row).strip().casefold() == target
                ]
                target_matches = len(matching_rows)
                supported_target_matches = sum(
                    room.title.strip().casefold() == target for room in choices
                )
                if target_matches and not supported_target_matches:
                    kinds = {_unsupported_kind(row, allow_open=allow_open) for row in matching_rows}
                    if None not in kinds:
                        print_fn(
                            f"찾는 방 '{_safe_text(target_name)}'은 "
                            "이 테스트가 지원하지 않는 유형입니다: "
                            f"{', '.join(sorted(kinds))}"
                        )
                    else:
                        print_fn(
                            "찾는 방은 서버 목록에 있지만 "
                            "현재 테스트에서 선택할 수 없는 항목입니다."
                        )
                elif not target_matches:
                    print_fn(
                        f"찾는 방 '{_safe_text(target_name)}'을 "
                        "서버가 제공한 이름에서 찾지 못했습니다."
                    )
                    print_fn(
                        "봇 계정의 해당 방 참여 여부를 확인하세요. "
                        "기기에만 저장된 별명은 서버가 제공하지 않을 수 있습니다."
                    )
                else:
                    print_fn(
                        f"찾는 이름과 일치하는 선택 가능한 방 {supported_target_matches}개를 "
                        "아래에서 직접 선택하세요."
                    )
            if not choices:
                update("no_supported_chats")
                print_fn("현재 설정으로 테스트할 수 있는 채팅방이 없습니다.")
                return 0
            update("waiting_for_room_selection")
            print_fn("연결 테스트에 사용할 채팅방을 한 개 선택하세요.")
            for index, room in enumerate(choices, 1):
                kind_label = "오픈채팅" if room.open_chat else "일반채팅"
                print_fn(f"{index}. [{kind_label}] {room.title} (chat_id={room.chat_id})")
            selected = await ask("방 번호 (취소는 q): ")
            if not isinstance(selected, str) or not selected.strip().isdigit():
                update("canceled")
                return 0
            position = int(selected.strip())
            if not 1 <= position <= len(choices):
                update("canceled")
                return 0
            room = choices[position - 1]
            print_fn(f"선택한 방: {room.title} (chat_id={room.chat_id})")
            print_fn(f"이 방의 다른 사용자가 새로 /핑 을 보내면 딱 한 번 보낼 답장: {TEST_REPLY}")
            update("waiting_for_start")
            approval = await ask("위 방과 답장을 확인했습니다. 시작하려면 START 입력: ")
            if not isinstance(approval, str) or approval.casefold() != "start":
                update("canceled")
                return 0
            update("waiting_for_command")
            print_fn("대기 중: 선택한 방의 다른 계정에서 /핑 을 새로 보내세요.")
            seen: OrderedDict[int, None] = OrderedDict()
            async with asyncio.timeout(timeout):
                async for message in client.messages():
                    if (
                        message.chat_id != room.chat_id
                        or isinstance(message.author_id, bool)
                        or not isinstance(message.author_id, int)
                        or message.author_id <= 0
                        or message.author_id == credentials.user_id
                    ):
                        continue
                    if (
                        isinstance(message.log_id, bool)
                        or not isinstance(message.log_id, int)
                        or message.log_id <= room.last_log_id
                        or message.log_id in seen
                    ):
                        continue
                    seen[message.log_id] = None
                    if len(seen) > 4096:
                        seen.popitem(last=False)
                    if message.type != 1 or message.text != "/핑":
                        continue
                    send_attempts = 1
                    update("sending_reply")
                    await client.send_text(room.chat_id, TEST_REPLY)
                    replies_sent = 1
                    update("reply_sent")
                    print_fn("답장 한 번의 서버 응답을 확인했습니다. 테스트를 종료합니다.")
                    return 1
            raise ConnectionError("Message stream ended before the reply test completed")
    except (KeyboardInterrupt, asyncio.CancelledError):
        update("reply_uncertain" if send_attempts else "canceled")
        raise
    except TimeoutError:
        if send_attempts:
            update("reply_uncertain", error_type="TimeoutError")
            raise ReplyTestWriteError(
                "The single reply write timed out; delivery is uncertain"
            ) from None
        update("test_timeout", error_type="TimeoutError")
        raise TimeoutError("Reply test timed out before receiving a new command") from None
    except Exception as error:
        if send_attempts:
            update("reply_uncertain", error_type=type(error).__name__)
            raise ReplyTestWriteError(
                "The single reply write did not complete; delivery is uncertain"
            ) from None
        update("failed", error_type=type(error).__name__)
        raise
