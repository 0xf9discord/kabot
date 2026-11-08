import asyncio
import hashlib
import json
from urllib.parse import parse_qs

import httpx
import pytest

from kabot.loco.auth import (
    ANDROID_26_8_2,
    AndroidAuthClient,
    AndroidAuthError,
    AndroidAuthProfile,
    AndroidTokens,
    RegistrationRequired,
    generate_device_uuid,
)

UUID = "ab" * 32


def run(coroutine):
    return asyncio.run(coroutine)


def test_profile_is_source_pinned_and_signs_exact_declared_identity():
    assert ANDROID_26_8_2.app_version == "26.8.2"
    assert ANDROID_26_8_2.agent == "android/26.8.2/ko"
    assert ANDROID_26_8_2.user_agent == "KT/26.8.2 An/13 ko"
    expected = hashlib.sha512(b"ALBUS|KT/26.8.2 An/13 ko|IAN|test@example.com|SEOGI").hexdigest()[
        :16
    ]
    assert ANDROID_26_8_2.xvc("test@example.com") == expected
    with pytest.raises(ValueError, match="26.8.2"):
        AndroidAuthProfile(app_version="26.9.1")
    first, second = generate_device_uuid(), generate_device_uuid()
    assert len(first) == 64 and all(c in "0123456789abcdef" for c in first)
    assert first != second


def test_login_form_tokens_redaction_and_external_client_ownership():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url == "https://katalk.kakao.com/android/account/login.json"
        assert request.headers["a"] == "android/26.8.2/ko"
        assert request.headers["user-agent"] == "KT/26.8.2 An/13 ko"
        assert request.headers["x-vc"] == ANDROID_26_8_2.xvc("test@example.com")
        assert parse_qs(request.content.decode()) == {
            "email": ["test@example.com"],
            "password": ["test-secret"],
            "device_name": ["SM-T870"],
            "device_uuid": [UUID],
            "forced": ["false"],
            "permanent": ["true"],
        }
        return httpx.Response(
            200,
            json={
                "status": 0,
                "userId": 2**60 + 123,
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with AndroidAuthClient(http_client=http) as api:
                tokens = await api.login("test@example.com", "test-secret", UUID)
                assert isinstance(tokens, AndroidTokens)
                assert tokens.access_token == "secret-access"
                assert tokens.refresh_token == "secret-refresh"
                assert tokens.user_id == 2**60 + 123
                assert tokens.device_uuid == UUID
                assert not any("password" in name for name in vars(api))
                assert "secret-access" not in repr(tokens)
                assert "secret-refresh" not in repr(tokens)
                assert UUID not in repr(tokens)
            assert not http.is_closed

    run(scenario())
    assert len(calls) == 1


def test_new_device_returns_requirement_without_generating_code_or_looping():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"status": -100})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            requirement = await AndroidAuthClient(http_client=http).login(
                "test@example.com", "password", UUID
            )
            assert isinstance(requirement, RegistrationRequired)
            assert requirement.server_status == -100
            assert requirement.device_uuid == UUID
            assert len(calls) == 1

    run(scenario())


def test_explicit_allowlist_generate_poll_and_second_login_sequence():
    steps = []

    def handler(request):
        steps.append(request.url.path)
        if request.url.path.endswith("allowlist.json"):
            assert request.method == "GET"
            assert request.headers["content-type"] == "application/x-www-form-urlencoded"
            assert request.url.params["model_name"] == "SM-T870"
            return httpx.Response(200, json={"allowlisted": True})
        if request.url.path.endswith("generate"):
            assert json.loads(request.content) == {
                "email": "test@example.com",
                "password": "password",
                "permanent": True,
                "device": {"name": "SM-T870", "uuid": UUID, "model": "SM-T870", "osVersion": "33"},
            }
            return httpx.Response(
                200, json={"status": 0, "passcode": "012345", "remainingSeconds": 180}
            )
        if request.url.path.endswith("registerDevice"):
            assert json.loads(request.content) == {
                "email": "test@example.com",
                "password": "password",
                "device": {"uuid": UUID},
            }
            count = sum(step.endswith("registerDevice") for step in steps)
            return httpx.Response(
                200,
                json={"status": -100, "remainingSeconds": 175, "nextRequestIntervalInSeconds": 5}
                if count == 1
                else {"status": 0},
            )
        raise AssertionError("Unexpected automatic login or registration request")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = AndroidAuthClient(http_client=http)
            assert await api.check_model()
            challenge = await api.request_registration("test@example.com", "password", UUID)
            assert challenge.passcode == "012345"
            assert challenge.remaining_seconds == 180
            assert "012345" not in repr(challenge)
            pending = await api.poll_registration_once("test@example.com", "password", UUID)
            assert not pending.registered
            assert pending.next_request_interval_seconds == 5
            assert len(steps) == 3
            registered = await api.poll_registration_once("test@example.com", "password", UUID)
            assert registered.registered and registered.server_status == 0
            assert len(steps) == 4  # no automatic login after registration

    run(scenario())


@pytest.mark.parametrize("status", [12, 30, -101, -132, -999, -997])
def test_server_rejections_preserve_status_and_never_force_or_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"status": status, "message": "password=leak access_token=leak"}
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AndroidAuthError) as caught:
                await AndroidAuthClient(http_client=http).login(
                    "test@example.com", "secret-password", UUID
                )
            assert caught.value.server_status == status
            assert caught.value.reason == "server_rejected"
            assert "leak" not in str(caught.value)
            assert "secret-password" not in repr(caught.value)
            assert len(calls) == 1

    run(scenario())


@pytest.mark.parametrize("status", [302, 429, 500])
def test_http_failures_no_retry_or_redirect(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Location": "https://example.com/redirect"}, text="secret server text"
        )

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as http:
            with pytest.raises(AndroidAuthError) as caught:
                await AndroidAuthClient(http_client=http).login(
                    "test@example.com", "password", UUID
                )
            assert caught.value.http_status == status
            assert "secret" not in str(caught.value)
            assert len(calls) == 1

    run(scenario())


def test_transport_error_is_redacted_without_request_attached():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("password=secret", request=request)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(AndroidAuthError) as caught:
                await AndroidAuthClient(http_client=http).login(
                    "test@example.com", "password", UUID
                )
            assert caught.value.reason == "timeout"
            assert not hasattr(caught.value, "request")
            assert "secret" not in str(caught.value)
            assert caught.value.__suppress_context__
            assert len(calls) == 1

    run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"status": True},
        {"status": 0, "access_token": "secret", "userId": "123"},
        {"status": 0, "access_token": "secret", "userId": True},
    ],
)
def test_malformed_login_response_does_not_report_success(payload):
    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ) as http:
            with pytest.raises(AndroidAuthError):
                await AndroidAuthClient(http_client=http).login(
                    "test@example.com", "password", UUID
                )

    run(scenario())


def test_bad_identity_fails_before_network():
    async def scenario():
        def handler(request):
            raise AssertionError("Network must not be reached")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = AndroidAuthClient(http_client=http)
            for invalid_uuid in ("short", "A" * 64, "g" * 64):
                with pytest.raises(ValueError, match="device_uuid"):
                    await api.login("test@example.com", "password", invalid_uuid)

    run(scenario())
