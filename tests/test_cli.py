import os
import subprocess
import sys
from pathlib import Path


def test_scaffold_local_chat_and_no_overwrite(tmp_path):
    def cli(*args, stdin=None):
        return subprocess.run(
            [sys.executable, "-m", "kabot", *args],
            cwd=tmp_path,
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    assert cli("init").returncode == 0
    original = (tmp_path / "mybot.py").read_bytes()
    assert cli("init").returncode != 0
    assert (tmp_path / "mybot.py").read_bytes() == original
    result = cli("chat", "mybot:bot", stdin="/안녕 테스터\n/방문\n/종료\n")
    assert result.returncode == 0, result.stderr
    assert "테스터" in result.stdout
    assert "1번째" in result.stdout
    assert Path(tmp_path / "bot.sqlite3").exists()
    assert "not implemented" in cli("doctor").stdout


def test_gui_passes_explicit_open_chat_and_target_options(monkeypatch):
    import pytest

    pytest.importorskip("bson")
    pytest.importorskip("cryptography")
    from kabot import cli
    from kabot.loco import gui

    observed = {}

    def window(session, **options):
        observed.update(session=session, **options)

    monkeypatch.setattr(gui, "run_window", window)
    monkeypatch.setattr(
        sys,
        "argv",
        ["kabot", "gui", "--mode", "bot-test", "--target-room", "2026testkakao", "--allow-open"],
    )
    cli.main()
    assert observed["allow_open"] is True
    assert observed["target_name"] == "2026testkakao"
    assert observed["mode"] == "bot-test"


def test_cli_login_does_not_receive_room_selection_arguments(monkeypatch):
    import pytest

    pytest.importorskip("bson")
    pytest.importorskip("cryptography")
    from kabot import cli
    from kabot.loco import interactive

    observed = {}

    async def login(session, **options):
        observed.update(session=session, **options)

    monkeypatch.setattr(interactive, "interactive_login", login)
    monkeypatch.setattr(sys, "argv", ["kabot", "login", "--session", "fake-session.kabot"])
    cli.main()
    assert "target_name" not in observed and "allow_open" not in observed
    assert observed["session"] == "fake-session.kabot"


def test_cli_profile_explicit_switch_and_read_only_default(monkeypatch):
    import pytest

    pytest.importorskip("bson")
    pytest.importorskip("cryptography")
    from kabot import cli
    from kabot.loco import interactive

    observed = []

    async def manage(session, **options):
        observed.append(options)

    monkeypatch.setattr(interactive, "manage_open_profile", manage)
    monkeypatch.setattr(sys, "argv", ["kabot", "open-profile"])
    cli.main()
    assert observed[-1] == {"chat_id": None, "profile": None}
    monkeypatch.setattr(
        sys,
        "argv",
        ["kabot", "open-profile", "--chat-id", "7", "--kind", "link", "--profile-link-id", "99"],
    )
    cli.main()
    assert observed[-1]["chat_id"] == 7
    assert observed[-1]["profile"].to_body() == {"ptp": 16, "pli": 99}


def test_cli_profile_invalid_selection_never_unlocks(monkeypatch):
    import pytest

    pytest.importorskip("bson")
    pytest.importorskip("cryptography")
    from kabot import cli
    from kabot.loco import interactive

    async def unexpected(*args, **options):
        pytest.fail("Invalid arguments must be rejected before unlocking or connecting")

    monkeypatch.setattr(interactive, "manage_open_profile", unexpected)
    monkeypatch.setattr(sys, "argv", ["kabot", "open-profile", "--kind", "main"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
