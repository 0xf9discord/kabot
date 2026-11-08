"""Real loopback TLS tests; no Kakao server, account or session file is touched."""

import asyncio
import ssl
import struct
from datetime import UTC, datetime, timedelta

import pytest
from bson import BSON
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from kabot.loco.session import LocoSession
from kabot.loco.transport import Endpoint, LocoTransport


@pytest.fixture
def tls_contexts(tmp_path):
    """Fresh CA and DNS-only localhost certificate, never trusted system-wide."""
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "kabot ephemeral test CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (
        tmp_path / "ephemeral-ca.pem",
        tmp_path / "localhost.pem",
        tmp_path / "localhost-key.pem",
    )
    ca_path.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(server_certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    client_context = ssl.create_default_context(cafile=str(ca_path))
    assert client_context.verify_mode == ssl.CERT_REQUIRED
    assert client_context.check_hostname is True
    return server_context, client_context


async def _close_writer(writer):
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 2)
    except (OSError, TimeoutError):
        pass


async def _stop_server(server, tasks):
    server.close()
    await asyncio.wait_for(server.wait_closed(), 2)
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 3)


@pytest.mark.parametrize(
    "connect_host,server_name", [("localhost", None), ("127.0.0.1", "localhost")]
)
def test_real_tls_raw_loco_request_and_fragmented_ack(
    tls_contexts, monkeypatch, connect_host, server_name
):
    server_context, client_context = tls_contexts
    monkeypatch.setattr("kabot.loco.transport.ssl.create_default_context", lambda: client_context)

    async def scenario():
        tasks, errors, observations = [], [], []
        finished = asyncio.Event()

        async def handle(reader, writer):
            try:
                tls = writer.get_extra_info("ssl_object")
                assert tls is not None and tls.version().startswith("TLS")
                # Parse independently of the production packet codec. The first
                # bytes after TLS must be the raw LOCO header, not a V2SL prefix.
                header = await asyncio.wait_for(reader.readexactly(22), 3)
                packet_id, status, method, body_type, size = struct.unpack("<Ih11sBI", header)
                assert status == 0 and method.rstrip(b"\0") == b"PING" and body_type == 0
                assert 5 <= size <= 1024
                body = BSON(await asyncio.wait_for(reader.readexactly(size), 3)).decode()
                assert body == {"probe": "loopback-only"}
                observations.append(tls.version())
                response_body = BSON.encode({"status": 0, "ack": "tls-ok"})
                wire = struct.pack("<Ih11sBI", packet_id, 0, b"PING", 0, len(response_body))
                wire += response_body
                for part in (wire[:3], wire[3:19], wire[19:24], wire[24:]):
                    writer.write(part)
                    await writer.drain()
                    await asyncio.sleep(0)
                # Keep the stream alive until the client closes normally.
                assert await asyncio.wait_for(reader.read(), 3) == b""
            except Exception as error:
                errors.append(error)
            finally:
                await _close_writer(writer)
                finished.set()

        def accepted(reader, writer):
            tasks.append(asyncio.create_task(handle(reader, writer)))

        server = await asyncio.start_server(
            accepted, "127.0.0.1", 0, ssl=server_context, ssl_handshake_timeout=3
        )
        session = None
        try:
            port = server.sockets[0].getsockname()[1]
            transport = await LocoTransport.connect(
                Endpoint(connect_host, port, tls=True, server_name=server_name),
                timeout=3,
                idle_timeout=3,
            )
            assert transport.encryptor is None
            assert transport.writer.get_extra_info("ssl_object").version().startswith("TLS")
            session = LocoSession(transport, command_timeout=3)
            response = await session.request("PING", {"probe": "loopback-only"})
            assert response.body["ack"] == "tls-ok"
            await session.close()
            await asyncio.wait_for(finished.wait(), 3)
            assert observations and not errors
        finally:
            if session is not None:
                await session.close()
            await _stop_server(server, tasks)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "server_name,expected_error",
    [(None, "IP address mismatch"), ("wrong.invalid", "Hostname mismatch")],
)
def test_real_tls_rejects_ip_hostname_before_application_packets(
    tls_contexts, monkeypatch, server_name, expected_error
):
    server_context, client_context = tls_contexts
    monkeypatch.setattr("kabot.loco.transport.ssl.create_default_context", lambda: client_context)

    async def scenario():
        tasks, accepted_connections = [], []

        async def unexpected_connection(reader, writer):
            accepted_connections.append(True)
            await _close_writer(writer)

        def accepted(reader, writer):
            tasks.append(asyncio.create_task(unexpected_connection(reader, writer)))

        server = await asyncio.start_server(
            accepted, "127.0.0.1", 0, ssl=server_context, ssl_handshake_timeout=3
        )
        try:
            port = server.sockets[0].getsockname()[1]
            # The certificate is CA-trusted, but SAN contains DNS localhost only.
            with pytest.raises(ssl.SSLCertVerificationError) as caught:
                await LocoTransport.connect(
                    Endpoint("127.0.0.1", port, tls=True, server_name=server_name), timeout=3
                )
            assert expected_error in caught.value.verify_message
            await asyncio.sleep(0)
            assert not accepted_connections
            assert client_context.verify_mode == ssl.CERT_REQUIRED
            assert client_context.check_hostname is True
        finally:
            await _stop_server(server, tasks)

    asyncio.run(scenario())
