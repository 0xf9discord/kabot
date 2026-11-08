# 카카오 공식 REST API

이 모듈은 서버에서 실행하며 PC 카카오톡이 필요하지 않습니다. 카카오 로그인으로 발급한 사용자 토큰을 사용합니다. 일반 대화방의 메시지를 수신하거나 방 번호로 메시지를 보내는 기능은 공식 API에 없습니다.

## 준비

1. [카카오디벨로퍼스](https://developers.kakao.com/)에서 앱을 만들고 카카오 로그인, Redirect URI, REST API 키와 Client secret을 설정합니다.
2. `talk_message` 동의항목을 사용합니다. 친구 조회에는 `friends` 동의 및 카카오톡 소셜 API 사용 권한이 필요합니다.
3. 메시지에 사용할 링크 도메인을 앱의 제품 링크 관리에 등록합니다.
4. 친구 메시지는 앱에 연결되고 필요한 동의를 완료한 수신자만 대상으로 하며 최대 5명씩 전송합니다. 카카오의 이용 권한·쿼터가 적용됩니다.

## 로그인

```python
import secrets
from kabot.rest import KakaoClient, authorization_url

state = secrets.token_urlsafe(32)  # 사용자 세션에 저장하고 콜백 후 한 번만 사용
login_url = authorization_url(
    "REST_API_KEY", "https://your-domain.example/oauth/callback",
    state=state, scopes=["talk_message", "friends"],
)
# 사용자를 login_url로 이동. callback의 code/state를 웹 프레임워크로 받음.

async def complete_login(code, returned_state, session_state):
    async with KakaoClient(client_id="REST_API_KEY", client_secret="CLIENT_SECRET") as api:
        tokens = await api.exchange_code(
            code, "https://your-domain.example/oauth/callback",
            expected_state=session_state, received_state=returned_state,
        )
        return tokens  # 애플리케이션의 안전한 저장소에 보관
```

`state`는 각 로그인 시도마다 생성하고 세션에 연결해서 사용 후 폐기하세요. `exchange_code`는 상태 일치 확인 후에만 네트워크 요청을 수행합니다. 토큰은 파일에 자동 저장하지 않습니다.

## 나에게 알림 보내기

```python
import asyncio
import os
from kabot.rest import KakaoClient

async def main():
    async with KakaoClient(os.environ["KAKAO_ACCESS_TOKEN"]) as api:
        await api.send_self_text(
            "작업이 완료되었습니다.", link_url="https://your-registered-domain.example/jobs"
        )

asyncio.run(main())
```

텍스트 템플릿은 200자까지입니다. `link_url`은 필수이며 해당 도메인을 앱에 등록해야 합니다.

## 친구 조회와 전송

```python
page = await api.list_friends(offset=0, limit=20)
uuids = [friend["uuid"] for friend in page.get("elements", [])[:5]]
if uuids:
    result = await api.send_friends_text(uuids, "준비되었습니다.", link_url=registered_url)
    # HTTP 200이라도 일부 수신자 실패 가능. 자동 재전송하지 말고 확인.
    failures = result.get("failure_info", [])
```

`list_friends`는 한 페이지만 반환합니다. 다음 페이지가 필요하면 `after_url` 존재 여부를 확인하고 `offset`을 증가시켜 호출하세요. 외부 URL을 직접 따라가지 않습니다. 친구 UUID는 채널 봇 사용자 ID와 서로 다른 값입니다.

`send_self_template` / `send_friends_template`는 기본 템플릿 객체를, `send_self_custom` / `send_friends_custom`은 메시지 템플릿 도구에서 등록한 `template_id`와 `template_args`를 받습니다.

## 운영 동작

- `refresh(refresh_token)`는 갱신 토큰을 명시해서 호출합니다. 같은 인스턴스에서 로그인했다면 `refresh()`도 가능합니다. 새 리프레시 토큰이 응답에 없으면 기존 값을 유지합니다. 갱신 결과를 안전한 저장소에도 반영하세요.
- 메시지 전송과 OAuth POST는 재시도하지 않습니다. 전송 후 응답 시간 초과는 실제 도착 여부가 불명확합니다.
- GET은 기본 2회까지 추가 시도하며 429/5xx와 전송 오류에만 적용합니다. `Retry-After` 대기는 기본 최대 5초로 제한합니다. `read_retries=0`으로 해제할 수 있습니다.
- `KakaoAPIError.status_code`, `.code`, `.server_message`로 오류를 검사합니다. 예외의 기본 문자열과 토큰 객체 repr에는 토큰을 넣지 않습니다. 서버 상세 메시지는 기록 전에 직접 검토하세요.
- 기본 요청 제한시간은 10초입니다. `http_client=httpx.AsyncClient(...)`를 주입하면 해당 클라이언트 종료는 호출자가 책임집니다.

공식 문서 확인일: 2026-10-31. 실제 계정 로그인·발송은 수행하지 않았으며 자동 검증은 MockTransport로 HTTP 요청 형태와 오류 처리를 확인합니다.

출처: [카카오 로그인 REST API](https://developers.kakao.com/docs/ko/kakaologin/rest-api), [카카오톡 메시지 REST API](https://developers.kakao.com/docs/ko/kakaotalk-message/rest-api), [친구 조회 REST API](https://developers.kakao.com/docs/ko/kakaotalk-social/rest-api), [기본 메시지 템플릿](https://developers.kakao.com/docs/ko/message-template/default).
