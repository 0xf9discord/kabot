"""Locally unlock a session and rotate the selected room's participant profile.

Example: python examples/open_profile_loop.py --chat-id ROOM_ID
         --profile-link-id PROFILE_A --profile-link-id PROFILE_B --interval 60
Stop with Ctrl+C. No profile is restored automatically on exit.
"""

import argparse
import asyncio

from kabot.loco import OpenChatProfile, PersonalClient
from kabot.loco.interactive import unlock_session


async def run(args, profiles):
    credentials = await unlock_session(args.session)
    async with PersonalClient(credentials) as client:
        await client.connect()

        async def consume_events():
            # Drain push notifications, and surface KICKOUT/CHANGESVR failures.
            async for _ in client.messages():
                pass

        async with asyncio.TaskGroup() as tasks:
            consumer = tasks.create_task(consume_events())
            try:
                count = await client.loopchange(
                    args.chat_id,
                    profiles,
                    interval=args.interval,
                    max_changes=args.max_changes,
                )
                print(f"완료: 서버 승인 {count}회")
            finally:
                consumer.cancel()


def main():
    parser = argparse.ArgumentParser(description="오픈채팅 프로필 순환 변경 (Ctrl+C로 중지)")
    parser.add_argument("--session", default="personal-session.kabot")
    parser.add_argument("--chat-id", type=int, required=True)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--profile-link-id", type=int, action="append")
    choices.add_argument("--nickname", action="append")
    parser.add_argument("--profile-path", help="닉네임 모드에서 사용할 기존 카카오 이미지 경로")
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--max-changes", type=int)
    args = parser.parse_args()
    if args.nickname:
        if not args.profile_path:
            parser.error("--nickname 사용 시 --profile-path가 필요합니다")
        profiles = [OpenChatProfile.anonymous(name, args.profile_path) for name in args.nickname]
    else:
        if args.profile_path:
            parser.error("--profile-path는 --nickname과 함께 사용하세요")
        profiles = [OpenChatProfile.link(identity) for identity in args.profile_link_id]
    try:
        asyncio.run(run(args, profiles))
    except KeyboardInterrupt:
        print("중지했습니다. 마지막 적용 프로필은 유지됩니다.")


if __name__ == "__main__":
    main()
