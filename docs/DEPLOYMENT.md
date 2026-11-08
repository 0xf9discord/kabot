# 채널 봇 배포 및 운영

## 연결 순서

1. 카카오 채널과 챗봇을 준비하고 챗봇 관리자센터에서 스킬을 만듭니다.
2. Kabot 서버를 공개 HTTPS 도메인 뒤에서 실행합니다. `/healthz`로 프로세스 상태를 확인합니다.
3. 충분히 긴 무작위 비밀값을 생성해서 `KABOT_WEBHOOK_SECRET`에 보관합니다. 재시작 후에도 동일 값을 주입해야 합니다.
4. 스킬 URL을 `https://your-domain/skill/<secret>`으로 지정합니다. `KABOT_BOT_ID`도 지정해서 다른 봇의 요청을 거부합니다.
5. 블록에 스킬을 연결하고 스킬데이터를 응답으로 사용하도록 설정합니다. 여러 명령을 처리하려면 폴백 블록도 이 스킬로 연결하세요.
6. 챗봇을 채널에 연결하고 배포한 뒤 사용자의 카카오톡에서 실제 대화를 확인합니다.

비밀 경로는 라이브러리에서 제공하는 접근 제어입니다. 카카오가 서명한 요청임을 암호학적으로 확인하는 기능은 아닙니다. 경로가 유출되면 교체하세요. 리버스 프록시에서도 `/skill/*` 경로·요청 본문·쿼리를 로그에 남기지 않도록 설정하세요. CLI의 Uvicorn access log는 비활성화되어 있습니다. 요청률 제한과 TLS는 앞단 프록시에서 구성합니다.

## 시간 제한

카카오 스킬 요청은 짧은 시간 내 응답해야 합니다. Kabot 기본 핸들러 제한은 4초입니다. 비동기 작업은 취소될 수 있지만 동기 핸들러는 Python 스레드에서 실행되어 타임아웃 후에도 작업이 계속될 수 있습니다. 외부 결제·주문·발송 같은 작업은 애플리케이션의 중복 실행 방지 키/트랜잭션으로 보호하세요. Kabot은 같은 발화를 반복했다는 이유로 요청을 중복 취급하지 않습니다.

## 콜백

```python
import os
from kabot import Bot, create_app

bot = Bot()

@bot.command("분석", deferred=True)
async def analyze(ctx):
    result = await your_async_analysis(ctx.args)  # 애플리케이션에서 구현
    return result

app = create_app(
    bot,
    webhook_secret=os.environ["KABOT_WEBHOOK_SECRET"],
    expected_bot_id=os.environ["KABOT_BOT_ID"],
    callback_hosts=("실제-검증한-카카오-콜백-호스트",),
)
```

위 호스트 문자열은 예시 자리표시자이므로 실제 검증한 ASCII DNS 호스트명으로 바꿔야 합니다. 임의의 도메인을 추측해서 허용하지 마세요. 정확한 HTTPS 호스트와 443 포트만 허용하며 URL 사용자정보/fragment 및 리다이렉트를 거부합니다. 운영 네트워크의 egress 제어도 적용하세요. CLI는 `KABOT_CALLBACK_HOSTS`의 쉼표 구분 호스트 목록을 사용합니다.

콜백 활성화된 블록에서 `userRequest.callbackUrl`을 받으면, 서버가 `{version:"2.0", useCallback:true}`를 먼저 반환하고 배경 작업으로 결과를 한 번 POST합니다. 문서는 도입부에서 5분 유효, 오류표에서는 1분 이내라는 서로 다른 안내를 포함합니다. 이 구현은 보수적으로 처리 작업을 기본 40초(설정 상한 45초)로 제한하며, POST 응답은 HTTP 성공과 `status=SUCCESS` 모두 확인합니다. 실패는 URL/토큰 없이 오류 종류를 기록합니다. 단일 사용 토큰이므로 POST는 자동 재시도하지 않습니다.

FastAPI BackgroundTasks는 프로세스 내부 작업입니다. 서버 종료/충돌 때 작업이 유실될 수 있으며 영속 작업 큐가 아닙니다. 장시간 AI 작업·무거운 CPU 작업·대규모 운영에는 별도의 작업 큐와 관측 시스템을 연결해야 합니다. 테스트용 callback token은 실제 전송에 사용할 수 없다는 카카오 제한이 있습니다.

출처: [카카오 콜백 개발 가이드](https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/ai_chatbot_callback_guide), [스킬 개발 가이드](https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide). 확인일: 2026-10-31.

## 패키징

프로젝트에서 `python -m build`로 wheel과 sdist를 만듭니다. 다른 서버에서는 `pip install /path/to/kabot_python-0.3.0-py3-none-any.whl`로 설치합니다. 개인 계정 기능은 LOCO 추가 의존성이 필요합니다. PyPI 업로드는 하지 않습니다. `docs/analysis`의 실행 파일과 IDA 데이터베이스, 사용자 세션 파일은 배포 대상에 포함하지 않습니다.
