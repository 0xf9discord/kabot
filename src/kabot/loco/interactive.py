"""Local terminal login. Account passwords and session keys never enter status files."""

from __future__ import annotations

import asyncio
import getpass
import json
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .auth import (
    AndroidAuthClient,
    AndroidAuthError,
    AndroidTokens,
    RegistrationRequired,
    generate_device_uuid,
)
from .client import PersonalClient
from .storage import load_session, save_session


@dataclass
class LoginStatus:
    path: Path | None = None
    authenticated: bool = False

    def update(self, phase: str, **fields):
        if self.path is not None:
            result = {
                "phase": phase,
                "authenticated": self.authenticated,
                "updated_utc": datetime.now(UTC).isoformat(),
                **fields,
            }
            # Status is deliberately limited to phase/status codes. No email,
            # user ID, password, token, passcode, UUID, chat content or session key.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


async def interactive_login(
    session_path: str | Path,
    *,
    status_path: str | Path | None = None,
    input_fn=input,
    secret_fn=getpass.getpass,
    print_fn=print,
    auth_factory=AndroidAuthClient,
    client_factory=PersonalClient,
    verify_loco: bool = True,
    replace: bool = False,
):
    path = Path(session_path)
    existing = path.exists()
    if existing and not replace:
        raise FileExistsError(
            "Session already exists. Use a different path or unlock the saved session."
        )
    status = LoginStatus(Path(status_path) if status_path else None)
    status.update("waiting_for_local_input")
    print_fn("Kabot Android 26.8.2 실험용 로그인입니다. 입력은 이 컴퓨터에서만 처리합니다.")

    async def ask(prompt, *, secret=False):
        return await asyncio.to_thread(secret_fn if secret else input_fn, prompt)

    password = passphrase = ""
    try:
        if existing:
            passphrase = await ask("기존 세션 파일 암호: ", secret=True)
            previous = load_session(path, passphrase)
            if previous.profile != "android":
                raise ValueError("Use a new session file for an Android login")
            device_uuid = previous.device_uuid
        else:
            passphrase = await ask(
                "세션 파일 암호(카카오 비밀번호와 별개, 12자 이상): ", secret=True
            )
            if len(passphrase) < 12:
                raise ValueError("Session passphrase must contain at least 12 characters")
            if await ask("세션 파일 암호 확인: ", secret=True) != passphrase:
                raise ValueError("Session passphrases do not match")
            device_uuid = generate_device_uuid()
        email = (await ask("카카오 계정 이메일: ")).strip()
        password = await ask("카카오 비밀번호: ", secret=True)
        async with auth_factory() as auth:
            status.update("checking_model")
            if not await auth.check_model():
                raise AndroidAuthError("allowlist", "model_not_allowed")
            status.update("authenticating")
            result = await auth.login(email, password, device_uuid)
            if isinstance(result, RegistrationRequired):
                print_fn("이 기기의 등록이 필요합니다. 기존 휴대폰 카카오톡으로 승인해야 합니다.")
                if (
                    await ask("기기 등록 요청을 시작하려면 Enter, 취소는 q: ")
                ).strip().lower() == "q":
                    status.update("canceled")
                    return None
                challenge = await auth.request_registration(email, password, device_uuid)
                print_fn(f"휴대폰에서 확인할 등록 번호: {challenge.passcode}")
                deadline = time.monotonic() + challenge.remaining_seconds
                earliest_poll = time.monotonic()
                while True:
                    status.update("waiting_for_phone_confirmation")
                    if (
                        await ask("휴대폰에서 등록을 승인한 뒤 Enter, 취소는 q: ")
                    ).strip().lower() == "q":
                        status.update("canceled")
                        return None
                    if time.monotonic() >= deadline:
                        raise AndroidAuthError("registration", "challenge_expired")
                    wait = earliest_poll - time.monotonic()
                    if wait > 0:
                        await asyncio.sleep(wait)
                    if time.monotonic() >= deadline:
                        raise AndroidAuthError("registration", "challenge_expired")
                    registration = await auth.poll_registration_once(email, password, device_uuid)
                    if registration.registered:
                        break
                    if registration.remaining_seconds is not None:
                        deadline = min(deadline, time.monotonic() + registration.remaining_seconds)
                    earliest_poll = time.monotonic() + (
                        registration.next_request_interval_seconds or 1
                    )
                    print_fn("아직 승인되지 않았습니다. 휴대폰 상태를 확인해 주세요.")
                status.update("completing_login")
                result = await auth.login(email, password, device_uuid)
            if not isinstance(result, AndroidTokens):
                raise AndroidAuthError("login", "registration_not_completed")
        credentials = result.to_credentials()
        save_session(path, credentials, passphrase, overwrite=replace)
        status.authenticated = True
        status.update("saved")
        print_fn("로그인 토큰을 암호화된 세션 파일에 저장했습니다.")
        if verify_loco:
            status.update("verifying_loco")
            async with client_factory(credentials) as client:
                data = await client.connect()
                rows = data.get("chatDatas", [])
                count = len(rows) if isinstance(rows, list) else 0
                status.update("connected", chat_count=count)
                print_fn(f"LOCO 로그인 확인 완료. 받은 채팅방 항목 수: {count}")
        return credentials
    except KeyboardInterrupt:
        status.update("canceled")
        raise
    except Exception as error:
        safe = {"error_type": type(error).__name__}
        if isinstance(error, AndroidAuthError):
            safe.update(
                auth_phase=error.phase,
                reason=error.reason,
                http_status=error.http_status,
                server_status=error.server_status,
            )
        from .session import LocoStatusError

        if isinstance(error, LocoStatusError):
            safe.update(method=error.method, server_status=error.status)
        status.update("failed", **safe)
        raise
    finally:
        password = passphrase = ""


