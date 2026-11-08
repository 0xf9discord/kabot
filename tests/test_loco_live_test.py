import asyncio
import json

import pytest

from kabot.loco.client import Credentials, Message
from kabot.loco.live_test import TEST_REPLY, ReplyTestWriteError, run_reply_test


class FakeClient:
    def __init__(self, credentials, *, rows=None, messages=(), send_error=None):
        self.credentials = credentials
        self.rows = (
            rows
            if rows is not None
            else [
                {"c": 555, "t": "MultiChat", "s": 100, "chatInfo": {"name": "private-room-title"}}
            ]
        )
        self.incoming = messages
        self.send_error = send_error
        self.sent = []
        self.closed = False
        self.stream_started = False
        self.list_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def connect(self):
        return {"chatDatas": [{"c": 99999, "name": "seed-only-room"}]}

    async def list_chats(self, *, resolve_names=True, max_pages=10):
        self.list_calls.append((resolve_names, max_pages))
        return self.rows

    async def messages(self):
        self.stream_started = True
        for message in self.incoming:
            yield message
        await asyncio.Event().wait()

    async def send_text(self, chat_id, message):
        self.sent.append((chat_id, message))
        if self.send_error:
            raise self.send_error
        return {"status": 0}


def setup_fakes(monkeypatch, *, rows=None, messages=(), send_error=None):
    credentials = Credentials(
        123, "dummy-secret-token", "dummy-private-device", "26.8.2", profile="android"
    )
    secret_calls, unlock_calls, output = [], [], []

    def secret(prompt):
        secret_calls.append(prompt)
        return "dummy-vault-passphrase"

    async def unlock(path, *, secret_fn):
        unlock_calls.append(path)
        secret_fn("vault only")
        return credentials

    monkeypatch.setattr("kabot.loco.live_test.unlock_session", unlock)
    client = FakeClient(credentials, rows=rows, messages=messages, send_error=send_error)
    return client, secret, secret_calls, unlock_calls, output


@pytest.mark.parametrize("approval", ["q", "", "yes", " START ", "START extra"])
def test_cancel_without_exact_start_never_sends_or_starts_stream(tmp_path, monkeypatch, approval):
    client, secret, secret_calls, unlock_calls, output = setup_fakes(monkeypatch)
    answers = iter(["1", approval])
    status = tmp_path / "status.json"
    result = asyncio.run(
        run_reply_test(
            "never-read-real-vault",
            status_path=status,
            input_fn=lambda _: next(answers),
            secret_fn=secret,
            print_fn=output.append,
            client_factory=lambda _: client,
        )
    )
    assert result == 0 and client.sent == [] and not client.stream_started
    assert client.closed
    assert len(secret_calls) == len(unlock_calls) == 1
    record = json.loads(status.read_text())
    assert record["phase"] == "canceled" and record["authenticated"] is True
    assert record["send_attempts"] == record["replies_sent"] == 0
    for private in (
        "private-room-title",
        "555",
        "dummy-secret-token",
        "dummy-vault-passphrase",
        TEST_REPLY,
    ):
        assert private not in status.read_text()
    assert any(TEST_REPLY in line for line in output)


def test_select_cancel_never_asks_start_or_sends(tmp_path, monkeypatch):
    client, secret, _, _, output = setup_fakes(monkeypatch)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "q"

    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                input_fn=answer,
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
            )
        )
        == 0
    )
    assert len(prompts) == 1
    assert client.closed and client.sent == []


def test_server_metadata_listing_used_and_target_never_selected_automatically(
    tmp_path, monkeypatch
):
    rows = [{"c": 555, "t": "MultiChat", "s": 100, "chatInfo": {"name": "2026testkakao"}}]
    client, secret, _, _, output = setup_fakes(monkeypatch, rows=rows)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return "q"

    status = tmp_path / "status.json"
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=answer,
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                target_name="2026testkakao",
            )
        )
        == 0
    )
    assert client.list_calls == [(True, 10)]
    assert len(prompts) == 1 and client.sent == [] and not client.stream_started
    assert any("2026testkakao" in line for line in output)
    assert not any("seed-only-room" in line for line in output)
    record = json.loads(status.read_text())
    assert record["target_match_count"] == record["supported_target_match_count"] == 1
    assert "2026testkakao" not in status.read_text()


