# Kabot Python

**서버에 카카오톡을 설치하지 않고 실행하는 카카오톡 봇 파이썬 라이브러리.** Python 3.11+, Windows/Linux/macOS에서 사용합니다. 채널 챗봇, 공식 메시지 API, 실험용 개인 계정·단체방 클라이언트를 제공합니다. PyPI에 게시되지 않은 로컬 패키지입니다.

| 기능 | 현재 상태 |
|---|---|
| 채널에서 사용자 질문에 응답 | 구현, 공개 HTTPS 스킬 서버 연결 필요 |
| 명령어/정규식/액션/전처리 | 구현, 동기·비동기 핸들러 |
| 카드/이미지/바로가기/긴 텍스트 | 구현 |
| 사용자별 메모·방문 횟수·TTL | SQLite로 구현 |
| 시간이 오래 걸리는 작업의 콜백 | 구현, 카카오 블록 활성화 + 정확한 호스트 허용 설정 필요 |
| 개인 계정의 나에게 보내기 | 공식 OAuth/API로 구현 |
| 친구에게 보내기 | 공식 API로 구현, 권한·동의·수신 대상 제한 적용 |
| 개인 계정·단체방 LOCO 수신/텍스트 응답 | 실제 오픈채팅에서 명령 수신·1회 답장 및 사용자 수신 확인 |
| 비밀번호 로그인·휴대폰 기기 등록·토큰 발급 | Android26.8.2 프로필 구현, 실제 사용자 계정 인증·세션 저장 확인 |
| 암호화 세션·로컬 입력 창 | 0.3.0 구현, 세션 암호로 재사용 |
| 참여 중인 오픈채팅 텍스트 | 명시적 `--allow-open` 테스트·실제 송수신 확인, 서버 방 이름 조회 |
| 자동 토큰 갱신·오픈채팅 참여/관리·E2E 비밀채팅 | 미구현 |

운영 서버에는 카카오톡 앱이 필요 없습니다. 채널 방식은 채널/챗봇 설정이 필요하고, 공식 메시지 API는 개발자 앱과 사용자 동의가 필요합니다. 실험용 개인 계정 방식은 기존 계정과 새 기기 등록을 승인할 휴대폰을 사용합니다. [개인 계정 로그인·실행 안내](docs/LOGIN.md)를 참조하세요.

## 설치 및 바로 실행

PowerShell에서 이 프로젝트 폴더를 열고:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\kabot.exe init mybot.py
.\.venv\Scripts\kabot.exe chat mybot:bot
```

로컬에서 `/도움말`, `/안녕 철수`, `/방문`, `/메모 내일 회의`, `/메모확인`을 입력해 보세요. 실제 메시지는 전송하지 않습니다. `init`은 기존 파일을 덮어쓰지 않습니다. Linux/macOS에서는 `.venv/bin/python`, `.venv/bin/kabot`을 사용합니다.

```python
from kabot import Bot, SQLiteStore, create_app

bot = Bot(store=SQLiteStore("mybot.sqlite3"))

@bot.command("안녕")
def hello(ctx):
    return f"안녕하세요, {ctx.args or '친구'}님!"

@bot.command("방문")
def visit(ctx):
    count = ctx.store.increment(ctx.scope, "visits")
    return f"{count}번째 방문입니다."

@bot.hears(r"^문의 (.+)$")
async def question(ctx):
    return f"문의: {ctx.match[1]}"
```

첫 번째로 일치하는 핸들러 하나가 실행됩니다. 포괄적인 `@bot.on_message()`는 마지막에 등록하세요. `@bot.action("액션명")`으로 스킬 액션 이름에 연결할 수 있습니다. `@bot.before` 전처리에서 응답을 반환하면 실행을 중단하고, `None`이면 계속합니다. `ctx.params`는 action.params, `ctx.user_id`는 봇 범위 사용자 ID이며 카카오 계정 ID/친구 UUID와 다릅니다.

## 오픈채팅 프로필 변경

0.4.0에서 `get_open_profile()`, `list_open_links()`, `change_open_profile()`과
프로필을 순서대로 반복 적용하는 `loopchange()`를 추가했습니다. 기본 프로필·익명
프로필·기존 오픈프로필로 전환하며, 간격·최대 횟수·중지 신호를 지정할 수 있습니다.
구현 및 모의 테스트를 완료했으며 실제 계정의 프로필 변경은 아직 검증하지 않았습니다.
[사용법과 실행 예제](docs/OPEN_PROFILE.md)를 참고하세요.

## 실제 채널에 연결

```powershell
$env:KABOT_WEBHOOK_SECRET = .\.venv\Scripts\kabot.exe secret
$env:KABOT_BOT_ID = '챗봇 관리자센터의 봇 ID'
.\.venv\Scripts\kabot.exe run mybot:bot
```

서버 앞에 HTTPS 리버스 프록시를 구성하고, 챗봇 관리자센터의 스킬 URL을 `https://내도메인/skill/생성한비밀값`으로 지정합니다. 실제 비밀값은 위 환경변수에 저장된 값입니다. 블록 또는 폴백 블록에 이 스킬을 연결하고 응답에서 **스킬데이터 사용**을 선택한 뒤 채널에 연결·배포하세요. 서버 기본 포트는 8000이며 로컬 인터페이스에 바인딩합니다. 컨테이너는 `--host 0.0.0.0`을 사용합니다. 상세 내용은 [배포 안내](docs/DEPLOYMENT.md)를 참조하세요.

