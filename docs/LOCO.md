# 개인 계정·단체방 LOCO 계층 (0.3.0)

0.3.0에는 **Android26.8.2 계정 인증, 휴대폰 기기 등록, 암호화 세션 저장**을 추가했습니다.
2026-11-08 사용자 직접 입력으로 실제 계정 인증과 채팅 서버 `LOGINLIST`가 성공했고,
채팅방 항목28개를 받았습니다. 이후 선택한 오픈채팅에서 다른 계정의 새 명령을 수신하고
답장1회의 서버 성공 응답과 사용자 화면의 실제 수신까지 확인했습니다.
사용 절차는 [로그인 안내](LOGIN.md)에 있습니다.

Android 프로필은 loco-wrapper의 고정된26.8.2 소스, 기존 macOS 프로필은 openkakao-cli
소스를 근거로 합니다. 두 프로필의 인증 필드와 암호화 방식을 섞지 않습니다. macOS
프로필은 참고용으로 유지하며 현재 실계정 확인은 Android 프로필에서 수행했습니다.

## 근거와 구현 범위

| 항목 | 구현/검증 상태 |
|---|---|
| 22바이트 little-endian 헤더 + BSON | 직접 바이트 fixture와 정수 범위·분할 파싱 테스트 |
| 64비트 사용자·채팅·로그 ID | `bson.Int64` 보존 테스트; float 변환 없음 |
| RSA-OAEP-SHA1 / AES-128-GCM | 로컬 RSA 복호화, NIST GCM 벡터, 변조 거부 테스트 |
| Android TLS 및 서비스 이름 | 실제 서버 CA 검증 성공, IP 배정 시 `kakao.com` 검증, 잘못된 이름 거부 테스트 |
| TCP 분할·합쳐진 패킷·암호화 레코드 재조립 | 로컬 테스트 |
| Booking → CHECKIN → LOGINLIST | 모의 응답과 실제 loopback TCP로 흐름 검증 |
| 동시 요청과 push 분리 | 요청 ID/메서드 대응, push 보존, 큐 초과 시 연결 중단 |
| MSG / SYNCMSG | flat, chatLog, chatLogs 구조와 ID 충돌 검사 |
| CHATONROOM / WRITE | 로컬 TCP 모의 서버에서 요청·응답 검증 |
| 개인/단체방 명령어 봇 어댑터 | 지정한 방·새 텍스트·타인 메시지만 처리, 중복 이벤트 억제 |
| 실제 계정 인증·LOGINLIST | 2026-11-08 사용자 직접 입력으로 확인 |
| 비밀번호 로그인·기기 등록·토큰 발급 | 구현, 비밀번호는 저장하지 않음 |
| 암호화 세션 파일 | scrypt + AES-256-GCM, GUI/CLI에서 사용자 암호로 열기 |
| 전체 방 목록·정식 방 이름 | LCHATLIST 페이지 + 읽기 전용 CHATINFO/INFOLINK |
| 참여 중인 오픈채팅 텍스트 | 명시적 `--allow-open`, 실제1회 송수신·사용자 수신 확인 |
| 첨부파일·이미지 발송·오픈채팅 참여/관리·E2E 비밀채팅 | 미구현 |

기존 패킷/암호화/메시지 필드의 출처는 고정한 공개 소스 커밋
`6ca6ea2fd05a6660c4a80c0b61b43b416653d1d5`입니다. Windows 실행 파일에서 이 규격을
직접 복구한 결과가 아닙니다. 네이티브 역분석 결과는 [IDA 기록](IDA_ANALYSIS.md),
참고 코드의 MIT 라이선스는 [서드파티 고지](THIRD_PARTY_NOTICES.md)에 구분했습니다.

## 설치

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[loco]'
```

다른 서버에서는 wheel 파일을 설치하고 `pymongo>=4.10,<5`, `cryptography>=44,<50`을
설치합니다. 이 프로젝트는 PyPI에 게시되지 않았습니다. `bson`이라는 별도 패키지를
설치하지 마세요. `pymongo`에 포함된 BSON을 씁니다. 기본 채널/공식 REST 기능은
이 optional dependency 없이 사용할 수 있습니다.

## 사용 형태

```python
from kabot import Bot
from kabot.loco import Credentials, PersonalClient, run_personal_bot