@pytest.mark.parametrize("include_supported", [False, True])
def test_target_found_only_in_unsupported_room_explains_kind_locally(
    tmp_path, monkeypatch, include_supported
):
    rows = [{"c": 98765, "t": "MemoChat", "name": "2026testkakao"}]
    if include_supported:
        rows.append({"c": 555, "t": "MultiChat", "name": "other-supported-room", "s": 100})
    client, secret, _, _, output = setup_fakes(monkeypatch, rows=rows)
    status = tmp_path / "status.json"
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: "q",
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                target_name="2026testkakao",
            )
        )
        == 0
    )
    assert any("지원하지 않는 유형" in line and "MemoChat" in line for line in output)
    assert not client.sent and not client.stream_started and client.closed
    record = json.loads(status.read_text())
    assert record["target_match_count"] == 1 and record["supported_target_match_count"] == 0
    for sensitive in ("2026testkakao", "98765", "MemoChat", "other-supported-room"):
        assert sensitive not in status.read_text()


def test_missing_target_explains_membership_and_device_alias_without_selecting(
    tmp_path, monkeypatch
):
    client, secret, _, _, output = setup_fakes(monkeypatch)
    status = tmp_path / "status.json"
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: "q",
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                target_name="not-shared-alias",
            )
        )
        == 0
    )
    assert any("참여 여부" in line and "별명" in line for line in output)
    record = json.loads(status.read_text())
    assert record["target_match_count"] == record["supported_target_match_count"] == 0
    assert not client.sent and not client.stream_started


def test_filters_old_own_other_room_nontext_and_duplicates_then_replies_once(tmp_path, monkeypatch):
    incoming = [
        Message(555, 100, 777, 1, "/핑"),  # snapshot baseline
        Message(555, 101, 123, 1, "/핑"),  # self
        Message(555, 102, 0, 1, "/핑"),  # system event
        Message(999, 102, 777, 1, "/핑"),  # another room
        Message(555, 103, 777, 2, "/핑"),  # non-text
        Message(555, 104, 777, 1, " /핑"),  # command must be exact
        Message(555, 104, 777, 1, "/핑"),  # duplicate log ID
        Message(555, 105, 777, 1, "/핑"),
        Message(555, 105, 777, 1, "/핑"),
        Message(555, 106, 777, 1, "/핑"),
    ]
    client, secret, calls, _, output = setup_fakes(monkeypatch, messages=incoming)
    answers = iter(["1", "start"])
    status = tmp_path / "status.json"
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: next(answers),
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
            )
        )
        == 1
    )
    assert client.sent == [(555, TEST_REPLY)] and client.closed and len(calls) == 1
    record = json.loads(status.read_text())
    assert (
        record["phase"] == "reply_sent" and record["replies_sent"] == record["send_attempts"] == 1
    )
    assert record["authenticated"] is True


def test_room_selection_skips_unsupported_and_sanitizes_local_names(tmp_path, monkeypatch):
    rows = [
        {"c": 1, "t": "MemoChat"},
        {"c": 2, "type": "OpenChat"},
        {"c": 3, "t": "SecretDirectChat"},
        {"c": 4, "t": "OM"},
        {"c": 5, "t": "OD"},
        {"c": True},
        {"c": -1},
        {"chatId": 555, "t": "MultiChat", "s": 100, "k": ["team\n", "\x1b[31mmate"]},
    ]
    client, secret, _, _, output = setup_fakes(
        monkeypatch, rows=rows, messages=[Message(555, 101, 777, 1, "/핑")]
    )
    answers = iter(["1", "START"])
    status = tmp_path / "status.json"
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: next(answers),
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
            )
        )
        == 1
    )
    assert client.sent == [(555, TEST_REPLY)]
    assert not any("\x1b" in line or "\n" in line for line in output)
    assert json.loads(status.read_text())["supported_chat_count"] == 1


