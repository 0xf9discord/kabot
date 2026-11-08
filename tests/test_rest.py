import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from kabot.rest import KakaoAPIError, KakaoClient, authorization_url, validate_state


def run(coro):
    return asyncio.run(coro)


def test_authorization_url_and_state():
    url = authorization_url(
        "app-key",
        "https://example.com/callback",
        state="random+state",
        scopes=["talk_message", "friends"],
    )
    assert urlsplit(url).hostname == "kauth.kakao.com"
    assert parse_qs(urlsplit(url).query)["scope"] == ["talk_message,friends"]
    assert parse_qs(urlsplit(url).query)["state"] == ["random+state"]
    validate_state("한글-state", "한글-state")
    for received in (None, "", "different"):
        with pytest.raises(ValueError, match="state"):
            validate_state("state", received)
    with pytest.raises(ValueError):
        authorization_url("app", "https://example.com", state="")


def test_send_self_encodes_form_and_keeps_injected_client_open():
    def handler(request):
        assert request.url == "https://kapi.kakao.com/v2/api/talk/memo/default/send"
        assert request.headers["Authorization"] == "Bearer access"
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
        template = json.loads(parse_qs(request.content.decode())["template_object"][0])
        assert template["text"] == "한글 테스트"
        assert template["link"]["web_url"] == "https://example.com"
        return httpx.Response(200, json={"result_code": 0})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with KakaoClient("access", http_client=http) as client:
                assert await client.send_self_text(
                    "한글 테스트", link_url="https://example.com"
                ) == {"result_code": 0}
            assert not http.is_closed

    run(scenario())


def test_read_retry_and_one_page_only():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.params["offset"] == "20"
        assert request.url.params["limit"] == "20"
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"code": -10})
        return httpx.Response(
            200,
            json={
                "elements": [{"uuid": "friend"}],
                "total_count": 80,
                "after_url": "https://kapi.kakao.com/v1/api/talk/friends?offset=40",
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = KakaoClient("access", http_client=http, max_retry_delay=0)
            result = await client.list_friends(offset=20, limit=20)
            assert result["after_url"]
            assert len(calls) == 2

    run(scenario())


@pytest.mark.parametrize("status", [429, 500, 503])
def test_send_never_retries_http_errors(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"code": -10, "msg": "private_server_detail"})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = KakaoClient("access", http_client=http)
            with pytest.raises(KakaoAPIError) as caught:
                await client.send_self_text("알림", link_url="https://example.com")
            assert caught.value.status_code == status
            assert caught.value.code == -10
            assert caught.value.server_message == "private_server_detail"
            assert "private_server_detail" not in str(caught.value)
            assert len(calls) == 1

    run(scenario())


def test_send_never_retries_ambiguous_timeout():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("Timed out", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = KakaoClient("access", http_client=http)
            with pytest.raises(httpx.ReadTimeout):
                await client.send_self_text("알림", link_url="https://example.com")
            assert len(calls) == 1

    run(scenario())


def test_friends_partial_success_retained():
    partial = {
        "successful_receiver_uuids": ["a"],
        "failure_info": [{"code": -532, "msg": "quota", "receiver_uuids": ["b"]}],
    }

    def handler(request):
        form = parse_qs(request.content.decode())
        assert json.loads(form["receiver_uuids"][0]) == ["a", "b"]
        assert request.url.path == "/v1/api/talk/friends/message/default/send"
        return httpx.Response(200, json=partial)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await KakaoClient("access", http_client=http).send_friends_text(
                ["a", "b"], "hello", link_url="https://example.com"
            )
            assert result == partial

    run(scenario())


def test_oauth_state_checked_before_network_and_refresh_token_preserved():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url == "https://kauth.kakao.com/oauth/token"
        assert "authorization" not in request.headers
        form = parse_qs(request.content.decode())
        assert form["client_secret"] == ["secret"]
        if form["grant_type"] == ["authorization_code"]:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 100,
                    "refresh_token_expires_in": 10000,
                    "scope": "talk_message",
                },
            )
        assert form["refresh_token"] == ["refresh-1"]
        return httpx.Response(200, json={"access_token": "access-2", "expires_in": 200})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = KakaoClient(client_id="app", client_secret="secret", http_client=http)
            with pytest.raises(ValueError, match="state"):
                await client.exchange_code(
                    "code",
                    "https://example.com/callback",
                    expected_state="expected",
                    received_state="wrong",
                )
            assert not calls
            first = await client.exchange_code(
                "code",
                "https://example.com/callback",
                expected_state="expected",
                received_state="expected",
            )
            second = await client.refresh()
            assert second.refresh_token == first.refresh_token == "refresh-1"
            assert second.refresh_expires_at == first.refresh_expires_at
            assert second.scope == "talk_message"
            assert client.access_token == "access-2"
            assert "access-2" not in repr(second)
            assert "refresh-1" not in repr(second)

    run(scenario())


def test_custom_templates_and_validation():
    calls = []

    def handler(request):
        calls.append(request)
        form = parse_qs(request.content.decode())
        assert form["template_id"] == ["123"]
        assert json.loads(form["template_args"][0]) == {"name": "테스트"}
        return httpx.Response(200, json={"result_code": 0})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = KakaoClient("access", http_client=http)
            await client.send_self_custom(123, template_args={"name": "테스트"})
            assert calls[-1].url.path == "/v2/api/talk/memo/send"
            await client.send_friends_custom(["a"], 123, template_args={"name": "테스트"})
            assert calls[-1].url.path == "/v1/api/talk/friends/message/send"
            for recipients in ([], [str(i) for i in range(6)], ["a", "a"], "abc"):
                with pytest.raises(ValueError):
                    await client.send_friends_text(
                        recipients, "text", link_url="https://example.com"
                    )
            with pytest.raises(ValueError):
                await client.send_self_text("x" * 201, link_url="https://example.com")
            with pytest.raises(ValueError):
                await client.send_self_text("hi", link_url="javascript:bad")
            with pytest.raises(ValueError):
                await client.list_friends(limit=101)
            assert len(calls) == 2

    run(scenario())


def test_redirects_are_not_followed_and_non_json_is_structured_error():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            302, headers={"Location": "https://example.com/steal"}, text="redirect"
        )

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as http:
            client = KakaoClient("access", http_client=http)
            with pytest.raises(KakaoAPIError) as caught:
                await client.list_friends()
            assert caught.value.status_code == 302
            assert len(calls) == 1

    run(scenario())
