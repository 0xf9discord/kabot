"""Portable encrypted session files; no password, email or passphrase is stored.

The format fixes scrypt and AES-GCM parameters rather than trusting file-provided
KDF settings. POSIX files use mode 0600. On Windows, Python's chmod does not set
an owner-only ACL; choose a user-private directory with suitable inherited ACLs.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .client import Credentials

MAX_SESSION_FILE_BYTES = 64 * 1024
_MAX_PLAINTEXT_BYTES = 32 * 1024
_AAD = b"kabot-python:encrypted-session:v1:scrypt32768-r8-p1:aes256gcm"
_OUTER_KEYS = {"version", "salt", "nonce", "ciphertext"}
_INNER_KEYS = {"user_id", "oauth_token", "device_uuid", "app_version", "profile"}


class SessionStoreError(ValueError):
    """Redacted session file failure; never includes ciphertext or secret values."""


def _passphrase(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise SessionStoreError("A nonempty session passphrase is required")
    try:
        return value.encode("utf-8")
    except UnicodeError:
        raise SessionStoreError("Session passphrase must contain valid Unicode") from None


def _derive(passphrase: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(passphrase)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SessionStoreError("Session file contains duplicate metadata")
        result[key] = value
    return result


def _invalid_constant(value):
    raise SessionStoreError("Session file contains invalid JSON metadata")


def _parse(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw, object_pairs_hook=_json_object, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise SessionStoreError("Session file format is invalid") from None
    if not isinstance(value, dict):
        raise SessionStoreError("Session file format is invalid")
    return value


def _decode64(value: Any, *, expected: int | None = None) -> bytes:
    if not isinstance(value, str):
        raise SessionStoreError("Session file encoding is invalid")
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError, binascii.Error):
        raise SessionStoreError("Session file encoding is invalid") from None
    # Require canonical base64, rejecting unnecessary padding and alternate forms.
    if base64.b64encode(decoded) != encoded or (expected is not None and len(decoded) != expected):
        raise SessionStoreError("Session file encoding is invalid")
    return decoded


def _validate_inner(value: dict[str, Any]) -> None:
    if set(value) != _INNER_KEYS:
        raise SessionStoreError("Encrypted session schema is invalid")
    user_id = value["user_id"]
    if type(user_id) is not int or not 0 < user_id < 2**63:
        raise SessionStoreError("Encrypted session identity is invalid")
    if not isinstance(value["profile"], str) or value["profile"] not in {"mac", "android"}:
        raise SessionStoreError("Encrypted session profile is invalid")
    for name in ("oauth_token", "device_uuid", "app_version"):
        item = value[name]
        if not isinstance(item, str) or not item.strip():
            raise SessionStoreError("Encrypted session fields are invalid")


def _read_bounded(path: Path) -> bytes:
    # Compare opened identity against lstat to reject symlinks and replacement
    # races, also on Windows where O_NOFOLLOW may not be available.
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SESSION_FILE_BYTES:
            raise SessionStoreError("Session path must be a bounded regular file")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_size > MAX_SESSION_FILE_BYTES
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise SessionStoreError("Session file changed while opening")
            result = stream.read(MAX_SESSION_FILE_BYTES + 1)
        if len(result) > MAX_SESSION_FILE_BYTES:
            raise SessionStoreError("Session file exceeds the size limit")
        return result
    except OSError:
        raise SessionStoreError("Unable to read session file") from None


def save_session(
    path: str | os.PathLike[str],
    credentials: Credentials,
    passphrase: str,
    *,
    overwrite: bool = False,
) -> None:
    """Encrypt and atomically publish a session. Existing files are protected by default.

    The destination directory must already exist. Without overwrite, an atomic
    hard-link publication prevents races with another creator. Filesystems that
    cannot provide this guarantee fail rather than falling back to clobbering.
    """
    password_bytes = _passphrase(passphrase)
    if not isinstance(credentials, Credentials):
        raise SessionStoreError("credentials must be a Credentials instance")
    if type(overwrite) is not bool:
        raise SessionStoreError("overwrite must be bool")
    target = Path(path)
    inner = {
        "user_id": int(credentials.user_id),
        "oauth_token": credentials.oauth_token,
        "device_uuid": credentials.device_uuid,
        "app_version": credentials.app_version,
        "profile": getattr(credentials, "profile", "mac"),
    }
    _validate_inner(inner)
    plaintext = json.dumps(inner, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(plaintext) > _MAX_PLAINTEXT_BYTES:
        raise SessionStoreError("Session contents exceed the size limit")
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    encrypted = AESGCM(_derive(password_bytes, salt)).encrypt(nonce, plaintext, _AAD)
    outer = {
        "version": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(encrypted).decode("ascii"),
    }
    serialized = json.dumps(outer, separators=(",", ":")).encode("ascii")
    if len(serialized) > MAX_SESSION_FILE_BYTES:
        raise SessionStoreError("Session file exceeds the size limit")
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=".kabot-session-", suffix=".tmp", dir=target.parent
        )
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1  # owned by stream from this point
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor != -1:
                os.close(descriptor)
        if overwrite:
            os.replace(temporary, target)
            temporary = None
        else:
            os.link(temporary, target)  # atomic no-clobber publication
    except FileExistsError:
        raise SessionStoreError(
            "Session file already exists; explicit overwrite is required"
        ) from None
    except OSError:
        raise SessionStoreError("Unable to atomically save session file") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def load_session(path: str | os.PathLike[str], passphrase: str) -> Credentials:
    """Authenticate and decrypt a bounded encrypted file using fixed KDF settings."""
    password_bytes = _passphrase(passphrase)
    outer = _parse(_read_bounded(Path(path)))
    if set(outer) != _OUTER_KEYS or type(outer.get("version")) is not int or outer["version"] != 1:
        raise SessionStoreError("Unsupported encrypted session format")
    salt = _decode64(outer["salt"], expected=16)
    nonce = _decode64(outer["nonce"], expected=12)
    ciphertext = _decode64(outer["ciphertext"])
    if not 16 <= len(ciphertext) <= _MAX_PLAINTEXT_BYTES + 16:
        raise SessionStoreError("Encrypted session size is invalid")
    try:
        plaintext = AESGCM(_derive(password_bytes, salt)).decrypt(nonce, ciphertext, _AAD)
    except InvalidTag:
        raise SessionStoreError(
            "Session passphrase is incorrect or file authentication failed"
        ) from None
    inner = _parse(plaintext)
    _validate_inner(inner)
    try:
        return Credentials(
            inner["user_id"],
            inner["oauth_token"],
            inner["device_uuid"],
            inner["app_version"],
            profile=inner["profile"],
        )
    except (TypeError, ValueError):
        raise SessionStoreError("Encrypted session credentials are invalid") from None
