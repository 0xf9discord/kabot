"""Experimental LOCO example. Requires operator-supplied desktop session credentials.

This does not obtain tokens or bypass device registration. See docs/LOCO.md.
No network operation is performed merely by importing this module.
"""

import asyncio
import os

from kabot import Bot, SQLiteStore
from kabot.loco import Credentials, PersonalClient, run_personal_bot


async def main():
    required = (
        "KABOT_LOCO_USER_ID",
        "KABOT_LOCO_TOKEN",
        "KABOT_LOCO_DEVICE_UUID",
        "KABOT_LOCO_APP_VERSION",
        "KABOT_LOCO_CHAT_IDS",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise SystemExit(
            "Missing environment variables: "
            + ", ".join(missing)
            + ". Read docs/LOCO.md before connecting."
        )
    credentials = Credentials(
        user_id=int(os.environ["KABOT_LOCO_USER_ID"]),
        oauth_token=os.environ["KABOT_LOCO_TOKEN"],
        device_uuid=os.environ["KABOT_LOCO_DEVICE_UUID"],
        app_version=os.environ["KABOT_LOCO_APP_VERSION"],
    )
    chats = {int(value.strip()) for value in os.environ["KABOT_LOCO_CHAT_IDS"].split(",")}
    bot = Bot(store=SQLiteStore("personal-bot.sqlite3"))

    @bot.command("안녕")
    async def hello(ctx):
        return f"안녕하세요, {ctx.args or '친구'}님!"

    @bot.command("방문")
    def visits(ctx):
        return f"{ctx.store.increment(ctx.scope, 'visits')}번째 방문입니다."

    async with PersonalClient(credentials) as client:
        await client.connect()
        await run_personal_bot(bot, client, chat_ids=chats)


if __name__ == "__main__":
    asyncio.run(main())
