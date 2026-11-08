import asyncio
import json

import pytest

pytest.importorskip("bson")
pytest.importorskip("cryptography")

from kabot.loco import Credentials
from kabot.loco.auth import (
    AndroidAuthError,
    AndroidTokens,
    RegistrationChallenge,
    RegistrationRequired,
    RegistrationStatus,
)
from kabot.loco.interactive import interactive_login, verify_saved_session
from kabot.loco.storage import load_session, save_session


class FakeAuth:
    def __init__(self, *, registration=False, fail=False):
        self.registration, self.fail = registration, fail
        self.calls = []
        self.logins = 0
        self.polls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def check_model(self):
        return True

    async def login(self, email, password, uuid):
        self.calls.append((email, password, uuid))
        self.logins += 1
        if self.fail:
            raise AndroidAuthError("login", "server_rejected", server_status=12)
        if self.registration and self.logins == 1:
            return RegistrationRequired(uuid)
        return AndroidTokens("fake-access-token", "fake-refresh-token", 123, uuid)

    async def request_registration(self, email, password, uuid):
        return RegistrationChallenge("fake-passcode", 60, uuid)

    async def poll_registration_once(self, email, password, uuid):
        self.polls += 1
        return RegistrationStatus(True, 0)


class FakeClient:
    def __init__(self, creds):
        assert creds.profile == "android"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def connect(self):
        return {"chatDatas": [{"c": 42}]}


@pytest.mark.parametrize("registration", [False, True])
def test_local_login_encrypted_session_and_redacted_status(tmp_path, registration):
    auth = FakeAuth(registration=registration)
    answers = iter(["fake-email@example.test", "", ""])
    secrets = iter(["independent-vault-key", "independent-vault-key", "fake-account-password"])
    output = []
    session = tmp_path / "session.kabot"
    status = tmp_path / "status.json"
    result = asyncio.run(
        interactive_login(
            session,
            status_path=status,
            input_fn=lambda _: next(answers),
            secret_fn=lambda _: next(secrets),
            print_fn=output.append,
            auth_factory=lambda: auth,
            client_factory=FakeClient,
        )
    )
    assert result.user_id == 123
    assert load_session(session, "independent-vault-key") == result
    assert auth.logins == (2 if registration else 1)
    assert auth.polls == int(registration)
    record = json.loads(status.read_text())
    assert record["phase"] == "connected" and record["authenticated"]
    assert record["chat_count"] == 1
    for secret in [
        "fake-email",
        "fake-access-token",
        "fake-refresh-token",
        "fake-account-password",
        "independent-vault-key",
        "fake-passcode",
        result.device_uuid,
    ]:
        assert secret not in status.read_text()
        assert secret.encode() not in session.read_bytes()


def test_server_rejection_does_not_retry_or_save_credentials(tmp_path):
    auth = FakeAuth(fail=True)
    session, status = tmp_path / "session.kabot", tmp_path / "status.json"
    secrets = iter(["independent-vault-key", "independent-vault-key", "fake-account-password"])
    with pytest.raises(AndroidAuthError):
        asyncio.run(
            interactive_login(
                session,
                status_path=status,
                input_fn=lambda _: "fake-email@example.test",
                secret_fn=lambda _: next(secrets),
                print_fn=lambda _: None,
                auth_factory=lambda: auth,
            )
        )
    assert auth.logins == 1
    assert not session.exists()
    record = json.loads(status.read_text())
    assert record["phase"] == "failed"
    assert record["server_status"] == 12
    assert "fake-account-password" not in status.read_text()


def test_existing_session_refused_before_prompts_and_requests(tmp_path):
    session = tmp_path / "session.kabot"
    session.write_bytes(b"existing")

    def forbidden(*args):
        raise AssertionError("must not prompt or connect")

    with pytest.raises(FileExistsError):
        asyncio.run(
            interactive_login(
                session, input_fn=forbidden, secret_fn=forbidden, auth_factory=forbidden
            )
        )
    assert session.read_bytes() == b"existing"


def test_explicit_relogin_reuses_device_and_replaces_encrypted_session(tmp_path):
    session = tmp_path / "session.kabot"
    previous = Credentials(123, "old-token", "a" * 64, "26.8.2", profile="android")
    save_session(session, previous, "independent-vault-key")
    auth = FakeAuth()
    secrets = iter(["independent-vault-key", "fake-account-password"])
    result = asyncio.run(
        interactive_login(
            session,
            replace=True,
            input_fn=lambda _: "fake@example.test",
            secret_fn=lambda _: next(secrets),
            print_fn=lambda _: None,
            auth_factory=lambda: auth,
            client_factory=FakeClient,
        )
    )
    assert auth.calls[0][2] == previous.device_uuid
    assert load_session(session, "independent-vault-key") == result
    assert result.oauth_token == "fake-access-token"


@pytest.mark.parametrize("tls_failure", [False, True])
def test_saved_session_verify_redacts_secrets_and_reports_tls_failure(tmp_path, tls_failure):
    import ssl

    session, status = tmp_path / "session.kabot", tmp_path / "status.json"
    credentials = Credentials(123, "private-fake-token", "a" * 64, "26.8.2", profile="android")
    save_session(session, credentials, "independent-vault-key")

    class VerificationClient:
        def __init__(self, creds, *, progress):
            assert creds == credentials
            self.progress = progress

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def connect(self):
            self.progress(
                {
                    "stage": "chat_connect",
                    "host": "203.0.113.7",
                    "port": 443,
                    "server_name": "kakao.com",
                    "event": "connecting",
                }
            )
            if tls_failure:
                error = ssl.SSLCertVerificationError(1, "certificate mismatch")
                error.verify_code = 62
                error.verify_message = "Hostname mismatch"
                raise error
            return {"chatDatas": [{"c": 42}]}

    async def run():
        return await verify_saved_session(
            session,
            status_path=status,
            secret_fn=lambda _: "independent-vault-key",
            print_fn=lambda _: None,
            client_factory=VerificationClient,
        )

    if tls_failure:
        with pytest.raises(ssl.SSLCertVerificationError):
            asyncio.run(run())
    else:
        assert asyncio.run(run()) == 1
    content = status.read_text()
    record = json.loads(content)
    assert record["phase"] == ("failed" if tls_failure else "connected")
    assert record["authenticated"] is not tls_failure
    if tls_failure:
        assert record["verify_code"] == 62
        assert record["connection"]["server_name"] == "kakao.com"
    for private in (credentials.oauth_token, credentials.device_uuid, "independent-vault-key"):
        assert private not in content
