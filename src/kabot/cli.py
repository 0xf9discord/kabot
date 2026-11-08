"""Local scaffold, simulator and server runner. Never reads Kakao desktop data."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import secrets
import sys
from pathlib import Path

from .bot import Bot
from .server import create_app

SCAFFOLD = """from kabot import Bot, SQLiteStore, quick_reply, text

bot = Bot(store=SQLiteStore("bot.sqlite3"))

@bot.command("도움말")
def help(ctx):
    return text("/안녕 이름, /방문, /메모 내용, /메모확인").with_quick_replies(
        quick_reply("인사", "/안녕 친구"), quick_reply("방문 횟수", "/방문"))

@bot.command("안녕")
def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"

@bot.command("방문")
def visit(ctx):
    count = ctx.store.increment(ctx.scope, "visits")
    return f"{count}번째 방문입니다."

@bot.command("메모")
def memo(ctx):
    if not ctx.args:
        return "사용법: /메모 기억할 내용"
    ctx.store.set(ctx.scope, "memo", ctx.args, ttl=86400)
    return "하루 동안 기억할게요."

@bot.command("메모확인")
def read_memo(ctx):
    return ctx.store.get(ctx.scope, "memo", "저장한 메모가 없어요.")
"""

PERSONAL_SCAFFOLD = """from kabot import Bot, SQLiteStore

bot = Bot(store=SQLiteStore("personal-bot.sqlite3"))

@bot.command("도움말")
def help_command(ctx):
    return "/핑, /안녕 이름, /방문 명령을 사용할 수 있습니다."

@bot.command("핑")
async def ping(ctx):
    return "퐁!"

@bot.command("안녕")
def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"

@bot.command("방문")
def visit(ctx):
    return f"{ctx.store.increment(ctx.scope, 'visits')}번째 방문입니다."
