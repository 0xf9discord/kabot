"""Experimental profile-specific LOCO client from pinned public protocol sources."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from bson import Int64
from bson.binary import Binary

from .packet import LocoPacket, PacketError
from .session import LocoSession
from .transport import Endpoint, LocoConnectionError, LocoTransport

if TYPE_CHECKING:
    from .open_profile import OpenChatProfile


def positive_id(value: int, label: str) -> Int64:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise ValueError(f"{label} must be a positive signed 64-bit integer")
    return Int64(value)


@dataclass(frozen=True)
class Credentials:
    user_id: int
    oauth_token: str = field(repr=False)
    device_uuid: str = field(repr=False)
    app_version: str
    profile: str = "mac"

    def __post_init__(self):
        positive_id(self.user_id, "user_id")
        if self.profile not in ("mac", "android"):
            raise ValueError("profile must be mac or android")
        for name in ("oauth_token", "device_uuid", "app_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

    def login_body(self) -> dict[str, Any]:
        result = {
            "appVer": self.app_version,
            "prtVer": "1",
            "os": self.profile,
            "lang": "ko",
            "duuid": self.device_uuid,
            "oauthToken": self.oauth_token,
            "ntype": 0,
            "MCCMNC": "45006" if self.profile == "android" else "99999",
            "revision": 0,
            "chatIds": [],
            "maxIds": [],
            "lastTokenId": Int64(0),
            "lbk": 0,
            "rp": Binary(b"\x00\x00\xff\xff\x00\x00"),
            "bg": self.profile == "android",
        }
        if self.profile == "mac":
            result["dtype"] = 2
        return result

    def booking_body(self) -> dict[str, Any]:
        result = {
            "MCCMNC": "45006" if self.profile == "android" else "99999",
            "os": self.profile,
            "userId": Int64(self.user_id),
        }
        if self.profile == "mac":
            result["model"] = ""
        return result

    def checkin_body(self) -> dict[str, Any]:
        result = {
            "userId": Int64(self.user_id),
            "os": self.profile,
            "ntype": 0,
            "appVer": self.app_version,
            "MCCMNC": "45006" if self.profile == "android" else "99999",
            "lang": "ko",
        }
        if self.profile == "mac":
            result.update(countryISO="KR", useSub=True)
        return result


@dataclass(frozen=True)
class Message:
    chat_id: int
    log_id: int
    author_id: int
    type: int
    text: str = field(repr=False)


def received_messages(packet: LocoPacket) -> list[Message]:
    """Parse flat MSG, nested chatLog and batched SYNCMSG; preserve 64-bit IDs."""
    if packet.method not in ("MSG", "SYNCMSG") or packet.status != 0:
        raise PacketError("Not a successful message packet")
    envelope = packet.body
    if packet.method == "SYNCMSG" and "chatLogs" in envelope:
        rows = envelope["chatLogs"]
        if not isinstance(rows, list):
            raise PacketError("SYNCMSG chatLogs must be a list")
    elif "chatLog" in envelope:
        rows = [envelope["chatLog"]]
    else:
        rows = [envelope]
    messages = []
    for row in rows:
        if not isinstance(row, dict):
            raise PacketError("Message must be a BSON document")
        chat = row.get("chatId", envelope.get("chatId"))
        try:
            chat = positive_id(chat, "chat_id")
            log = positive_id(row.get("logId"), "log_id")
            author = row.get("authorId", 0)
            if isinstance(author, bool) or not isinstance(author, int) or not 0 <= author < 2**63:
                raise ValueError("invalid author identity")
        except ValueError:
            raise PacketError("Message contains an invalid identity") from None
        if "chatId" in envelope:
            outer = envelope["chatId"]
            if isinstance(outer, bool) or not isinstance(outer, int) or outer != chat:
                raise PacketError("Message chat ID conflicts with envelope")
        kind = row.get("type")
        message = row.get("message", "")
        if isinstance(kind, bool) or not isinstance(kind, int) or not isinstance(message, str):
            raise PacketError("Message contains invalid type or text")
        messages.append(Message(int(chat), int(log), int(author), int(kind), message))
    return messages


class PersonalClient:
    """Booking -> CHECKIN -> LOGINLIST with explicit credentials and no retry loops.

    Android26.8.2 uses TLS throughout; the legacy macOS reference uses RSA/GCM.
    Profiles come from pinned public sources, separately from native observations.
    """

    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout: float = 10,
        booking: Endpoint = Endpoint("booking-loco.kakao.com", 443, True),
        checkin_port: int | None = None,
        public_key_der: bytes | None = None,
        connector: Callable[[Endpoint], Awaitable[LocoTransport]] | None = None,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.credentials = credentials
        self.timeout, self.booking = timeout, booking
        if checkin_port is not None:
            Endpoint("validation", checkin_port)
        self.checkin_port, self.public_key_der = checkin_port, public_key_der
        self._connector = connector
        self._progress = progress
        self.session: LocoSession | None = None
        self.login_data: dict[str, Any] | None = None
        self._heartbeat: asyncio.Task | None = None

    async def _open(self, endpoint: Endpoint, *, stage: str = "chat_connect") -> LocoSession:
        details = {
            "stage": stage,
            "host": endpoint.host,
            "port": endpoint.port,
            "tls": endpoint.tls,
            "server_name": endpoint.server_name or endpoint.host,
        }
        if self._progress:
            self._progress({**details, "event": "connecting"})
        try:
            transport = (
                await self._connector(endpoint)
                if self._connector
                else await LocoTransport.connect(
                    endpoint, timeout=self.timeout, public_key_der=self.public_key_der
                )
            )
        except ssl.SSLCertVerificationError as error:
            if self._progress:
                self._progress(
                    {
                        **details,
                        "event": "tls_failed",
                        "verify_code": error.verify_code,
                        "verify_message": error.verify_message,
                    }
                )
            raise
        return LocoSession(transport, command_timeout=self.timeout)

    async def _oneshot(self, endpoint: Endpoint, method: str, body: dict) -> LocoPacket:
        async with await self._open(endpoint, stage=method.lower()) as session:
            return await session.request(method, body)

    async def discover(self) -> Endpoint:
        creds = self.credentials
        config = await self._oneshot(
            self.booking,
            "GETCONF",
            creds.booking_body(),
        )
        ticket = config.body.get("ticket")
        hosts = ticket.get("lsl") if isinstance(ticket, dict) else None
        if not isinstance(hosts, list) or not hosts or not isinstance(hosts[0], str):
            raise LocoConnectionError("Booking response has no ticket.lsl host")
        android = creds.profile == "android"
        checkin_port = self.checkin_port
        if checkin_port is None:
            if android:
                wifi = config.body.get("wifi")
                ports = wifi.get("ports") if isinstance(wifi, dict) else None
                if not isinstance(ports, list) or not ports:
                    raise LocoConnectionError("Booking response has no wifi.ports")
                checkin_port = ports[0]
            else:
                checkin_port = 995
        # No automatic TLS/cipher downgrade, port sweeping or certificate bypass.
        response = await self._oneshot(
            Endpoint(hosts[0], checkin_port, tls=android),
            "CHECKIN",
            creds.checkin_body(),
        )
        try:
            host = response.body["host"]
            server_name = None
            if android:
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    pass
                else:
                    # Discovery supplies an IP, but this Kakao service presents a
                    # kakao.com certificate. Bind verification to that explicit
                    # source-backed identity, retaining CA + signature checks.
                    # openkakao-cli 6ca6ea2, client.rs KakaoVerifier / PR60.
                    server_name = "kakao.com"
            return Endpoint(host, response.body["port"], tls=android, server_name=server_name)
        except (KeyError, ValueError, TypeError):
            raise LocoConnectionError("CHECKIN response has no valid host/port") from None

    async def connect(self, *, endpoint: Endpoint | None = None) -> dict[str, Any]:
        if self.session is not None:
            raise LocoConnectionError("Close the previous session before connecting again")
        session = await self._open(endpoint or await self.discover())
        try:
            response = await session.request("LOGINLIST", self.credentials.login_body())
            user = response.body.get("userId")
            if (
                isinstance(user, bool)
                or not isinstance(user, int)
                or user != self.credentials.user_id
            ):
                raise LocoConnectionError("LOGINLIST did not confirm the expected user ID")
            self.session, self.login_data = session, response.body
            self._heartbeat = asyncio.create_task(self._keepalive(), name="kabot-loco-ping")
            return response.body
        except BaseException:
            await session.close()
            raise

    def _session(self) -> LocoSession:
        if self.session is None or self.session.closed:
            raise LocoConnectionError("An authenticated LOCO session is required")
        return self.session

    async def list_chats(self, *, resolve_names: bool = True, max_pages: int = 10) -> list[dict]:
        """Fetch complete paginated membership and optional read-only canonical room names."""
        from .chats import collect_chats

        return await collect_chats(
            self._session(), self.login_data or {}, resolve_names=resolve_names, max_pages=max_pages
        )

    async def _keepalive(self):
        try:
            while True:
                await asyncio.sleep(30)
                await self._session().request("PING")
        except asyncio.CancelledError:
            pass
        except Exception:
            if self.session is not None:
                await self.session.close()

    async def list_open_links(self) -> list[dict]:
        """Read account-associated open links/profiles (SYNCLINK); no room mutation."""
        from .open_profile import collect_open_links

        return await collect_open_links(self._session())

    async def get_open_profile(self, chat_id: int) -> dict[str, Any]:
        """Read this account's participant profile in an existing open-chat room."""
        from .open_profile import room_link_id

        session = self._session()
        await room_link_id(session, chat_id)
        response = await session.request(
            "MEMBER",
            {
                "chatId": positive_id(chat_id, "chat_id"),
                "memberIds": [positive_id(self.credentials.user_id, "user_id")],
            },
        )
        body = response.body
        if "chatId" in body:
            try:
                returned = positive_id(body["chatId"], "chat_id")
            except ValueError:
                raise PacketError("MEMBER contains an invalid chat ID") from None
            if returned != chat_id:
                raise PacketError("MEMBER returned a different room")
        members = body.get("members")
        if isinstance(members, list):
            for member in members:
                if isinstance(member, dict):
                    identity = member.get("userId")
                    if (
                        isinstance(identity, int)
                        and not isinstance(identity, bool)
                        and identity == self.credentials.user_id
                    ):
                        return member
        raise PacketError("MEMBER did not return this account's profile")

    async def change_open_profile(self, chat_id: int, profile: OpenChatProfile) -> dict[str, Any]:
        """Switch this account's room profile once. Never retries an uncertain write.

        profile must be OpenChatProfile.main(), .anonymous(nickname, path), or
        .link(profile_link_id). Server restrictions still apply. A successful
        response is an acknowledgement; use get_open_profile to read back state.
        """
        from .open_profile import OpenChatProfile, room_link_id

        if not isinstance(profile, OpenChatProfile):
            raise TypeError("profile must be an OpenChatProfile")
        session = self._session()
        link_id = await room_link_id(session, chat_id)
        response = await session.request("UPLINKPROF", {"li": link_id, **profile.to_body()})
        return response.body

    async def loopchange(
        self,
        chat_id: int,
        profiles: Iterable[OpenChatProfile],
        *,
        interval: float = 60,
        max_changes: int | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> int:
        """Rotate room profiles in order; return acknowledged change count on stop.

        First change is immediate. interval is the delay after each completed
        change (minimum one second). None max_changes repeats until stop_event
        is set or the task is cancelled. Any server/connection error propagates
        immediately; a failed or uncertain write is never retried.
        """
        from .open_profile import OpenChatProfile

        positive_id(chat_id, "chat_id")
        choices = tuple(profiles)
        if not choices or any(not isinstance(p, OpenChatProfile) for p in choices):
            raise ValueError("profiles must contain at least one OpenChatProfile")
        if (
            isinstance(interval, bool)
            or not isinstance(interval, (int, float))
            or not math.isfinite(interval)
            or interval < 1
        ):
            raise ValueError("interval must be finite and at least one second")
        if max_changes is not None and (
            isinstance(max_changes, bool) or not isinstance(max_changes, int) or max_changes < 1
        ):
            raise ValueError("max_changes must be a positive integer or None")
        if stop_event is not None and not isinstance(stop_event, asyncio.Event):
            raise TypeError("stop_event must be an asyncio.Event")
        completed = 0
        while max_changes is None or completed < max_changes:
            if stop_event is not None and stop_event.is_set():
                break
            await self.change_open_profile(chat_id, choices[completed % len(choices)])
            completed += 1
            if max_changes is not None and completed >= max_changes:
                break
            if stop_event is None:
                await asyncio.sleep(interval)
            else:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=interval)
                except TimeoutError:
                    pass
        return completed

    async def send_text(self, chat_id: int, message: str) -> dict[str, Any]:
        chat_id = positive_id(chat_id, "chat_id")
        if not isinstance(message, str) or not message.strip() or len(message) > 3000:
            raise ValueError("Text must contain 1..3000 characters")
        session = self._session()
        await session.request("CHATONROOM", {"chatId": chat_id})
        response = await session.request(
            "WRITE", {"chatId": chat_id, "msg": message, "type": 1, "noSeen": False}
        )
        return response.body

    async def messages(self) -> AsyncIterator[Message]:
        async for packet in self._session().events():
            if packet.method in ("CHANGESVR", "KICKOUT"):
                await self.close()
                raise LocoConnectionError(f"Server requested session stop ({packet.method})")
            if packet.method in ("MSG", "SYNCMSG"):
                for message in received_messages(packet):
                    yield message

    async def close(self):
        if self._heartbeat is not None and self._heartbeat is not asyncio.current_task():
            self._heartbeat.cancel()
            await asyncio.gather(self._heartbeat, return_exceptions=True)
        self._heartbeat = None
        if self.session is not None:
            await self.session.close()
        self.session, self.login_data = None, None

    async def __aenter__(self) -> PersonalClient:
        return self

    async def __aexit__(self, *args):
        await self.close()
