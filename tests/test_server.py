import asyncio

import httpx

from kabot import Bot, create_app
from kabot.server import callback_allowed

SECRET = "a" * 32
URL = "/skill/" + SECRET
PAYLOAD = {"bot": {"id": "expected"}, "userRequest": {"utterance": "/ping", "user": {"id": "u"}}}


def test_http_validation_auth_and_payload_limits():
    bot = Bot()

    @bot.command("ping")
    def ping(ctx):
        return "pong"

    async def run():
        app = create_app(bot, webhook_secret=SECRET, expected_bot_id="expected", max_body_bytes=300)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as c:
            assert (await c.get("/healthz")).status_code == 200
            assert (await c.post("/skill/wrong", json=PAYLOAD)).status_code == 404
            assert (await c.post(URL, content="broken")).status_code == 400
            assert (await c.post(URL, json={})).status_code == 400
            assert (await c.post(URL, content="a" * 301)).status_code == 413
            bad = dict(PAYLOAD, bot={"id": "other"})
            assert (await c.post(URL, json=bad)).status_code == 403
            response = (await c.post(URL, json=PAYLOAD)).json()
            assert response["template"]["outputs"][0]["simpleText"]["text"] == "pong"

    asyncio.run(run())


def test_deadline_and_handler_failure_return_valid_responses():
    bot = Bot()

    @bot.command("ping")
    async def ping(ctx):
        await asyncio.sleep(0.1)
        return "too late"

    @bot.command("error")
    async def error(ctx):
        raise RuntimeError("private details")

    async def run():
        app = create_app(bot, webhook_secret=SECRET, timeout=0.01)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as c:
            assert "초과" in (await c.post(URL, json=PAYLOAD)).text
            p = {**PAYLOAD, "userRequest": {**PAYLOAD["userRequest"], "utterance": "/error"}}
            response = await c.post(URL, json=p)
            assert "오류" in response.text
            assert "private details" not in response.text

    asyncio.run(run())


def test_callback_ack_delivery_and_host_rejection():
    calls = []
    bot = Bot()

    @bot.command("ping", deferred=True)
    async def ping(ctx):
        return "콜백 완료"

    def remote(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "SUCCESS"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as remote_client:
            app = create_app(
                bot,
                webhook_secret=SECRET,
                callback_hosts=("callback.example.com",),
                callback_client=remote_client,
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://local"
            ) as c:
                for url in [
                    "http://callback.example.com/t",
                    "https://evil.example.com/t",
                    "https://callback.example.com@127.0.0.1/t",
                ]:
                    p = {**PAYLOAD, "userRequest": {**PAYLOAD["userRequest"], "callbackUrl": url}}
                    assert "useCallback" not in (await c.post(URL, json=p)).json()
                assert not calls
                p = {
                    **PAYLOAD,
                    "userRequest": {
                        **PAYLOAD["userRequest"],
                        "callbackUrl": "https://callback.example.com/secret",
                    },
                }
                assert (await c.post(URL, json=p)).json() == {"version": "2.0", "useCallback": True}
                assert len(calls) == 1
                assert "콜백 완료" in calls[0].content.decode()

    asyncio.run(run())


def test_callback_url_policy():
    hosts = frozenset(["callback.example.com"])
    assert callback_allowed("https://callback.example.com/x", hosts)
    for url in [
        "https://callback.example.com.evil/x",
        "https://callback.example.com:444/x",
        "https://user:pw@callback.example.com/x",
        "https://callback.example.com/x#frag",
        "http://127.0.0.1/x",
        "https://callback.example.com:bad/x",
    ]:
        assert not callback_allowed(url, hosts)
