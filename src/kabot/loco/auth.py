"""Experimental, explicit Android sub-device authentication.

Protocol facts: loco-wrapper 1dec3b79e59f2776ebd1f03e60744162ff195b24.
No app installation, cache extraction, password persistence or automatic retries.
This source-derived profile has not been authenticated against a live server here.
"""

from __future__ import annotations

import hashlib
import math
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

import httpx

_BASE = "https://katalk.kakao.com/android/account/"
_DEVICE_UUID = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class AndroidAuthProfile:
    app_version: str = "26.8.2"
    os_version: str = "13"
    api_level: str = "33"
    language: str = "ko"
    device_name: str = "SM-T870"
    source_commit: str = "1dec3b79e59f2776ebd1f03e60744162ff195b24"

    def __post_init__(self) -> None:
        # The signature seed below is paired with the source version. Do not
        # silently advertise an arbitrary newer version with an old signature.
        if self.app_version != "26.8.2":
            raise ValueError("This source-derived profile supports version 26.8.2 only")
        for value in (self.os_version, self.api_level, self.language, self.device_name):
            if (
                not isinstance(value, str)
                or not value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError(
                    "Profile fields must be nonempty strings without control characters"
                )

    @property
    def user_agent(self) -> str:
        return f"KT/{self.app_version} An/{self.os_version} {self.language}"

    @property
    def agent(self) -> str:
        return f"android/{self.app_version}/{self.language}"

    def xvc(self, email: str) -> str:
        _text(email, "email")
        source = f"ALBUS|{self.user_agent}|IAN|{email}|SEOGI"
        return hashlib.sha512(source.encode("utf-8")).hexdigest()[:16]


ANDROID_26_8_2 = AndroidAuthProfile()


def generate_device_uuid() -> str:
    """Generate a stable-installation ID; callers retain it with their tokens."""
    return secrets.token_hex(32)


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} must be a nonempty string without control characters")
    return value


def _identity(email: str, password: str, device_uuid: str) -> None:
    _text(email, "email")
    # Passwords are data, so spaces/control characters must not be normalized.
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a nonempty string")
    if not isinstance(device_uuid, str) or not _DEVICE_UUID.fullmatch(device_uuid):
        raise ValueError("device_uuid must be 64 lowercase hexadecimal characters")


class AndroidAuthError(Exception):
    """Safe failure metadata; no request/response bodies are attached or printed."""

    def __init__(
        self,
        phase: str,
        reason: str,
        *,
        http_status: int | None = None,
        server_status: int | None = None,
    ):
        self.phase = phase
        self.reason = reason
        self.http_status = http_status
        self.server_status = server_status
        super().__init__(
            f"Android authentication {phase} failed "
            f"({reason}; HTTP={http_status}; status={server_status})"
        )


@dataclass(frozen=True)
class AndroidTokens:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    user_id: int
    device_uuid: str = field(repr=False)
    app_version: str = "26.8.2"

    def to_credentials(self):
        """Create personal-client credentials with a consistent Android profile."""
        from .client import Credentials

        return Credentials(
            self.user_id, self.access_token, self.device_uuid, self.app_version, profile="android"
        )


@dataclass(frozen=True)
class RegistrationRequired:
    device_uuid: str = field(repr=False)
    server_status: int = -100


@dataclass(frozen=True)
class RegistrationChallenge:
    passcode: str = field(repr=False)
    remaining_seconds: int
    device_uuid: str = field(repr=False)


@dataclass(frozen=True)
class RegistrationStatus:
    registered: bool
    server_status: int
    remaining_seconds: int | None = None
    next_request_interval_seconds: int | None = None