"""


def load_bot(reference: str) -> Bot:
    module_name, separator, name = reference.partition(":")
    if not separator or not module_name or not name:
        raise ValueError("Use module:bot, for example mybot:bot")
    # Import operator-provided code from the working directory, as with uvicorn.
    sys.path.insert(0, str(Path.cwd()))
    bot = getattr(importlib.import_module(module_name), name)
    if not isinstance(bot, Bot):
        raise TypeError("The referenced object must be kabot.Bot")
    return bot


async def simulate(bot: Bot) -> None:
    print("로컬 시뮬레이터입니다. 실제 카카오톡에는 전송하지 않습니다. /종료로 끝냅니다.")
    while True:
        try:
            message = await asyncio.to_thread(input, "> ")
        except EOFError:
            return
        if message == "/종료":
            return
        payload = {
            "bot": {"id": "local"},
            "userRequest": {"utterance": message, "user": {"id": "local-user"}},
        }
        response = await bot.handle(payload)
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="kabot", description="Kakao channel skill bot tools")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create an example bot without overwriting files")
    init.add_argument("file", nargs="?", default="mybot.py")
    init.add_argument(
        "--personal", action="store_true", help="Create a text-only personal/group bot"
    )
    local = sub.add_parser("chat", help="Run a local simulator (no Kakao network traffic)")
    local.add_argument("bot", default="mybot:bot", nargs="?")
    run = sub.add_parser("run", help="Start a channel skill server")
    run.add_argument("bot", default="mybot:bot", nargs="?")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)
    login = sub.add_parser(
        "login", help="Interactive experimental Android login; never pass passwords as arguments"
    )
    login.add_argument("--session", default="personal-session.kabot")
    login.add_argument(
        "--status-file", help="Write redacted phase/status codes for local progress monitoring"
    )
    login.add_argument("--skip-loco-check", action="store_true")
    login.add_argument(
        "--replace",
        action="store_true",
        help="Unlock and replace an existing session, reusing its device ID",
    )
    chats = sub.add_parser(
        "chats", help="Unlock an encrypted personal session and list chat IDs locally"
    )
    chats.add_argument("--session", default="personal-session.kabot")
    profile = sub.add_parser(
        "open-profile", help="List open links, read a room profile, or explicitly switch it"
    )
    profile.add_argument("--session", default="personal-session.kabot")
    profile.add_argument("--chat-id", type=int)
    profile.add_argument("--kind", choices=("main", "anonymous", "link"))
    profile.add_argument("--nickname")
    profile.add_argument(
        "--profile-path", help="Existing Kakao image path, not a local file or URL"
    )
    profile.add_argument("--profile-link-id", type=int)
    verify = sub.add_parser(
        "verify", help="Unlock a saved session and check chat login without sending messages"
    )
    verify.add_argument("--session", default="personal-session.kabot")
    verify.add_argument("--status-file")
    bot_test = sub.add_parser(
        "bot-test", help="Locally select a test room and authorize one ping reply"
    )
    bot_test.add_argument("--session", default="personal-session.kabot")
    bot_test.add_argument("--status-file")
    bot_test.add_argument("--target-room")
    bot_test.add_argument("--allow-open", action="store_true")
    gui = sub.add_parser(
        "gui", help="Open a local user-operated session verification or login window"
    )
    gui.add_argument("--session", default="personal-session.kabot")
    gui.add_argument("--status-file")
    gui.add_argument("--mode", choices=("verify", "login", "bot-test"), default="verify")
    gui.add_argument("--replace", action="store_true")
    gui.add_argument("--target-room")
    gui.add_argument("--allow-open", action="store_true")
    personal = sub.add_parser("personal", help="Run an experimental text bot in selected chats")
    personal.add_argument("bot", default="mybot:bot", nargs="?")
    personal.add_argument("--session", default="personal-session.kabot")
    personal.add_argument("--chat-id", type=int, action="append", required=True)
    sub.add_parser("secret", help="Generate a secret for KABOT_WEBHOOK_SECRET")
    sub.add_parser("doctor", help="Show supported transports and configuration status")
    args = parser.parse_args()
    try:
        if args.command == "init":
            with Path(args.file).open("x", encoding="utf-8") as output:
                output.write(PERSONAL_SCAFFOLD if args.personal else SCAFFOLD)
            created = Path(args.file)
            print(
                f"Created {created}. From {created.resolve().parent}, run: "
                f"kabot chat {created.stem}:bot"
            )
        elif args.command == "secret":
            print(secrets.token_urlsafe(32))
        elif args.command == "doctor":
            print(
                "Channel skill server: supported (public HTTPS + Kakao channel configuration required)"
            )
            print(
                "Personal official API: self/friend outbound messages; OAuth and permissions required"
            )
            print(
                "Personal/group LOCO: experimental transport/session; live compatibility unverified"
            )
            print(
                "Android26.8.2 password/device registration: experimental; account verification required"
            )
            print("Automatic token renewal and QR login: not implemented")
            print("Webhook secret configured: " + str(bool(os.getenv("KABOT_WEBHOOK_SECRET"))))
        elif args.command == "chat":
            asyncio.run(simulate(load_bot(args.bot)))
        elif args.command == "gui":
            from .loco.gui import run_window

            run_window(
                args.session,
                status_path=args.status_file,
                mode=args.mode,
                replace=args.replace,
                target_name=args.target_room,
                allow_open=args.allow_open,
            )
        elif args.command in ("login", "chats", "personal", "verify", "bot-test", "open-profile"):
            from .loco import LocoConnectionError, LocoStatusError, PersonalClient, run_personal_bot
            from .loco.auth import AndroidAuthError
            from .loco.interactive import (
                interactive_login,
                manage_open_profile,
                show_chats,
                unlock_session,
                verify_saved_session,
            )

            try:
                if args.command == "login":
                    asyncio.run(
                        interactive_login(
                            args.session,
                            status_path=args.status_file,
                            verify_loco=not args.skip_loco_check,
                            replace=args.replace,
                        )
                    )
                elif args.command == "chats":
                    asyncio.run(show_chats(args.session))
                elif args.command == "open-profile":
                    from .loco import OpenChatProfile
                    from .loco.client import positive_id

                    if args.chat_id is not None:
                        positive_id(args.chat_id, "chat_id")
                    if args.kind is not None and args.chat_id is None:
                        raise ValueError("--chat-id is required to change a room profile")
                    if args.kind is None and any(
                        v is not None
                        for v in (args.nickname, args.profile_path, args.profile_link_id)
                    ):
                        raise ValueError("--kind is required with profile options")
                    selection = (
                        OpenChatProfile(
                            args.kind,
                            nickname=args.nickname,
                            profile_path=args.profile_path,
                            profile_link_id=args.profile_link_id,
                        )
                        if args.kind is not None
                        else None
                    )
                    asyncio.run(
                        manage_open_profile(args.session, chat_id=args.chat_id, profile=selection)
                    )
                elif args.command == "verify":
                    asyncio.run(verify_saved_session(args.session, status_path=args.status_file))
                elif args.command == "bot-test":
                    from .loco.live_test import run_reply_test

                    asyncio.run(
                        run_reply_test(
                            args.session,
                            status_path=args.status_file,
                            target_name=args.target_room,
                            allow_open=args.allow_open,
                        )
                    )
                else:
                    bot = load_bot(args.bot)

                    async def personal_main():
                        credentials = await unlock_session(args.session)
                        async with PersonalClient(credentials) as client:
                            await client.connect()
                            await run_personal_bot(bot, client, chat_ids=args.chat_id)

                    asyncio.run(personal_main())
            except (
                AndroidAuthError,
                LocoConnectionError,
                LocoStatusError,
                OSError,
                TimeoutError,
            ) as exc:
                parser.exit(1, f"kabot: {exc}\n")
            except KeyboardInterrupt:
                parser.exit(130, "\nStopped.\n")
        elif args.command == "run":
            secret = os.getenv("KABOT_WEBHOOK_SECRET", "")
            if not secret:
                parser.error("Set KABOT_WEBHOOK_SECRET first; generate one with kabot secret")
            app = create_app(
                load_bot(args.bot),
                webhook_secret=secret,
                expected_bot_id=os.getenv("KABOT_BOT_ID") or None,
                callback_hosts=tuple(
                    h.strip() for h in os.getenv("KABOT_CALLBACK_HOSTS", "").split(",") if h.strip()
                ),
            )
            import uvicorn

            # URLs contain a webhook secret: do not print access logs.
            uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    except (ValueError, TypeError, FileExistsError, ImportError, AttributeError) as exc:
        parser.exit(1, f"kabot: {exc}\n")


if __name__ == "__main__":
    main()
