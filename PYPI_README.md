# Kabot Python

**카카오톡 앱 설치 없이 운영하는 Python 카카오톡 봇 라이브러리.**

Python 3.11 이상에서 채널 챗봇 서버, 공식 메시지 REST API,
실험용 개인 계정·일반채팅·오픈채팅 LOCO 클라이언트를 제공합니다.
카카오의 공식 SDK가 아닙니다.

## 설치

```console
python -m pip install pykabot
```

개인 계정·오픈채팅 기능을 사용하려면:

```console
python -m pip install "pykabot[loco]"
```

배포 이름은 `pykabot`, Python import 이름과 실행 명령은 `kabot`입니다.
Windows, Linux, macOS에서 사용할 수 있는 순수 Python 패키지입니다.

## 네트워크 없이 봇 만들기

```console
kabot init mybot.py
kabot chat mybot:bot
```

`/도움말`, `/안녕 철수`, `/방문`, `/종료`를 입력해 볼 수 있습니다.
이 시뮬레이터는 실제 카카오톡 메시지를 전송하지 않습니다.

```python
from kabot import Bot, SQLiteStore

bot = Bot(store=SQLiteStore("mybot.sqlite3"))

@bot.command("안녕")
def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"

@bot.command("방문")
def visit(ctx):
    count = ctx.store.increment(ctx.scope, "visits")
    return f"{count}번째 방문입니다."
```

동기·비동기 핸들러, 정규식 매칭, 액션, 전처리와 SQLite 사용자 상태를 지원합니다.

## 채널 챗봇

```console
kabot secret
```

생성된 값을 `KABOT_WEBHOOK_SECRET` 환경변수에 설정한 뒤 실행합니다.

```console
kabot run mybot:bot
```

공개 HTTPS 서버와 카카오 챗봇 관리자센터의 스킬 연결이 필요합니다.
스킬 주소는 `https://YOUR_HOST/skill/YOUR_WEBHOOK_SECRET`입니다.
텍스트·카드·이미지·버튼 응답과, 별도 콜백 설정이 필요한 지연 응답을 지원합니다.
공식 메시지 REST API는 별도의 카카오 개발자 앱, OAuth 동의 및 권한이 필요합니다.

## 개인 계정·오픈채팅

```console
kabot login
kabot chats
kabot init personal_bot.py --personal
kabot personal personal_bot:bot --chat-id YOUR_CHAT_ID
```

`YOUR_CHAT_ID`를 `kabot chats`에 표시된 실제 숫자 ID로 바꾸세요.
계정 비밀번호와 세션 파일 암호는 실행한 터미널에서 직접 입력합니다.
최초 로그인은 기기 등록을 승인할 휴대폰이 필요할 수 있습니다.
서버에는 카카오톡 앱이 필요 없습니다. GUI 입력 창은 Tkinter가 설치된 데스크톱에서
`kabot gui --mode login`으로 열 수 있습니다.

Android 26.8.2 프로필의 로그인·기기 등록, 암호화 세션 저장, 방 목록 조회,
실시간 텍스트 수신·전송을 구현했습니다. 실제 오픈채팅에서 명령 수신과
1회 답장 도착을 확인했습니다. 모든 환경·계정에서의 호환성을 보장하지 않습니다.
자동 토큰 갱신·자동 재접속·미디어 업로드·비밀채팅은 아직 지원하지 않습니다.

## 오픈채팅 프로필 순환 변경

로그인된 `PersonalClient`에서 기본·익명·기존 오픈프로필로 전환할 수 있습니다.
다음은 이미 연결된 `client`를 사용하는 예시입니다.

```python
from kabot.loco import OpenChatProfile

await client.loopchange(
    chat_id,
    [OpenChatProfile.link(profile_a_id), OpenChatProfile.link(profile_b_id)],
    interval=60,
    max_changes=10,
)
```

`max_changes`를 생략하면 계속 반복하며 `stop_event=asyncio.Event()`로 중지할 수 있습니다.
서버 오류 시 중단하고, 중지 후 마지막 프로필을 유지합니다.
단독 실행 시에도 LOCO 푸시 이벤트를 소비해야 하며, 봇의 메시지 소비 루프와 함께
실행할 수 있습니다. 프로필 변경은 모의 테스트만 완료했으며 실계정 반영은 미검증입니다.

```console
kabot open-profile --help
```

## 라이선스

MIT. 공개 프로토콜 참고 소스의 라이선스·저작권 고지는 배포 파일의
`kabot/THIRD_PARTY_NOTICES.md` 및 라이선스 메타데이터에 포함되어 있습니다.
