# LOCO TLS service identity findings

Investigation date: **2026-11-08**, Asia/Seoul. This investigation used public
source repositories and three public TLS handshakes. No account vault, account
status file, user identifier, token, password or chat data was accessed. No
application bytes were sent during those handshakes.

## Finding and scoped correction

LOCO's routing address can be an IP address while the certificate authenticates
the Kakao service name `kakao.com`. Validating that certificate against the IP
address causes a hostname verification failure even when the certificate chain
is otherwise trusted. This is supported by primary source implementations and
a matching public issue; it is not inferred solely from a wildcard certificate.

The correction separates the TCP destination from the TLS service identity.
For an Android chat endpoint assigned as an IP by verified Checkin, connect to
that IP and use `server_name="kakao.com"` for SNI and certificate verification.
The SSL context retains `CERT_REQUIRED`, `check_hostname=True` and its normal
public trust store. Generic endpoints continue to verify their own host name.
This does not accept arbitrary names, disable certificate validation, introduce
a new root CA, or pin the currently observed leaf certificate.

## Primary source evidence

- [openkakao-cli issue #61](https://github.com/JungHoonGhae/openkakao-cli/issues/61),
  opened 2026-10-03 by NetRiceCake, reports a successful Booking/Checkin followed
  by an assigned-IP chat TLS failure. The log identifies a certificate valid
  for `kakao.com` and `*.kakao.com`, with no IP SAN matching the routing address.
- [PR #60](https://github.com/JungHoonGhae/openkakao-cli/pull/60), merged
  2026-10-11, and the
  [1.9.0 changelog](https://github.com/JungHoonGhae/openkakao-cli/blob/6ca6ea2fd05a6660c4a80c0b61b43b416653d1d5/CHANGELOG.md)
  document the related IP-addressed TLS correction.
- The already-pinned
  [Rust verifier](https://github.com/JungHoonGhae/openkakao-cli/blob/6ca6ea2fd05a6660c4a80c0b61b43b416653d1d5/src/loco/client.rs#L306)
  retains a WebPKI verifier and public roots, but verifies service names rather
  than the routing IP. It checks `kakao.com` and a wildcard-matching surrogate
  `probe.kakao.com`. Kabot does not adopt this two-name fallback. The source's
  SNI still follows its original connection host, so this source alone does not
  establish the exact SNI name for an assigned server.
- Current openkakao-cli HEAD was checked without changing the pinned checkout:
  `36d8503a144706af4216f36a390d7781ae675e30`, dated
  2026-11-08T08:43:27+09:00. Its verifier retains the same behavior.
- Current agent-messenger HEAD was also inspected separately from the pinned
  checkout: `f4990c8d6172d0b8c4e1523262ee94349c120ff7`, dated
  2026-11-07T23:16:59+09:00. Its
  [TLS configuration](https://github.com/agent-messenger/agent-messenger/blob/f4990c8d6172d0b8c4e1523262ee94349c120ff7/src/platforms/kakaotalk/protocol/config.ts)
  explicitly sets `servername: 'kakao.com'` for Android tablet messaging, and
  [connection.ts](https://github.com/agent-messenger/agent-messenger/blob/f4990c8d6172d0b8c4e1523262ee94349c120ff7/src/platforms/kakaotalk/protocol/connection.ts)
  retains `rejectUnauthorized: true`. This supplies direct corroboration for
  the SNI and certificate identity choice.

The current agent-messenger implementation separately selects messaging TLS
port `10009` and contains runtime-specific cipher/extension settings. Those
are distinct protocol choices; they are not evidence that certificate checking
should be relaxed or that all Node-specific settings should be copied to
Python. They were not applied by this investigation.

The current loco-wrapper source remains commit
`1dec3b79e59f2776ebd1f03e60744162ff195b24`. Its Netty codec uses an insecure
trust manager and therefore does not establish a secure certificate identity
policy. Kabot does not adopt that trust manager.

## Actual public TLS observations

The following handshakes used Python `ssl.create_default_context()` without
modifying global trust configuration, `verify_mode=CERT_REQUIRED`,
`check_hostname=True`, TCP connect timeout five seconds, and no custom cipher
settings. `server_hostname` was explicitly set to the name shown below. The
handshake was closed without sending LOCO or HTTP data.

| TCP destination | TLS `server_hostname` | Result | Negotiated protocol |
| --- | --- | --- | --- |
| `booking-loco.kakao.com:443` | `booking-loco.kakao.com` | Verified successfully | TLS1.3 |
| `ticket-loco.kakao.com:9282` | `ticket-loco.kakao.com` | Verified successfully | TLS1.3 |
| `ticket-loco.kakao.com:9282` | `kakao.com` | Verified successfully | TLS1.3 |

All three returned the same verified leaf certificate:

```text
Subject organization: Kakao Corp.
Subject common name: kakao.com
Subject alternative names: DNS:kakao.com, DNS:*.kakao.com
Issuer: Thawte TLS RSA CA G1 (DigiCert Inc)
Not after: 2027-03-18 23:59:59 GMT
Leaf SHA-256: c84681d06f4fd41cf7d4ea55d1ec702fdf4f9754c304df70035532ad12a64b54
```

The observed peer IP was `211.183.211.14` for Booking and `211.183.211.10` for
Ticket. These are public service observations, not a user's assigned chat
endpoint. This demonstrates that normal public CA validation works for these
services and that Ticket accepts SNI `kakao.com`. It does not prove that a
particular account's assigned chat endpoint is reachable, accepts a session,
or has an identical certificate. The fingerprint is an observation, not a
newly installed trust anchor or a required permanent pin.

## Local integration checks

`tests/test_loco_tls.py` generates an ephemeral CA and DNS-only `localhost`
server certificate. An actual asyncio TLS server accepts a raw 22-byte LOCO
header plus BSON request and returns its acknowledgement in fragmented TLS
writes. The tests prove that:

1. Hostname connection with the matching identity succeeds with CA and name
   verification enabled.
2. IP connection with explicit `server_name="localhost"` succeeds under the
   same strict context and correctly exchanges the request/acknowledgement.
3. IP connection without an explicit DNS identity fails certificate name
   checking before application packets are accepted.
4. Explicit `server_name="wrong.invalid"` also fails before application packets.

`tests/test_loco_profiles.py` checks that Android discovery applies the fixed
Kakao service identity to Checkin-assigned IPv4 and IPv6 addresses while
preserving the generic DNS endpoint behavior. The targeted local suite passed
**8 tests**. These tests use generated certificates and dummy packet data; they
do not establish live account authentication or message delivery.
