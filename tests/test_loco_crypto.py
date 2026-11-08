import struct

import pytest

pytest.importorskip("cryptography", reason="optional LOCO extra is not installed")
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from kabot.loco.crypto import REFERENCE_RSA_PUBLIC_KEY_DER, CryptoError, LocoEncryptor


def test_gcm_matches_nist_zero_key_nonce_plaintext_vector(monkeypatch):
    codec = LocoEncryptor(key=b"\0" * 16)
    monkeypatch.setattr("kabot.loco.crypto.secrets.token_bytes", lambda count: b"\0" * count)
    ciphertext = bytes.fromhex("0388dace60b6a392f328c2b971b2fe78")
    tag = bytes.fromhex("ab6e47d42cec13bdf53a67b21257bddf")
    expected = struct.pack("<I", 44) + b"\0" * 12 + ciphertext + tag
    assert codec.encrypt(b"\0" * 16) == expected
    assert codec.decrypt_frame(expected) == b"\0" * 16
    assert codec.decrypt(expected[4:]) == b"\0" * 16


def test_handshake_is_oaep_sha1_with_explicit_operator_public_key():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.PKCS1
    )
    aes_key = b"0123456789abcdef"
    codec = LocoEncryptor(key=aes_key, public_key_der=public)
    handshake = codec.build_handshake_packet()
    assert len(handshake) == 268
    assert struct.unpack("<III", handshake[:12]) == (256, 16, 3)
    recovered = private.decrypt(
        handshake[12:],
        padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
    )
    assert recovered == aes_key


def test_reference_key_identity_and_handshake_header():
    public = serialization.load_der_public_key(REFERENCE_RSA_PUBLIC_KEY_DER)
    assert isinstance(public, rsa.RSAPublicKey)
    assert public.key_size == 2048
    assert public.public_numbers().e == 3
    handshake = LocoEncryptor().build_handshake_packet()
    assert len(handshake) == 268
    assert handshake[:12] == struct.pack("<III", 256, 16, 3)


def test_random_keys_and_nonces_make_distinct_records():
    a = LocoEncryptor()
    b = LocoEncryptor()
    first, second = a.encrypt(b"same"), a.encrypt(b"same")
    assert first != second
    assert a.decrypt_frame(first) == a.decrypt_frame(second) == b"same"
    with pytest.raises(CryptoError, match="authentication"):
        b.decrypt_frame(first)


@pytest.mark.parametrize("index", [4, 16, -1])
def test_nonce_ciphertext_and_tag_tampering_rejects_without_plaintext(index):
    codec = LocoEncryptor()
    frame = bytearray(codec.encrypt(b"sensitive payload"))
    frame[index] ^= 1
    with pytest.raises(CryptoError, match="authentication"):
        codec.decrypt_frame(frame)


def test_length_bounds_validated_before_decryption():
    codec = LocoEncryptor(max_plaintext_size=4)
    frame = codec.encrypt(b"1234")
    assert codec.frame_body_size(frame[:4]) == 32
    assert codec.decrypt_frame(frame) == b"1234"
    for size in (0, 27, 33, 0xFFFFFFFF):
        with pytest.raises(CryptoError):
            codec.frame_body_size(struct.pack("<I", size))
    for invalid in (frame[:3], frame[:-1], frame + b"extra"):
        with pytest.raises(CryptoError):
            codec.decrypt_frame(invalid)
    with pytest.raises(CryptoError, match="limit"):
        codec.encrypt(b"12345")
    with pytest.raises(CryptoError, match="bounds"):
        codec.decrypt(b"x" * 33)


def test_empty_plaintext_and_record_limit():
    codec = LocoEncryptor(max_plaintext_size=0)
    frame = codec.encrypt(b"")
    assert len(frame) == 32
    assert codec.decrypt_frame(frame) == b""
    codec._encrypt_count = 2**32
    with pytest.raises(CryptoError, match="record limit"):
        codec.encrypt(b"")


def test_invalid_key_inputs_rejected():
    with pytest.raises(CryptoError):
        LocoEncryptor(key=b"short")
    with pytest.raises(CryptoError):
        LocoEncryptor(public_key_der=b"not a key")
    small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    public = small.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.PKCS1
    )
    with pytest.raises(CryptoError, match="2048"):
        LocoEncryptor(public_key_der=public)