def test_wait_timeout_is_bounded_no_write(tmp_path, monkeypatch):
    client, secret, _, _, output = setup_fakes(monkeypatch)
    answers = iter(["1", "START"])
    status = tmp_path / "status.json"
    with pytest.raises(TimeoutError):
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: next(answers),
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                timeout=0.01,
            )
        )
    record = json.loads(status.read_text())
    assert record["phase"] == "test_timeout"
    assert record["replies_sent"] == record["send_attempts"] == 0
    assert client.closed and not client.sent


def test_uncertain_write_error_is_typed_redacted_and_never_retried(tmp_path, monkeypatch):
    client, secret, _, _, output = setup_fakes(
        monkeypatch,
        messages=[Message(555, 101, 777, 1, "/핑")],
        send_error=RuntimeError("raw secret message should not leak"),
    )
    answers = iter(["1", "START"])
    status = tmp_path / "status.json"
    with pytest.raises(ReplyTestWriteError) as caught:
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: next(answers),
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
            )
        )
    assert "raw secret" not in str(caught.value)
    record = json.loads(status.read_text())
    assert record["phase"] == "reply_uncertain" and record["send_attempts"] == 1
    assert record["replies_sent"] == 0 and len(client.sent) == 1 and client.closed
    assert "raw secret" not in status.read_text()


@pytest.mark.parametrize("kind", ["OM", "OD", "OpenMultiChat"])
def test_explicit_open_flag_lists_target_and_still_requires_start(tmp_path, monkeypatch, kind):
    rows = [{"c": 555, "t": kind, "s": 100, "chatInfo": {"name": "2026testkakao"}}]
    client, secret, _, _, output = setup_fakes(monkeypatch, rows=rows)
    answers = iter(["1", "q"])
    status = tmp_path / "status.json"
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                status_path=status,
                input_fn=lambda _: next(answers),
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                target_name="2026testkakao",
                allow_open=True,
            )
        )
        == 0
    )
    assert client.list_calls == [(True, 10)]
    assert any("[오픈채팅]" in line and "2026testkakao" in line for line in output)
    assert not any("지원하지 않는 유형" in line for line in output)
    assert not client.sent and not client.stream_started
    record = json.loads(status.read_text())
    assert record["target_match_count"] == record["supported_target_match_count"] == 1
    assert record["send_attempts"] == 0


def test_joined_open_room_can_reply_once_after_explicit_flag_and_start(tmp_path, monkeypatch):
    rows = [{"c": 555, "t": "OM", "s": 100, "chatInfo": {"name": "2026testkakao"}}]
    client, secret, _, _, output = setup_fakes(
        monkeypatch, rows=rows, messages=[Message(555, 101, 777, 1, "/핑")]
    )
    answers = iter(["1", "START"])
    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                input_fn=lambda _: next(answers),
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                target_name="2026testkakao",
                allow_open=True,
            )
        )
        == 1
    )
    assert client.sent == [(555, TEST_REPLY)] and client.closed


@pytest.mark.parametrize("kind", ["MemoChat", "SecretChat"])
def test_open_flag_never_enables_memo_or_secret_rooms(tmp_path, monkeypatch, kind):
    client, secret, _, _, output = setup_fakes(
        monkeypatch, rows=[{"c": 555, "t": kind, "name": "excluded-target"}]
    )

    def forbidden_input(prompt):
        raise AssertionError("No selectable rooms means no approval prompt")

    assert (
        asyncio.run(
            run_reply_test(
                "dummy",
                input_fn=forbidden_input,
                secret_fn=secret,
                print_fn=output.append,
                client_factory=lambda _: client,
                target_name="excluded-target",
                allow_open=True,
            )
        )
        == 0
    )
    assert any("지원하지 않는 유형" in line and kind in line for line in output)
    assert not client.sent and not client.stream_started and client.closed
