import base64
import json
import os
import stat

import pytest

from kabot.loco.client import Credentials
from kabot.loco.storage import (
    MAX_SESSION_FILE_BYTES,
    SessionStoreError,
    load_session,
    save_session,
)


@pytest.fixture
def credentials():
    return Credentials(
        2**60 + 123, "unique-private-token", "unique-device-id", "26.8.2", profile="android"
    )


def test_roundtrip_and_no_plaintext_or_passphrase_on_disk(tmp_path, credentials):
    path = tmp_path / "session.json"
    password = "unique storage passphrase 한글"
    save_session(path, credentials, password)
    raw = path.read_bytes()
    for secret in (
        credentials.oauth_token,
        credentials.device_uuid,
        str(credentials.user_id),
        password,
    ):
        assert secret.encode() not in raw
    outer = json.loads(raw)
    assert set(outer) == {"version", "salt", "nonce", "ciphertext"}
    assert outer["version"] == 1
    assert len(base64.b64decode(outer["salt"])) == 16
    assert len(base64.b64decode(outer["nonce"])) == 12
    assert load_session(path, password) == credentials
    assert not list(tmp_path.glob(".kabot-session-*.tmp"))
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("profile", ["mac", "android"])
def test_profile_and_app_version_preserved(tmp_path, profile):
    creds = Credentials(
        42, "token", "uuid", "26.8.2" if profile == "android" else "26.9.1", profile=profile
    )
    path = tmp_path / "vault"
    save_session(path, creds, "p")
    loaded = load_session(path, "p")
    assert loaded == creds
    assert loaded.profile == profile
    assert loaded.device_uuid == "uuid"


def test_wrong_passphrase_and_tampered_ciphertext_redacted(tmp_path, credentials):
    path = tmp_path / "vault"
    save_session(path, credentials, "right password")
    with pytest.raises(SessionStoreError) as caught:
        load_session(path, "wrong private password")
    assert "wrong private password" not in str(caught.value)
    assert credentials.oauth_token not in str(caught.value)
    outer = json.loads(path.read_bytes())
    encrypted = bytearray(base64.b64decode(outer["ciphertext"]))
    encrypted[-1] ^= 1
    outer["ciphertext"] = base64.b64encode(encrypted).decode()
    path.write_text(json.dumps(outer))
    with pytest.raises(SessionStoreError, match="authentication"):
        load_session(path, "right password")


def test_refuses_existing_file_and_allows_explicit_atomic_overwrite(tmp_path, credentials):
    path = tmp_path / "vault"
    path.write_bytes(b"existing user content")
    with pytest.raises(SessionStoreError, match="already exists"):
        save_session(path, credentials, "password")
    assert path.read_bytes() == b"existing user content"
    save_session(path, credentials, "password", overwrite=True)
    assert load_session(path, "password") == credentials
    assert not list(tmp_path.glob(".kabot-session-*.tmp"))


def test_creation_race_does_not_clobber_winner(tmp_path, credentials, monkeypatch):
    path = tmp_path / "vault"
    original_link = os.link

    def competing_link(source, target):
        path.write_bytes(b"concurrent winner")
        original_link(source, target)

    monkeypatch.setattr("kabot.loco.storage.os.link", competing_link)
    with pytest.raises(SessionStoreError, match="already exists"):
        save_session(path, credentials, "password")
    assert path.read_bytes() == b"concurrent winner"
    assert not list(tmp_path.glob(".kabot-session-*.tmp"))


def test_missing_hardlink_support_fails_closed(tmp_path, credentials, monkeypatch):
    path = tmp_path / "vault"

    def unavailable(*args, **kwargs):
        raise OSError("unsupported")

    monkeypatch.setattr("kabot.loco.storage.os.link", unavailable)
    with pytest.raises(SessionStoreError, match="atomically"):
        save_session(path, credentials, "password")
    assert not path.exists()
    assert not list(tmp_path.glob(".kabot-session-*.tmp"))


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": 2},
        {"version": True},
        {"salt": "!invalid!"},
        {"salt": base64.b64encode(b"short").decode()},
        {"nonce": base64.b64encode(b"short").decode()},
        {"ciphertext": base64.b64encode(b"short").decode()},
        {"n": 2**30},
    ],
)
def test_corrupt_metadata_rejected_before_key_derivation(
    tmp_path, credentials, monkeypatch, mutation
):
    path = tmp_path / "vault"
    save_session(path, credentials, "password")
    outer = json.loads(path.read_bytes())
    outer.update(mutation)
    path.write_text(json.dumps(outer))

    def not_called(*args):
        raise AssertionError("Invalid metadata must not trigger KDF")

    monkeypatch.setattr("kabot.loco.storage._derive", not_called)
    with pytest.raises(SessionStoreError):
        load_session(path, "password")


@pytest.mark.parametrize(
    "raw", [b"", b"not-json", b"[]", b'{"version":1,"version":1}', b'{"version":NaN}']
)
def test_invalid_json_is_redacted(tmp_path, raw):
    path = tmp_path / "vault"
    path.write_bytes(raw)
    with pytest.raises(SessionStoreError):
        load_session(path, "password")


def test_file_and_plaintext_limits(tmp_path, credentials):
    path = tmp_path / "vault"
    path.write_bytes(b"x" * (MAX_SESSION_FILE_BYTES + 1))
    with pytest.raises(SessionStoreError, match="bounded"):
        load_session(path, "password")
    huge = Credentials(42, "x" * 40000, "uuid", "26.8.2", profile="android")
    with pytest.raises(SessionStoreError, match="size limit"):
        save_session(tmp_path / "huge", huge, "password")
    assert not (tmp_path / "huge").exists()


def test_random_salt_nonce_for_each_save(tmp_path, credentials):
    a, b = tmp_path / "a", tmp_path / "b"
    save_session(a, credentials, "same password")
    save_session(b, credentials, "same password")
    first, second = json.loads(a.read_bytes()), json.loads(b.read_bytes())
    assert first["salt"] != second["salt"]
    assert first["nonce"] != second["nonce"]
    assert first["ciphertext"] != second["ciphertext"]


def test_empty_passphrase_rejected(tmp_path, credentials):
    with pytest.raises(SessionStoreError, match="nonempty"):
        save_session(tmp_path / "vault", credentials, "")
    with pytest.raises(SessionStoreError, match="nonempty"):
        load_session(tmp_path / "vault", "")
