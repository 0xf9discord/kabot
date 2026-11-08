import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from kabot import Bot, SQLiteStore, card, link_button, quick_reply, text


def payload(message, user="alice", bot="b1"):
    return {"bot": {"id": bot}, "userRequest": {"utterance": message, "user": {"id": user}}}


def test_routing_arguments_regex_action_hooks_and_fallback():
    bot = Bot()

    @bot.before
    def guard(ctx):
        if ctx.user_id == "blocked":
            return "차단됨"

    @bot.command("echo")
    async def echo(ctx):
        return ctx.args or "empty"

    @bot.hears(r"^가격 (\d+)$")
    def price(ctx):
        return str(int(ctx.match[1]) * 100)

    @bot.action("order")
    def order(ctx):
        return ctx.params["id"]

    async def run():
        assert (await bot.handle(payload("/echo a b"))).outputs[0]["simpleText"]["text"] == "a b"
        assert (await bot.handle(payload("/echo"))).outputs[0]["simpleText"]["text"] == "empty"
        assert (await bot.handle(payload("/echoes"))).outputs[0]["simpleText"][
            "text"
        ] == bot.fallback
        assert (await bot.handle(payload("가격 32"))).outputs[0]["simpleText"]["text"] == "3200"
        p = payload("주문")
        p["action"] = {"name": "order", "params": {"id": "주문123"}}
        assert (await bot.handle(p)).outputs[0]["simpleText"]["text"] == "주문123"
        assert (await bot.handle(payload("/echo", "blocked"))).outputs[0]["simpleText"][
            "text"
        ] == "차단됨"

    asyncio.run(run())


def test_response_limits_and_cards():
    long = text("한" * 2500).with_quick_replies(quick_reply("도움말", "/도움말"))
    assert len(long.to_dict()["template"]["outputs"]) == 3
    assert long.to_dict()["template"]["quickReplies"][0]["messageText"] == "/도움말"
    with pytest.raises(ValueError):
        text("x" * 3001)
    with pytest.raises(ValueError):
        text("ok").with_quick_replies(*[quick_reply("x", "x")] * 11)
    value = card(
        "제목",
        "설명",
        "https://example.com/a.png",
        buttons=[link_button("보기", "https://example.com")],
    ).to_dict()
    assert value["template"]["outputs"][0]["basicCard"]["thumbnail"]["imageUrl"].endswith("a.png")


def test_persistence_ttl_and_atomic_counters(tmp_path):
    path = tmp_path / "store.db"
    store = SQLiteStore(path)
    store.set("a", "memo", {"한국어": True})
    assert SQLiteStore(path).get("a", "memo") == {"한국어": True}
    assert store.get("b", "memo") is None
    store.set("a", "expires", 1, ttl=0.01)
    time.sleep(0.02)
    assert store.get("a", "expires") is None
    assert store.purge_expired() == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: store.increment("a", "count"), range(50)))
    assert store.get("a", "count") == 50
    store.delete("a", "memo")
    assert store.get("a", "memo", "default") == "default"


def test_sync_handler_does_not_block_event_loop():
    bot = Bot()

    @bot.on_message()
    def slow(ctx):
        time.sleep(0.05)
        return "ok"

    async def run():
        handler = asyncio.create_task(bot.handle(payload("hi")))
        await asyncio.sleep(0.005)
        assert not handler.done()
        await handler

    asyncio.run(run())
