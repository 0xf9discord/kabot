"""Async clients for documented Kakao Login, Talk Message and Talk Social APIs.

No desktop installation or UI automation is used. These APIs cannot receive
personal chat messages, list chat rooms, or send messages to arbitrary rooms.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

__all__ = ["KakaoAPIError", "KakaoClient", "OAuthTokens", "authorization_url", "validate_state"]

_API = "https://kapi.kakao.com"
_AUTH = "https://kauth.kakao.com"


class KakaoAPIError(Exception):
    """HTTP or Kakao error. String representation omits server messages/tokens."""

    def __init__(self, status_code: int, code: int | str | None, server_message: str = ""):
        self.status_code = status_code
        self.code = code
        self.server_message = server_message
        # OAuth error codes are server input; do not echo arbitrary text in logs.
        printable = str(code) if isinstance(code, int) else "oauth_error" if code else "unknown"
        super().__init__(f"Kakao API request failed (HTTP {status_code}, code {printable})")


@dataclass(frozen=True)
class OAuthTokens:
    """In-memory credentials; persist securely in your own application's vault."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: float = 0.0
    refresh_expires_at: float | None = None
    scope: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


def _nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _web_url(value: str, name: str) -> str:
    _nonempty(value, name)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL without credentials")
    return value


def authorization_url(
    client_id: str, redirect_uri: str, *, state: str, scopes: Sequence[str] = ()
) -> str:
    """Build login URL. Store random state in session and validate on callback."""
    _nonempty(client_id, "client_id")
    _web_url(redirect_uri, "redirect_uri")
    _nonempty(state, "state")
    if isinstance(scopes, str):
        raise ValueError("scopes must be a sequence of scope names, not a string")
    for scope in scopes:
        _nonempty(scope, "scope")
        if "," in scope:
            raise ValueError("each scope must be a single scope name")
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if scopes:
        query["scope"] = ",".join(scopes)
    return f"{_AUTH}/oauth/authorize?{urlencode(query)}"


def validate_state(expected: str, received: str | None) -> None:
    """Reject absent/mismatching OAuth callback state before exchanging code."""
    _nonempty(expected, "expected state")
    if (
        not isinstance(received, str)
        or not received
        or not hmac.compare_digest(expected.encode(), received.encode())
    ):
        raise ValueError("OAuth state mismatch")


def _recipients(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("receiver_uuids must be a sequence of UUID strings")
    result = list(values)
    if not 1 <= len(result) <= 5:
        raise ValueError("Kakao allows 1 to 5 recipients per request")
    for value in result:
        _nonempty(value, "receiver UUID")
    if len(set(result)) != len(result):
        raise ValueError("receiver UUIDs must be unique")
    return result


def _text_template(text: str, link_url: str, button_title: str | None) -> dict[str, Any]:
    _nonempty(text, "text")
    if len(text) > 200:
        raise ValueError("Kakao text templates allow at most 200 characters")
    _web_url(link_url, "link_url")
    result: dict[str, Any] = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }
    if button_title is not None:
        result["button_title"] = _nonempty(button_title, "button_title")
    return result


