"""Experimental LOCO RSA-OAEP-SHA1 / AES-128-GCM reference wire format.

The SHA-1 OAEP algorithm and handshake identifiers follow the pinned upstream
protocol, not a fallback. No TLS verification bypass is implemented here.
See docs/THIRD_PARTY_NOTICES.md for attribution and reference limitations.
"""

from __future__ import annotations

import base64
import secrets
import struct

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as error:
    raise ImportError(
        'LOCO requires optional dependencies: pip install "kabot-python[loco]"'
    ) from error

MAX_PLAINTEXT_SIZE = 16 * 1024 * 1024
GCM_NONCE_SIZE = 12
GCM_TAG_SIZE = 16

# Historical key from upstream crypto.rs; not independently authenticated as a
# current Kakao server key. Operators can explicitly supply their verified key.
REFERENCE_RSA_PUBLIC_KEY_DER = base64.b64decode(
    "MIIBCAKCAQEAo7B26MRFhR8ZpnDCMarG20Lv0JcX0GBIpcxWkGzRqye53zf/1QF+"
    "fBOhQFtdHD5IeaakmdPGGKckcrC1DKXvHvbupwNp2UE/5mLY4rR5qfchQu5wzubCr"
    "RIEXVKyXEogSiiWjjfwumpJ7j7J8qx6ZRhBYPIvYsQ6QGfNjSpvE9m4KYqwAnY9I"
    "2ydGHnX/OW4+pEIgrIeFSR+DQokeRMI5RmDYUQC6foDBXxX6eF4scw5/mcojvxGG"
    "UXLyqEdH8wSPnULhh8NRH6+PBFfQRpC3JXdsh2kJ3SlvLHd9/pfEGKAEMdPNvMcQ"
    "O/P4on9gbq6RKZVamwwEhBBS2Ajw/RjcQIBAw=="
)


class CryptoError(ValueError):
    """Invalid frame, key, or failed GCM authentication; no plaintext returned."""


class LocoEncryptor:
    """One connection's random AES key and authenticated GCM record codec.

    encrypt() produces the four-byte length prefix. decrypt() accepts only the
    body after that prefix, matching the upstream interface. decrypt_frame()
    validates and consumes a complete record including the prefix.
    """

    def __init__(
        self,
        key: bytes | None = None,
        *,
        public_key_der: bytes | None = None,
        max_plaintext_size: int = MAX_PLAINTEXT_SIZE,
    ):
        if type(max_plaintext_size) is not int or not 0 <= max_plaintext_size <= 100 * 1024 * 1024:
            raise ValueError("max_plaintext_size must be between 0 and 100 MiB")
        if key is not None and (not isinstance(key, bytes) or len(key) != 16):
            raise CryptoError("AES-128 key must be exactly 16 bytes")
        self._key = secrets.token_bytes(16) if key is None else key
        self._cipher = AESGCM(self._key)
        self._max_plaintext_size = max_plaintext_size
        self._encrypt_count = 0
        encoded = REFERENCE_RSA_PUBLIC_KEY_DER if public_key_der is None else public_key_der
        try:
            public_key = serialization.load_der_public_key(encoded)
        except (ValueError, TypeError):
            raise CryptoError("invalid DER public key") from None
        if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size != 2048:
            raise CryptoError("LOCO reference handshake requires a 2048-bit RSA public key")
        self._public_key = public_key

    def build_handshake_packet(self) -> bytes:
        """268 bytes: u32 LE key-size=256, key-type=16, cipher-type=3, RSA blob."""
        encrypted = self._public_key.encrypt(
            self._key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None
            ),
        )
        return struct.pack("<III", len(encrypted), 16, 3) + encrypted

    def frame_body_size(self, prefix: bytes | bytearray | memoryview) -> int:
        """Validate a four-byte size prefix before allocating/reading its body."""
        if len(prefix) != 4:
            raise CryptoError("encrypted frame prefix must be exactly 4 bytes")
        size = struct.unpack("<I", prefix)[0]
        if (
            not GCM_NONCE_SIZE + GCM_TAG_SIZE
            <= size
            <= self._max_plaintext_size + GCM_NONCE_SIZE + GCM_TAG_SIZE
        ):
            raise CryptoError("encrypted frame length is outside configured bounds")
        return size

    def encrypt(self, plaintext: bytes) -> bytes:
        if not isinstance(plaintext, bytes):
            raise TypeError("plaintext must be bytes")
        if len(plaintext) > self._max_plaintext_size:
            raise CryptoError("plaintext exceeds configured frame limit")
        if self._encrypt_count >= 2**32:
            raise CryptoError("GCM per-key record limit reached; reconnect with a new key")
        nonce = secrets.token_bytes(GCM_NONCE_SIZE)
        ciphertext_and_tag = self._cipher.encrypt(nonce, plaintext, None)
        self._encrypt_count += 1
        body = nonce + ciphertext_and_tag
        return struct.pack("<I", len(body)) + body

    def decrypt(self, data: bytes | bytearray | memoryview) -> bytes:
        if (
            not GCM_NONCE_SIZE + GCM_TAG_SIZE
            <= len(data)
            <= self._max_plaintext_size + GCM_NONCE_SIZE + GCM_TAG_SIZE
        ):
            raise CryptoError("encrypted frame body is outside configured bounds")
        nonce = bytes(data[:GCM_NONCE_SIZE])
        ciphertext_and_tag = bytes(data[GCM_NONCE_SIZE:])
        try:
            return self._cipher.decrypt(nonce, ciphertext_and_tag, None)
        except InvalidTag:
            raise CryptoError("AES-GCM authentication failed") from None

    def decrypt_frame(self, frame: bytes | bytearray | memoryview) -> bytes:
        if len(frame) < 4:
            raise CryptoError("truncated encrypted frame prefix")
        expected = self.frame_body_size(frame[:4])
        if len(frame) != expected + 4:
            raise CryptoError("encrypted frame length does not match prefix")
        return self.decrypt(frame[4:])