개인 계정의 나에게/친구에게 메시지 보내기, OAuth 로그인과 갱신은 [공식 REST API 안내](docs/REST.md)에 있습니다.

0.3.0의 개인 계정·단체방 프로토콜 계층은 [LOCO 안내](docs/LOCO.md),
계정 입력과 암호화 세션 재사용은 [로그인 안내](docs/LOGIN.md)에 있습니다.
`pip install -e '.[loco]'`로 추가 의존성을 설치합니다.

## 카드, 이미지, 버튼

```python
from kabot import card, link_button, quick_reply, text, image

answer = card("주문 안내", "주문 현황을 확인하세요.", "https://example.com/product.png",
              buttons=[link_button("주문 보기", "https://example.com/orders")])
answer = answer.with_quick_replies(quick_reply("도움말", "/도움말"))
long_answer = text("긴 텍스트")  # 최대 3000자를 1000자씩 최대 3개 말풍선으로 분할
picture = image("https://example.com/photo.jpg", "상품 사진")
```

`Response(outputs=[...])`로 추가 공식 응답 형식을 직접 구성할 수도 있습니다. 이 경우 내부 필드 규격은 호출자가 확인합니다. 기본 빌더는 길이와 개수 제한을 검사하며 임의로 내용을 잘라내지 않습니다. API의 상세 제약은 [카카오 스킬 응답 규격](https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format)을 따릅니다.

## 느린 작업과 상태 저장

`@bot.command("분석", deferred=True)`는 콜백을 통해 응답합니다. 카카오 블록의 콜백을 활성화하고 실제 카카오가 제공하는 콜백 URL의 정확한 호스트를 운영자가 검증한 뒤 `KABOT_CALLBACK_HOSTS`에 설정해야 합니다. 설정하지 않으면 외부 콜백은 전송되지 않습니다. [운영 제한과 콜백 설정](docs/DEPLOYMENT.md)을 먼저 확인하세요.

`SQLiteStore`는 사용자 상태를 JSON으로 보관하고 TTL을 지원합니다. 사용자 범위는 `ctx.scope`를 쓰세요. `increment`는 여러 동시 요청에도 원자적으로 증가합니다. `get` 후 `set`을 하는 임의의 갱신은 원자적이지 않습니다. 파일 백업·접근 권한·보관 기간은 운영자가 관리합니다.

## 검증과 역분석

PyPI 배포용 빌드·검증은 `python tools/build_release.py`로 실행합니다.
현재 버전의 배포 파일만 `dist/pypi/0.4.0/`에 만들며 업로드는 하지 않습니다.
[PyPI 배포 안내](docs/PUBLISHING.md)를 참고하세요.

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[dev,loco]'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build
```

자동 테스트는 HTTP 모의 서버로 실행하며 실계정 로그인을 하거나 카카오톡 메시지를 발송하지 않습니다. 실계정 인증·채널 배포·실제 도착 여부는 별도 확인이 필요합니다.

REA PE 분석 근거는 `docs/rea-evidence.json`, 실제 IDA Pro 9.3 정적 분석 결과는 [IDA 분석 보고서](docs/IDA_ANALYSIS.md)에 있습니다. 첫 압축 계층 약 20.9MB를 오프라인 복원하고 IDA로 다시 분석했으나 로그인/단체방 프로토콜까지 복구하지는 못했습니다. 실험용 LOCO 계층은 고정한 MIT 공개 소스를 별도 근거로 사용했습니다. 분석에 사용한 원본 실행 파일·IDA 데이터베이스는 배포 패키지에 포함하지 않습니다.

이 프로젝트는 카카오의 공식 SDK가 아닙니다. 라이선스: MIT.