bot = Bot()

@bot.command("안녕")
async def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"

async def run(credentials: Credentials, chat_ids: set[int]):
    async with PersonalClient(credentials) as client:
        await client.connect()  # 실제 실행하면 서버 연결과 LOGINLIST를 한 번 시도
        await run_personal_bot(bot, client, chat_ids=chat_ids)
```

`Credentials(user_id, oauth_token, device_uuid, app_version, profile="android")`는 Android
계정 인증으로 얻은 LOCO 세션 정보를 받습니다. 기본 `profile="mac"`는 기존 호환용입니다.
**공식 개발자 REST API 토큰과 서로 바꿔 쓸 수
있다고 가정하면 안 됩니다.** 로컬 앱·캐시·운영체제 자격 증명 저장소를 뒤져 자동으로
정보를 읽는 기능은 없습니다. 토큰·기기 ID는 객체 repr에서 숨깁니다.

`examples/personal_bot.py`에는 환경변수로 입력받는 실행 예제가 있습니다. 필요한 항목은
`KABOT_LOCO_USER_ID`, `KABOT_LOCO_TOKEN`, `KABOT_LOCO_DEVICE_UUID`,
`KABOT_LOCO_APP_VERSION`, `KABOT_LOCO_CHAT_IDS`(쉼표 구분 방 ID)입니다.
현재 호환성을 확인한 자격 증명이 없는 상태에서는 이 예제가 동작한다고 보장하지 않습니다.

## 연결과 실패 처리

- GUI/CLI 계정 로그인은 Android26.8.2 프로필을 생성합니다. 직접 `Credentials`를 만드는
  코드는 사용할 프로필을 지정하세요.
- Android는 Booking/Checkin/채팅 모두 TLS를 사용합니다. 배정된 채팅 IP와 인증서의
  서비스 이름 `kakao.com`을 분리해 정상 CA/호스트 검증을 유지합니다. 기존 macOS
  프로필의 Checkin/채팅에는 참고 RSA+GCM 계층을 사용합니다.
- 참고 RSA 공개키는 소스에서 가져온 값이며 현행 서버 키로 독립 검증한 것은 아닙니다.
  `PersonalClient(..., public_key_der=검증한키)`로 교체할 수 있습니다.
- `LocoStatusError.method`, `.status`로 서버 거부를 확인합니다. 특히 인증 실패를 자동
  재시도하지 않습니다. 서버가 지정한 이동/퇴장도 연결을 멈추고 호출자에게 알립니다.
- 요청 타임아웃·취소·수신 파싱/인증 실패 시 연결을 닫습니다. WRITE 이후 응답이 없으면
  실제 도착 여부가 불명확하므로 자동 재전송하지 않습니다.
- 수신 큐는 기본 256개입니다. 소비자가 뒤처지면 조용히 메시지를 버리는 대신
  `EventOverflowError`로 연결을 중단합니다.
- 30초마다 PING을 보냅니다. 자동 재접속이나 과거 메시지 동기화는 구현하지 않았습니다.
- 봇 어댑터는 텍스트 응답만 지원하고, 일반 대화/자기 메시지/다른 방/비텍스트는 무시합니다.
  중복 억제는 기본 4096개이며 프로세스 재시작 뒤에는 보존되지 않습니다.
  애플리케이션의 영속 중복 처리나 exactly-once 보장을 대신하지 않습니다.
- `ctx.metadata`에 `chat_id`, `log_id`, `transport="loco"`를 제공합니다.
  `ctx.scope`는 계정·방·발화자 범위입니다. 응답 오류는 무시하지 않고 실행을 중단합니다.

## 검증 실행

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,loco]'
.\.venv\Scripts\python.exe -m pytest tests/test_loco_packet.py tests/test_loco_crypto.py tests/test_loco_session.py tests/test_loco_integration.py -q
```

위 자동 테스트의 토큰·RSA 비밀키·TCP 서버는 가짜 값/로컬 서버를 사용합니다. 자동
테스트와 별도로 사용자 직접 입력의 실제 계정 인증·LOGINLIST를 확인했습니다.
계정 정보나 채팅 내용을 테스트 fixture와 배포 파일에 포함하지 않습니다.
