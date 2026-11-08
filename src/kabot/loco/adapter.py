"""Reuse Kabot text commands on explicitly selected personal/group chats."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable

from ..bot import Bot
from ..models import SkillRequest
from .client import PersonalClient, positive_id


async def run_personal_bot(
    bot: Bot,
    client: PersonalClient,
    *,
    chat_ids: Iterable[int],
    handler_timeout: float = 4.0,
    dedupe_capacity: int = 4096,
) -> None:
    """Run on an authenticated client. No native client, UI automation, or implicit login.

    Only new text pushes for selected chat IDs are handled. Self messages are ignored.
    Duplicate suppression is bounded and process-local, not durable exactly-once delivery.
    Handler/delivery errors stop the runner, allowing the operator to assess ambiguous writes.
    """
    chats = {int(positive_id(value, "chat_id")) for value in chat_ids}
    if not chats or not 0 < handler_timeout <= 60 or dedupe_capacity < 1:
        raise ValueError("Require chat_ids, positive dedupe capacity and 0<handler_timeout<=60")
    seen: OrderedDict[tuple[int, int], None] = OrderedDict()
    async for message in client.messages():
        if (
            message.author_id <= 0
            or message.chat_id not in chats
            or message.author_id == client.credentials.user_id
            or message.type != 1
        ):
            continue
        key = (message.chat_id, message.log_id)
        if key in seen:
            continue
        seen[key] = None
        if len(seen) > dedupe_capacity:
            seen.popitem(last=False)
        payload = {
            "bot": {"id": f"loco:{client.credentials.user_id}:{message.chat_id}"},
            "userRequest": {"utterance": message.text, "user": {"id": str(message.author_id)}},
        }
        # Unmatched chat messages do not trigger the channel fallback in a group.
        route, ctx = bot.resolve(SkillRequest.model_validate(payload))
        if route is None:
            continue
        ctx.metadata.update(chat_id=message.chat_id, log_id=message.log_id, transport="loco")
        answer = await asyncio.wait_for(bot.execute(route, ctx), handler_timeout)
        outputs = answer.to_dict()["template"]["outputs"]
        if any(set(output) != {"simpleText"} for output in outputs) or answer.quick_replies:
            raise ValueError("Personal bot adapter currently supports text responses only")
        # Send one WRITE for the whole answer, avoiding partial multi-bubble delivery.
        await client.send_text(
            message.chat_id, "\n\n".join(output["simpleText"]["text"] for output in outputs)
        )
