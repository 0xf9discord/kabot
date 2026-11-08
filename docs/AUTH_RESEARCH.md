# 독립 실행 개인 계정 인증 조사와 구현

소스 조사일: 2026-10-31. 실제 접속 확인일: **2026-11-08**. 봇 호스트에 카카오톡을 설치하지 않는 Android 서브 디바이스 인증을 구현했습니다. 사용자 직접 입력으로 계정 인증, 암호화 세션 저장, 채팅 서버 `LOGINLIST` 성공을 확인했습니다. 비밀번호·토큰은 채팅이나 진행 기록에 출력하지 않았으며 검증 상태에는 성공 여부와 채팅방 항목 수만 남겼습니다. 이 확인을 다른 버전·모든 계정의 성공 보장으로 확대하지 않습니다.

## 근거와 버전

| 출처 | 고정 커밋 / 마지막 소스 시각 | 관찰 내용 | 증거의 범위 |
| --- | --- | --- | --- |
| [loco-wrapper](https://github.com/NetRiceCake/loco-wrapper/tree/1dec3b79e59f2776ebd1f03e60744162ff195b24) | `1dec3b79e59f2776ebd1f03e60744162ff195b24`, 2026-10-03 | Android **26.8.2**, 변경된 X-VC 시드, 비밀번호/기기 등록 API, 채팅·체크인 TLS | 현재 구현의 주된 동작 근거. README의 정상 동작 설명은 저자 보고이며 이 작업의 실서버 검증이 아님 |
| [agent-messenger](https://github.com/agent-messenger/agent-messenger/tree/e58739d80305d5e8ddf72e9aad085c2069f4fd3c) | `e58739d80305d5e8ddf72e9aad085c2069f4fd3c`, 2026-10-29 | Android25.9.2 로그인/등록 및 OAuth 갱신 구현 | 저장소가 더 최근이어도 해당 인증 상수는 예전 버전. 26.8.2와 혼합하지 않음 |
| [node-kakao](https://github.com/storycraft/node-kakao/tree/8512e4699e2cd4c26516b80d38b57b2f85a6cc8a) | `8512e4699e2cd4c26516b80d38b57b2f85a6cc8a`, 2023-11-01 | 과거 Win32/Android X-VC 및 `request_passcode.json` 계열 API | 역사적 비교 자료. 현재 등록 API로 그대로 사용하지 않음 |
| [openkakao-cli](https://github.com/JungHoonGhae/openkakao-cli/tree/6ca6ea2fd05a6660c4a80c0b61b43b416653d1d5) | `6ca6ea2fd05a6660c4a80c0b61b43b416653d1d5` | macOS 서버 로그인 문제, Android26.7.1 정적 조사 | macOS 실패를 Android의 불가능 증거로 취급하지 않음. 정적 조사를 라이브 인증 증거로 취급하지 않음 |
| [KakaoForge](https://github.com/play2fly/KakaoForge/tree/4b774ea40b1347280fadb685415436584093118b) | `4b774ea40b1347280fadb685415436584093118b`, 2026-02-09 | Android26.1.2 QR 로그인 후보와 갱신 동작 | QR 대안 조사만 수행. 현 버전 검증이 없으므로 구현·실행하지 않음 |

주요 원본은 [KakaoApi.java](https://github.com/NetRiceCake/loco-wrapper/blob/1dec3b79e59f2776ebd1f03e60744162ff195b24/src/main/java/com/github/netricecake/kakao/KakaoApi.java)입니다. 최신 Java 저장소에는 MIT LICENSE가 추가되어 있습니다. agent-messenger의 이전 NOTICE에 있는 “라이선스 없음”은 최신 상태와 다릅니다.

서로 다른 버전은 X-VC 입력부터 다릅니다. node-kakao의 과거 Android 시드는 `KOLD/BRAN/BRAD`, agent-messenger25.9.2는 `BARD/DANTE/SIAN`, 현재 loco-wrapper26.8.2는 `ALBUS/IAN/SEOGI`입니다. 소스 날짜만 보고 모든 저장소의 구현을 합치면 잘못된 로그인 요청이 됩니다.

## 구현한 26.8.2 요청

기본 프로필은 `ANDROID_26_8_2`이며 Android13/API33, `device_name=SM-T870`, 언어 `ko`입니다. 기기 이름은 `AndroidAuthProfile(device_name=...)`으로 선택할 수 있습니다. 임의의 최신 버전 문자열을 넣으면 기존 서명을 재사용하지 않고 오류를 냅니다.

공통 헤더:

```text
A: android/26.8.2/ko
User-Agent: KT/26.8.2 An/13 ko
Accept-Language: ko
X-VC: SHA512_UTF8("ALBUS|{User-Agent}|IAN|{email}|SEOGI").hex()[:16]
```

X-VC는 이 소스에서 이메일과 공개된 클라이언트 프로필로 계산됩니다. 별도의 기기 하드웨어 비밀키나 설치 앱에서 추출한 토큰을 입력으로 요구하지 않습니다. 이는 **해당 공개 구현에 대한 관찰**이며, 현재 서버가 추가 검증을 요구하지 않는다는 라이브 증거는 아닙니다.

| 작업 | HTTP 경로 (`https://katalk.kakao.com` 기준) | 본문·결과 |
| --- | --- | --- |
| 모델 확인 | `GET /android/account/allowlist.json?model_name=SM-T870` | 계정 정보 없이 `allowlisted` 확인 |
| 로그인 | `POST /android/account/login.json` | form: `email`, `password`, `device_name`, `device_uuid`, `forced=false`, `permanent=true` |
| 번호 생성 | `POST /android/account/passcodeLogin/generate` | JSON: `email`, `password`, `permanent:true`, `device:{name,uuid,model,osVersion:"33"}`. `passcode`와 `remainingSeconds` 반환 |
| 등록 확인 | `POST /android/account/passcodeLogin/registerDevice` | JSON: `email`, `password`, `device:{uuid}`. 번호는 휴대폰에서 입력하므로 이 요청에 `passcode`를 넣지 않음 |

로그인 `status=0`과 유효한 `access_token`·정수 `userId`가 있어야 `AndroidTokens`를 반환합니다. `status=-100`은 `RegistrationRequired`를 반환합니다. 나머지 상태는 숫자를 보존한 `AndroidAuthError`로 중단합니다. 예컨대 `12`/`30`을 잘못된 자격 정보, `-999`를 버전 거절로 해석할 수 있으나 서버 메시지 원문은 예외에 붙이지 않습니다. 상태를 추측해서 강제 로그인하거나 재시도하지 않습니다.

등록 확인은 `status=0`이면 등록 완료, `-100`이면 대기입니다. 대기 응답의 `remainingSeconds`, `nextRequestIntervalInSeconds`를 호출자가 확인해야 합니다. 라이브러리는 한 번만 요청하고 자동으로 폴링하지 않습니다. `force=True`는 호출자가 명시할 때만 보내며 기본값은 `false`입니다.

## 사용 예제

```python
from kabot.loco.auth import (
    AndroidAuthClient, AndroidTokens, RegistrationRequired, generate_device_uuid,
)

async def authenticate(email, password, device_uuid):
    async with AndroidAuthClient() as auth:
        if not await auth.check_model():
            raise RuntimeError("서브 디바이스 모델이 허용되지 않았습니다.")

        result = await auth.login(email, password, device_uuid)
        if isinstance(result, RegistrationRequired):
            # 이 단계는 실제 계정에 기기 등록 알림을 만듭니다.
            challenge = await auth.request_registration(email, password, device_uuid)
            print("휴대폰 카카오톡의 인증 화면에 입력:", challenge.passcode)
            print("남은 시간:", challenge.remaining_seconds)

            # 사용자가 휴대폰에서 확인한 뒤 명시적으로 한 번 검사.
            state = await auth.poll_registration_once(email, password, device_uuid)
            if not state.registered:
                # 다음 검사까지 최소 state.next_request_interval_seconds 대기.
                # 유효시간 만료 시 중단. 이 예제는 자동 반복하지 않음.
                return state
            result = await auth.login(email, password, device_uuid)

        if not isinstance(result, AndroidTokens):
            raise RuntimeError("기기 등록 이후에도 로그인이 완료되지 않았습니다.")
        return result

# device_uuid = generate_device_uuid() 는 첫 설치에서 한 번 생성합니다.
# 다음 실행에서도 같은 UUID를 사용하며 토큰과 함께 안전하게 관리합니다.
# 실제 email/password는 환경에 맞는 대화형 입력을 사용하고 로그에 출력하지 않습니다.
```

`AndroidTokens.to_credentials()`는 `Credentials(user_id, access_token, device_uuid, "26.8.2", profile="android")`를 만듭니다. `access_token`이 LOCO `LOGINLIST.oauthToken`입니다. Kakao Developers의 공식 OAuth 앱 토큰, macOS REST 캐시의 Authorization 문자열, 채널 사용자 ID를 대체로 사용하면 안 됩니다.

이 클라이언트는 비밀번호나 토큰을 디스크에 저장하지 않습니다. 비밀번호는 호출 인수와 요청 생성 중에만 사용하며 클라이언트 속성으로 보관하지 않습니다. 토큰·기기 UUID·인증 번호의 기본 `repr`는 숨깁니다. 상세 로컬 변수까지 수집하는 디버거/로깅 훅을 사용하면 호출자가 넘긴 비밀값이 포함될 수 있으므로 일반 예외 문자열만 기록해야 합니다. 내부 HTTP 클라이언트는 인증서 검증을 사용하고 리다이렉트를 따라가지 않습니다. 주입한 `httpx.AsyncClient`의 TLS 검증 설정과 종료는 호출자 책임입니다.

모델 확인 GET에도 원본과 같은 `Content-Type: application/x-www-form-urlencoded`를 보냅니다. 이 헤더를 생략한 초기 공개 모델 확인은 HTTP415를 반환했고, 그 결과를 성공으로 처리하지 않았습니다.

## 동일 프로필의 LOCO 연결

[GetConfOut.java](https://github.com/NetRiceCake/loco-wrapper/blob/1dec3b79e59f2776ebd1f03e60744162ff195b24/src/main/java/com/github/netricecake/kakao/packet/outbound/login/GetConfOut.java), [CheckInOut.java](https://github.com/NetRiceCake/loco-wrapper/blob/1dec3b79e59f2776ebd1f03e60744162ff195b24/src/main/java/com/github/netricecake/kakao/packet/outbound/login/CheckInOut.java), [LoginListOut.java](https://github.com/NetRiceCake/loco-wrapper/blob/1dec3b79e59f2776ebd1f03e60744162ff195b24/src/main/java/com/github/netricecake/kakao/packet/outbound/login/LoginListOut.java)와 [TalkClient.java](https://github.com/NetRiceCake/loco-wrapper/blob/1dec3b79e59f2776ebd1f03e60744162ff195b24/src/main/java/com/github/netricecake/kakao/TalkClient.java)에서 확인한 필드는 다음과 같습니다.

```text
GETCONF: MCCMNC="45006", os="android", userId
CHECKIN: userId, os="android", ntype=0, appVer="26.8.2", lang="ko", MCCMNC="45006"
LOGINLIST:
  appVer="26.8.2", prtVer="1", os="android", lang="ko", duuid,
  ntype=0, MCCMNC="45006", revision=0, chatIds=[], maxIds=[],
  lastTokenId=0, lbk=0, rp=Binary(0000ffff0000), bg=true,
  oauthToken=login.access_token
```

Booking은 TLS `booking-loco.kakao.com:443`으로 연결합니다. 응답 `ticket.lsl[0]`와 `wifi.ports[0]`를 Checkin에 사용하고, Checkin 응답의 `host`/`port`로 채팅 서버에 TLS 연결합니다. 현재 Java 소스는 인증서 전부 신뢰 설정이 있지만 **이 패키지는 CA·호스트 이름 검증을 유지합니다.** TLS 검증이 실패하면 원인을 확인하고 중단해야 합니다. 이 프로필의 채팅 연결에는 RSA/AES-GCM V2SL을 대신 시도하지 않습니다. 원본 README는 이미지 전송이 별도 V2SL을 사용한다고 설명합니다.

Java 구현은 숫자를 JSON 파서로 BSON화하므로 작은 정수의 Int32/Int64 선택을 모든 필드에 명시하지 않습니다. Python 쪽 userId·chatId·logId 같은 식별자는 `bson.Int64`를 사용해 정확성을 유지합니다. Mac 프로필의 `dtype`, `countryISO`, `useSub`, `bg=false` 등을 근거 없이 섞지 않습니다.

## 갱신·QR 대안의 조사 결과

agent-messenger의 [oauth-refresh.ts](https://github.com/agent-messenger/agent-messenger/blob/e58739d80305d5e8ddf72e9aad085c2069f4fd3c/src/platforms/kakaotalk/auth/oauth-refresh.ts)는 `POST /android/account/oauth2_token.json`을 사용합니다. JSON은 `access_token`, `refresh_token`, `grant_type:"refresh_token"`입니다. `Authorization`은 `accessToken-deviceId`, `C`는 요청 UUID, `A`와 User-Agent는 해당 구현의 Android25.9.2입니다. 40~64자리 hex ID는 그대로 사용하고 그 외 ID는 고정 문자열 접두사를 붙여 SHA-256으로 만듭니다. 테스트는 Mock fetch를 사용합니다. 현재26.8.2 주 근거에 같은 갱신 흐름을 검증한 결과가 없으므로 본 인증 모듈에 자동 갱신을 추가하지 않았습니다.

KakaoForge는 QR 생성→로그인 폴링→휴대폰 승인 후보를 구현하며 메인 기기의 승인 요청은 기존 refresh token을 이용한 HMAC-SHA256도 설명합니다. README와 코드의 존재만으로 현재26.8.2에서 QR가 성공한다고 판단할 수 없으며 이번 구현에는 포함하지 않았습니다. 기기 등록 승인 자체를 우회하는 수단으로 취급하지 않습니다.

## 검증 상태와 남은 실환경 증거

- **확인한 것:** 고정 소스의 요청 경로·필드·서명 입력, 일관된26.8.2 프로필, Python의 큰 정수 보존, 단일 요청 의미론, 개인정보를 숨기는 결과/오류, HTTP 오류·시간 초과·등록 상태 전이의 MockTransport 테스트.
- **저자 보고:** loco-wrapper26.8.2 README는 업데이트 후 Booking/Checkin이 테스트에서 정상 동작했다고 하며 모든 경우를 확인하지 않았다고 명시합니다. 이 작업에서 재현하지 않았습니다.
- **확인하지 않은 것:** 현재 서버의26.8.2 수용, 모델 allowlist, 새 기기 로그인/휴대폰 승인 성공, 토큰으로 LOGINLIST 성공, 단체방 실수신·발송, 장기 세션 유지.

별도의 계정 없는 공개 확인에서는 `userId=0`으로 보낸 Android GETCONF가 CA·호스트 이름을 검증한 TLS1.3 연결에서 `status=0`을 반환했습니다. 응답의 첫 Ticket 호스트는 `ticket-loco.kakao.com`, 첫 Wi-Fi 포트는 `9282`였습니다. 이는 Booking 경로와 프레이밍의 실제 응답 증거이며 계정 인증 성공 증거가 아닙니다. 원본 관찰 기록은 `docs/analysis/phase4-x86-runtime/public-probes.json`에 있습니다. 최초 모델 확인415 기록도 보존합니다.

완료 판정에는 사용자가 제어하는 테스트 계정으로 한 번의 명시적인 로그인·휴대폰 등록을 거친 뒤, 새 Python 프로세스에서 토큰/UUID를 사용해 TLS Booking→Checkin→LOGINLIST를 통과하고 지정 테스트 방에서 송수신한 증거가 필요합니다. 필요한 입력은 계정 인증 정보, 사용자의 휴대폰 확인, 생성한 UUID의 유지입니다. 설치 앱의 메모리나 저장소에서 비밀번호·토큰을 추출할 필요가 있는 설계가 아닙니다. 서버 거절이 나오면 상태/HTTP 코드·요청 프로필·인증서 체인을 보존해 원인을 구분하고, 실제 앱과 비교할 경우 같은 **Android** 버전의 승인된 런타임 요청 필드를 확인해야 합니다. 현재 Windows26.9 바이너리의 문자열만으로 Android26.8.2 인증이 성공한다고 결론 낼 수 없습니다.