class KakaoClient:
    """Explicit async REST operations with bounded retries for GET requests only.

    Message sends and OAuth operations are never automatically retried. A timeout
    after a send is ambiguous: inspect the outcome before deciding to send again.
    When supplying an AsyncClient, its lifecycle remains caller-owned.
    """

    def __init__(
        self,
        access_token: str | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 10.0,
        read_retries: int = 2,
        max_retry_delay: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ):
        if type(read_retries) is not int or not 0 <= read_retries <= 5:
            raise ValueError("read_retries must be an integer between 0 and 5")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if not math.isfinite(max_retry_delay) or not 0 <= max_retry_delay <= 60:
            raise ValueError("max_retry_delay must be between 0 and 60 seconds")
        if access_token is not None:
            _nonempty(access_token, "access_token")
        self.access_token = access_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.tokens: OAuthTokens | None = None
        self._timeout = timeout
        self._read_retries = read_retries
        self._max_retry_delay = max_retry_delay
        self._owns_client = http_client is None
        self._http = (
            http_client
            if http_client is not None
            else httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        )

    async def __aenter__(self) -> KakaoClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After", "")
        try:
            seconds = float(header)
        except ValueError:
            try:
                target = parsedate_to_datetime(header)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                seconds = (target - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = 0.25 * (2**attempt)
        if not math.isfinite(seconds):
            seconds = self._max_retry_delay
        return min(self._max_retry_delay, max(0.0, seconds))

    async def _request(
        self,
        method: str,
        url: str,
        *,
        authenticated: bool = True,
        data: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self.access_token:
                raise ValueError("An access token is required; complete Kakao Login first")
            headers["Authorization"] = f"Bearer {self.access_token}"
        attempts = self._read_retries if method == "GET" else 0
        for attempt in range(attempts + 1):
            try:
                response = await self._http.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                    params=params,
                    timeout=self._timeout,
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt == attempts:
                    raise
                await asyncio.sleep(min(self._max_retry_delay, 0.25 * (2**attempt)))
                continue
            if attempt < attempts and (response.status_code == 429 or response.status_code >= 500):
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue
            try:
                payload = response.json()
            except ValueError:
                raise KakaoAPIError(response.status_code, None, "Non-JSON API response") from None
            if not isinstance(payload, dict):
                raise KakaoAPIError(response.status_code, None, "Expected JSON object")
            code = payload.get("code")
            if (
                not 200 <= response.status_code < 300
                or payload.get("error")
                or (isinstance(code, int) and code < 0)
            ):
                raise KakaoAPIError(
                    response.status_code,
                    code if code is not None else payload.get("error"),
                    str(payload.get("msg") or payload.get("error_description") or ""),
                )
            return payload
        raise AssertionError("unreachable")

    def _oauth_data(self) -> dict[str, str]:
        if not self.client_id:
            raise ValueError("client_id (REST API key) is required for OAuth operations")
        data = {"client_id": self.client_id}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        return data

    def _accept_tokens(
        self, payload: dict[str, Any], previous_refresh: str | None = None
    ) -> OAuthTokens:
        token = payload.get("access_token")
        expires = payload.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or type(expires) not in {int, float}
            or expires <= 0
            or not math.isfinite(expires)
        ):
            raise KakaoAPIError(200, None, "Invalid OAuth token response")
        now = time.time()
        previous = self.tokens
        refresh_expiry = payload.get("refresh_token_expires_in")
        tokens = OAuthTokens(
            access_token=token,
            refresh_token=payload.get("refresh_token", previous_refresh),
            expires_at=now + expires,
            refresh_expires_at=now + refresh_expiry
            if isinstance(refresh_expiry, (int, float))
            else previous.refresh_expires_at
            if previous
            else None,
            scope=payload.get("scope", previous.scope if previous else None),
        )
        self.tokens = tokens
        self.access_token = tokens.access_token
        return tokens

    async def exchange_code(
        self, code: str, redirect_uri: str, *, expected_state: str, received_state: str | None
    ) -> OAuthTokens:
        """Validate callback state, exchange a one-use code and keep tokens in memory."""
        validate_state(expected_state, received_state)
        _nonempty(code, "code")
        _web_url(redirect_uri, "redirect_uri")
        data = self._oauth_data()
        data.update(grant_type="authorization_code", code=code, redirect_uri=redirect_uri)
        return self._accept_tokens(
            await self._request("POST", f"{_AUTH}/oauth/token", authenticated=False, data=data)
        )

    async def refresh(self, refresh_token: str | None = None) -> OAuthTokens:
        """Refresh explicitly; keep old refresh token when Kakao omits replacement."""
        token = refresh_token or (self.tokens.refresh_token if self.tokens else None)
        if not token:
            raise ValueError("refresh_token is required")
        data = self._oauth_data()
        data.update(grant_type="refresh_token", refresh_token=token)
        return self._accept_tokens(
            await self._request("POST", f"{_AUTH}/oauth/token", authenticated=False, data=data),
            token,
        )

    async def list_friends(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        order: str = "asc",
        friend_order: str = "favorite",
    ) -> dict[str, Any]:
        """Return one page, including elements/total_count/after_url as provided."""
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative; limit must be between 1 and 100")
        if order not in {"asc", "desc"} or friend_order not in {"favorite", "nickname"}:
            raise ValueError("Invalid friend list ordering")
        return await self._request(
            "GET",
            f"{_API}/v1/api/talk/friends",
            params={"offset": offset, "limit": limit, "order": order, "friend_order": friend_order},
        )

    async def send_self_text(
        self, text: str, *, link_url: str, button_title: str | None = None
    ) -> dict[str, Any]:
        """Send a text template to your own chat. link_url domain must be registered."""
        return await self.send_self_template(_text_template(text, link_url, button_title))

    async def send_friends_text(
        self,
        receiver_uuids: Sequence[str],
        text: str,
        *,
        link_url: str,
        button_title: str | None = None,
    ) -> dict[str, Any]:
        return await self.send_friends_template(
            receiver_uuids, _text_template(text, link_url, button_title)
        )

    async def send_self_template(self, template: Mapping[str, Any]) -> dict[str, Any]:
        """Send a documented default-template object (text/feed/list/location...)."""
        return await self._request(
            "POST",
            f"{_API}/v2/api/talk/memo/default/send",
            data={"template_object": json.dumps(dict(template), ensure_ascii=False)},
        )

    async def send_friends_template(
        self, receiver_uuids: Sequence[str], template: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return full response including partial delivery failure_info; never retry."""
        values = _recipients(receiver_uuids)
        return await self._request(
            "POST",
            f"{_API}/v1/api/talk/friends/message/default/send",
            data={
                "receiver_uuids": json.dumps(values),
                "template_object": json.dumps(dict(template), ensure_ascii=False),
            },
        )

    async def send_self_custom(
        self, template_id: int, *, template_args: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{_API}/v2/api/talk/memo/send",
            data=self._custom_data(template_id, template_args),
        )

    async def send_friends_custom(
        self,
        receiver_uuids: Sequence[str],
        template_id: int,
        *,
        template_args: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        values = _recipients(receiver_uuids)
        data = self._custom_data(template_id, template_args)
        data["receiver_uuids"] = json.dumps(values)
        return await self._request("POST", f"{_API}/v1/api/talk/friends/message/send", data=data)

    @staticmethod
    def _custom_data(template_id: int, args: Mapping[str, str] | None) -> dict[str, Any]:
        if type(template_id) is not int or template_id <= 0:
            raise ValueError("template_id must be a positive integer")
        data: dict[str, Any] = {"template_id": str(template_id)}
        if args is not None:
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in args.items()):
                raise ValueError("template_args must contain string keys and values")
            data["template_args"] = json.dumps(dict(args), ensure_ascii=False)
        return data