class AndroidAuthClient:
    """One explicit request per method, including each registration poll.

    New-device registration requires confirmation on the user's logged-in phone.
    Returning a challenge does not mean confirmation or login has succeeded.
    The caller owns injected AsyncClient lifetimes. TLS verification is always on
    for internally created clients; injected clients must retain that guarantee.
    """

    def __init__(
        self,
        *,
        profile: AndroidAuthProfile = ANDROID_26_8_2,
        timeout: float = 15,
        http_client: httpx.AsyncClient | None = None,
    ):
        if not isinstance(profile, AndroidAuthProfile):
            raise TypeError("profile must be AndroidAuthProfile")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.profile = profile
        self._timeout = timeout
        self._owns_client = http_client is None
        self._http = (
            http_client
            if http_client is not None
            else httpx.AsyncClient(verify=True, follow_redirects=False, timeout=timeout)
        )

    async def __aenter__(self) -> AndroidAuthClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _request(
        self,
        phase: str,
        route: str,
        *,
        email: str | None = None,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "A": self.profile.agent,
            "User-Agent": self.profile.user_agent,
            "Accept-Language": self.profile.language,
            "Accept": "application/json",
        }
        if email is not None:
            headers["X-VC"] = self.profile.xvc(email)
        if json_body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        elif data is not None or params is not None:
            # The source sends this header even on the bodyless allowlist GET.
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        method = "GET" if params is not None else "POST"
        try:
            response = await self._http.request(
                method,
                _BASE + route,
                headers=headers,
                data=data,
                json=json_body,
                params=params,
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise AndroidAuthError(phase, "timeout") from None
        except httpx.HTTPError:
            raise AndroidAuthError(phase, "transport_error") from None
        if not 200 <= response.status_code < 300:
            raise AndroidAuthError(phase, "http_error", http_status=response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise AndroidAuthError(
                phase, "malformed_response", http_status=response.status_code
            ) from None
        if not isinstance(payload, dict):
            raise AndroidAuthError(phase, "malformed_response", http_status=response.status_code)
        return payload

    @staticmethod
    def _status(payload: dict[str, Any], phase: str) -> int:
        status = payload.get("status")
        if type(status) is not int:
            raise AndroidAuthError(phase, "malformed_status", http_status=200)
        return status

    async def check_model(self) -> bool:
        """Check the declared model allowlist; no account/password is sent."""
        payload = await self._request(
            "allowlist", "allowlist.json", params={"model_name": self.profile.device_name}
        )
        allowed = payload.get("allowlisted")
        if type(allowed) is not bool:
            raise AndroidAuthError("allowlist", "malformed_response", http_status=200)
        return allowed

    async def login(
        self, email: str, password: str, device_uuid: str, *, force: bool = False
    ) -> AndroidTokens | RegistrationRequired:
        """Attempt exactly once. -100 returns a challenge requirement, not success."""
        _identity(email, password, device_uuid)
        if type(force) is not bool:
            raise TypeError("force must be bool")
        payload = await self._request(
            "login",
            "login.json",
            email=email,
            data={
                "password": password,
                "device_name": self.profile.device_name,
                "forced": "true" if force else "false",
                "permanent": "true",
                "email": email,
                "device_uuid": device_uuid,
            },
        )
        status = self._status(payload, "login")
        if status == -100:
            return RegistrationRequired(device_uuid)
        if status != 0:
            raise AndroidAuthError(
                "login", "server_rejected", http_status=200, server_status=status
            )
        token, refresh, user_id = (
            payload.get("access_token"),
            payload.get("refresh_token"),
            payload.get("userId"),
        )
        if (
            not isinstance(token, str)
            or not token
            or type(user_id) is not int
            or not 0 < user_id < 2**63
            or (refresh is not None and not isinstance(refresh, str))
        ):
            raise AndroidAuthError("login", "malformed_credentials", http_status=200)
        return AndroidTokens(token, refresh or None, user_id, device_uuid, self.profile.app_version)

    async def request_registration(
        self, email: str, password: str, device_uuid: str
    ) -> RegistrationChallenge:
        """Explicitly generate a code for confirmation on the user's phone."""
        _identity(email, password, device_uuid)
        payload = await self._request(
            "generate",
            "passcodeLogin/generate",
            email=email,
            json_body={
                "email": email,
                "password": password,
                "permanent": True,
                "device": {
                    "name": self.profile.device_name,
                    "uuid": device_uuid,
                    "model": self.profile.device_name,
                    "osVersion": self.profile.api_level,
                },
            },
        )
        status = payload.get("status")
        if status is not None and (type(status) is not int or status != 0):
            raise AndroidAuthError(
                "generate",
                "server_rejected",
                http_status=200,
                server_status=status if type(status) is int else None,
            )
        code, remaining = payload.get("passcode"), payload.get("remainingSeconds")
        if (
            not isinstance(code, str)
            or not code.isascii()
            or not code.isdigit()
            or type(remaining) is not int
            or remaining <= 0
        ):
            raise AndroidAuthError("generate", "malformed_challenge", http_status=200)
        return RegistrationChallenge(code, remaining, device_uuid)

    async def poll_registration_once(
        self, email: str, password: str, device_uuid: str
    ) -> RegistrationStatus:
        """One poll only. Wait for server interval and phone approval before retrying.

        The displayed passcode is entered on the phone; it is not sent by this
        endpoint. A registered result still requires a fresh explicit login().
        """
        _identity(email, password, device_uuid)
        payload = await self._request(
            "register",
            "passcodeLogin/registerDevice",
            email=email,
            json_body={"email": email, "password": password, "device": {"uuid": device_uuid}},
        )
        status = self._status(payload, "register")
        if status == 0:
            return RegistrationStatus(True, 0)
        if status != -100:
            raise AndroidAuthError(
                "register", "server_rejected", http_status=200, server_status=status
            )
        remaining, interval = (
            payload.get("remainingSeconds"),
            payload.get("nextRequestIntervalInSeconds"),
        )
        if (
            type(remaining) is not int
            or remaining < 0
            or type(interval) is not int
            or interval <= 0
        ):
            raise AndroidAuthError(
                "register", "malformed_pending_response", http_status=200, server_status=status
            )
        return RegistrationStatus(False, status, remaining, interval)
