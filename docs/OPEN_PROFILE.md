# 오픈채팅 프로필 변경·순환 변경

0.4.0 추가 기능입니다. 기존 오픈채팅방에서 **자신이 사용하는 참여 프로필**을
바꿉니다. 계정 기본 프로필 자체나 저장된 오픈프로필의 이름·사진을 편집하지는 않습니다.
아직 이 기능의 실계정 변경·화면 반영은 검증하지 않았습니다.

## Python API

로그인된 `PersonalClient`에 다음 메서드를 사용할 수 있습니다.

```python
from kabot.loco import OpenChatProfile

# 조회만 수행
links = await client.list_open_links()  # 계정 연결 오픈링크; 모두 프로필인 것은 아님
current = await client.get_open_profile(chat_id)

# 세 가지 전환 방식. 각 호출은 실제 프로필 변경을 한 번 요청함
await client.change_open_profile(chat_id, OpenChatProfile.main())
await client.change_open_profile(chat_id, OpenChatProfile.link(my_profile_link_id))
await client.change_open_profile(
    chat_id, OpenChatProfile.anonymous("봇 이름", existing_kakao_image_path)
)
```

`main()`은 해당 방에서 계정 기본 프로필을 사용하도록 전환합니다.
`link()`에는 자신이 사용하는 기존 오픈프로필의 링크 ID를 지정합니다.
방 ID, 방의 링크 ID, 사용할 프로필의 링크 ID는 서로 다른 값입니다.
`anonymous()`의 이미지 경로는 이미 카카오에 등록된 경로여야 합니다.
로컬 파일·전체 URL을 업로드하는 기능은 포함하지 않습니다. 닉네임은 로컬에서
1~100자의 출력 가능한 문자열로 제한하며, 서버가 더 엄격하게 제한할 수 있습니다.

## loopchange

```python
import asyncio
from kabot.loco import OpenChatProfile

stop = asyncio.Event()
task = asyncio.create_task(client.loopchange(
    chat_id,
    [OpenChatProfile.link(profile_a_id), OpenChatProfile.link(profile_b_id)],
    interval=60,
    max_changes=10,
    stop_event=stop,
))
# 다른 작업을 하다가 stop.set()으로 중지 가능
count = await task
```

- 첫 변경은 즉시 수행하고, 완료 후 `interval`초를 기다립니다. 최소 간격은 1초입니다.
- 순서는 A → B → A → B입니다. 닉네임이 서로 다른 익명 프로필 목록도 가능합니다.
- `max_changes`를 생략하면 중지할 때까지 반복합니다. 반환값은 서버 승인 횟수입니다.
- `stop_event.set()`은 다음 변경을 막고 대기 중이면 즉시 깨웁니다.
  이미 서버로 보낸 요청을 취소하거나 되돌리지는 않습니다.
- 작업 자체를 `task.cancel()`하면 취소 예외가 전달됩니다.
- 서버 거절·시간 초과·연결 오류가 나면 즉시 중단합니다. 자동 재시도는 없습니다.
- 중지해도 마지막으로 적용된 프로필은 유지됩니다. 기본 프로필로 자동 복원하지 않습니다.
- 봇과 함께 쓰면 기존 메시지 소비 루프를 유지하세요. 단독 실행 시에도 푸시 이벤트를
  소비해야 합니다. 아래 예제는 이를 처리하며 연결 종료 시 변경 루프도 중단합니다.

## 명령줄

```powershell
# 계정 연결 오픈링크 목록 (조회만)
kabot open-profile

# 지정 방에서 내 현재 참여 프로필 조회
kabot open-profile --chat-id ROOM_ID

# 기존 오픈프로필로 한 번 전환
kabot open-profile --chat-id ROOM_ID --kind link --profile-link-id PROFILE_ID

# 기본 카카오 프로필로 한 번 전환
kabot open-profile --chat-id ROOM_ID --kind main

# 기존 오픈프로필 두 개를 60초 간격으로 총 10회 순환
python examples/open_profile_loop.py --chat-id ROOM_ID --profile-link-id PROFILE_A --profile-link-id PROFILE_B --interval 60 --max-changes 10

# 같은 이미지로 닉네임을 순환. IMAGE_PATH는 실제 카카오 이미지 경로로 대체
python examples/open_profile_loop.py --chat-id ROOM_ID --nickname 이름1 --nickname 이름2 --profile-path IMAGE_PATH --interval 60
```

`ROOM_ID` 등의 표시는 실제 숫자 ID로 대체하세요. `--session`으로 세션 파일을 지정할 수
있으며 암호는 실행한 터미널에서 직접 입력합니다. 계정 비밀번호를 인자로 받지 않습니다.
단일 변경 후 현재 프로필 조회를 다시 실행해 반영 여부를 확인할 수 있습니다.

## 검증 범위와 근거

`CHATINFO`로 방의 오픈링크 ID를 조회한 뒤 `UPLINKPROF`를 한 번 보냅니다.
`MEMBER`로 자신의 참여 프로필을 조회하고 `SYNCLINK`로 계정 연결 링크를 조회합니다.
다른 방의 응답이나 유효하지 않은 ID는 변경 전에 거부합니다.
서버 상태 0은 요청 승인이며 앱 화면 반영을 보장하는 별도 검증은 아닙니다.
오픈프로필 전용 방 등 방 설정에 따라 변경이 거절될 수 있습니다.

프로토콜 근거는 MIT 라이선스의 [node-kakao 8512e469](https://github.com/storycraft/node-kakao/tree/8512e4699e2cd4c26516b80d38b57b2f85a6cc8a)이며,
`open-link-profile.ts`, `talk-open-channel-session.ts`, `talk-open-link-session.ts`를
참조했습니다. 현재 서버 호환성은 별도 실계정 확인이 필요합니다.
