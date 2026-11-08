# Current authentication findings — 2026-11-08

This pass inspected public source only. No local account/session/status files,
credentials, authentication HTTP requests or token refresh operations were used.

## What status 12 means

The strongest source-supported interpretation is **the server reported a
password mismatch**. It does not prove that the human typed incorrectly or
exclude every undocumented server policy/compatibility condition.

- [node-kakao's authentication enum](https://github.com/storycraft/node-kakao/blob/8512e4699e2cd4c26516b80d38b57b2f85a6cc8a/src/api/auth-api-client.ts)
  names `12` as `MISMATCH_PASSWORD`, separately from `13` login limit, `30`
  generic login failure, `-100` unregistered device, `-101` another login and
  `-999` upgrade required. This is a historical reverse-engineered enum, not
  an official server specification.
- Current [loco-wrapper KakaoApi.java](https://github.com/NetRiceCake/loco-wrapper/blob/1dec3b79e59f2776ebd1f03e60744162ff195b24/src/main/java/com/github/netricecake/kakao/KakaoApi.java)
  describes `12` as an incorrect password and `30` as an incorrect email; both
  raise `BadCredentialsException`.
- Current [agent-messenger kakao-login.ts](https://github.com/agent-messenger/agent-messenger/blob/f4990c8d6172d0b8c4e1523262ee94349c120ff7/src/platforms/kakaotalk/auth/kakao-login.ts)
  groups `12` and `30` as bad credentials. It does not identify `12` as an
  X-VC, device model or app-version error.

No inspected source or test demonstrates that an incorrect X-VC specifically
produces status12. Therefore changing the signature seed, client version or
device UUID in response to this code would be an unverified guess. A user-led
single re-entry of the account email/password with the existing consistent
profile and UUID is compatible with this evidence; it does not justify an
automatic retry. Repeating status12 should remain a reported rejection, not a
claim that the password was conclusively diagnosed by the library.

## Current profile evidence

Remote HEAD values were checked on 2026-11-08 without switching any pinned
checkout:

| Repository | Current HEAD | Relevant authentication facts |
| --- | --- | --- |
| loco-wrapper | `1dec3b79e59f2776ebd1f03e60744162ff195b24` (2026-10-03) | Still Android26.8.2, Android13/API33. Form password is passed directly over HTTPS. X-VC uses `ALBUS / IAN / SEOGI` with the matching User-Agent and email. No newer profile change was found. |
| agent-messenger | `f4990c8d6172d0b8c4e1523262ee94349c120ff7` (2026-11-07) | Still Android25.9.2 and its `BARD / DANTE / SIAN` seed. Its recent repository date does not make these constants Android26.8.2 evidence. |
| KakaoForge | `4b774ea40b1347280fadb685415436584093118b` (2026-02-09) | Older Android26.1.2 reference. Not evidence for silently changing this client's profile. |

The current agent-messenger authentication test uses a mocked fetch response
with a fixture token. Its refresh tests also use mocked fetch. These prove
request construction/error handling in that implementation, not current live
acceptance of this project's26.8.2 authentication profile.

## Candidate refresh flow

Primary references are current agent-messenger
[oauth-refresh.ts](https://github.com/agent-messenger/agent-messenger/blob/f4990c8d6172d0b8c4e1523262ee94349c120ff7/src/platforms/kakaotalk/auth/oauth-refresh.ts)
and [its tests](https://github.com/agent-messenger/agent-messenger/blob/f4990c8d6172d0b8c4e1523262ee94349c120ff7/src/platforms/kakaotalk/auth/oauth-refresh.test.ts),
corroborated by the older
[KakaoForge refresh implementation](https://github.com/play2fly/KakaoForge/blob/4b774ea40b1347280fadb685415436584093118b/src/auth/login.ts).

```text
POST https://katalk.kakao.com/android/account/oauth2_token.json
Content-Type: application/json; charset=utf-8
Authorization: {existing_access_token}-{device_id}
A: android/{source_profile_version}/ko
User-Agent: KT/{source_profile_version} An/13 ko
Accept-Language: ko
C: fresh request UUID
Connection: Close

{
  "access_token": existing_access_token,
  "refresh_token": existing_refresh_token,
  "grant_type": "refresh_token"
}
```

In agent-messenger, an existing40–64hex-character device ID is reused unchanged;
other strings use SHA256 of `"dkljleskljfeisflssljeif " + device_uuid`. A new access
token is required in the successful response. If a new refresh token is omitted,
the previous one is retained. `token_type` and `expires_in` are optional result
metadata. It makes one request and surfaces HTTP/server/transport failures.

This is the private Android Talk endpoint, distinct from the official
Kakao Developers app OAuth endpoint. The inspected current refresh code uses
Android25.9.2 headers. A26.8.2 variant is a candidate requiring its own explicit
validation, not an already verified recovery route.

## Practical persistence proposal

The current encrypted session schema only retains the personal client's access
credential. A refresh flow needs the refresh token returned by a successful
login as well as the same device UUID/profile. That missing token cannot be
reconstructed from the old access token or the vault's public metadata.

For a later implementation, extend the encrypted payload with an explicit
versioned session record containing access token, refresh token, user ID,
device UUID, profile, app version and any supplied expiry metadata. Keep the
refresh token out of repr/logs. Read old access-only vaults as such; do not
invent a refresh credential. After an explicit successful refresh, atomically
replace the encrypted token pair before opening a new LOCO session. Preserve
the previous refresh token only when the response omits a replacement. Do not
retry an ambiguous refresh timeout because the server may already have rotated
the token.

No code or account state was changed by this investigation.