async def unlock_session(path: str | Path, *, secret_fn=getpass.getpass):
    passphrase = await asyncio.to_thread(secret_fn, "세션 파일 암호: ")
    return load_session(path, passphrase)


async def verify_saved_session(
    session_path: str | Path,
    *,
    status_path: str | Path | None = None,
    secret_fn=getpass.getpass,
    print_fn=print,
    client_factory=PersonalClient,
):
    """Read-only connection check. Only the local user unlocks their encrypted file."""
    status = LoginStatus(Path(status_path) if status_path else None)
    status.update("waiting_for_session_unlock")
    last_connection = {}

    def progress(event):
        nonlocal last_connection
        last_connection = event
        status.update("connecting", connection=event)

    try:
        credentials = await unlock_session(session_path, secret_fn=secret_fn)
        async with client_factory(credentials, progress=progress) as client:
            data = await client.connect()
            rows = data.get("chatDatas", [])
            count = len(rows) if isinstance(rows, list) else 0
            status.authenticated = True
            status.update("connected", chat_count=count)
            print_fn(f"채팅 서버 로그인 확인 완료. 채팅방 항목 수: {count}")
            return count
    except Exception as error:
        safe = {"error_type": type(error).__name__, "connection": last_connection}
        from .session import LocoStatusError

        if isinstance(error, LocoStatusError):
            safe.update(method=error.method, server_status=error.status)
        if isinstance(error, ssl.SSLCertVerificationError):
            safe.update(verify_code=error.verify_code, verify_message=error.verify_message)
        status.update("failed", **safe)
        raise


async def show_chats(session_path: str | Path):
    credentials = await unlock_session(session_path)
    async with PersonalClient(credentials) as client:
        await client.connect()
        rows = await client.list_chats(resolve_names=True)
        print("chat_id\t제목")
        for row in rows:
            if isinstance(row, dict):
                chat_id = row.get("c", row.get("chatId"))
                if isinstance(chat_id, int) and not isinstance(chat_id, bool):
                    info = row.get("chatInfo", {})
                    title = info.get("name", "") if isinstance(info, dict) else ""
                    if not title:
                        title = ", ".join(
                            name for name in row.get("k", []) if isinstance(name, str)
                        )
                    # Terminal control characters are never printed from remote text.
                    title = "".join(c for c in str(title) if c.isprintable())[:120]
                    print(f"{chat_id}\t{title}")


async def manage_open_profile(session_path: str | Path, *, chat_id=None, profile=None):
    """List links, read the current room profile, or explicitly switch it once."""

    def text(value):
        return "".join(c for c in str(value) if c.isprintable())[:2048]

    credentials = await unlock_session(session_path)
    async with PersonalClient(credentials) as client:
        await client.connect()
        if chat_id is None:
            rows = await client.list_open_links()
            print("link_id\t종류\t이름 (계정 연결 오픈링크 목록)")
            for row in rows:
                print(f"{row['li']}\t{text(row.get('lt', ''))}\t{text(row.get('ln', ''))}")
        elif profile is None:
            row = await client.get_open_profile(chat_id)
            print(f"닉네임: {text(row.get('nickName', ''))}")
            print(f"오픈프로필 ID: {text(row.get('pli', ''))}")
            print(f"이미지 URL: {text(row.get('pi', ''))}")
        else:
            await client.change_open_profile(chat_id, profile)
            print("서버가 프로필 변경 요청을 승인했습니다. 실제 반영은 프로필 조회로 확인하세요.")
