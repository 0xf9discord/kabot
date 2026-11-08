"""Local, user-operated login/verification window. No browser or terminal automation."""

from __future__ import annotations

import asyncio
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Prompt:
    text: str
    secret: bool
    done: threading.Event = field(default_factory=threading.Event)
    answer: str | None = field(default=None, repr=False)


def run_window(
    session_path: str | Path,
    *,
    status_path: str | Path | None = None,
    mode: str = "verify",
    replace: bool = False,
    target_name: str | None = None,
    allow_open: bool = False,
):
    """All sensitive text stays inside this user-controlled process.

    The GUI calls the same workflow as the CLI, and writes only its redacted
    status file. No input values are included in application logs or arguments.
    """
    import tkinter as tk
    from tkinter import ttk

    from .auth import AndroidAuthError
    from .interactive import LoginStatus, interactive_login, verify_saved_session
    from .session import LocoStatusError
    from .storage import SessionStoreError

    if mode not in ("verify", "login", "bot-test"):
        raise ValueError("mode must be verify, login or bot-test")
    messages: queue.Queue = queue.Queue()
    closed = threading.Event()
    active: Prompt | None = None
    root = tk.Tk()
    root.title(
        ("Kabot · 오픈채팅 답장 테스트" if allow_open else "Kabot · 봇 답장 테스트")
        if mode == "bot-test"
        else "Kabot · 계정 재로그인"
        if mode == "login"
        else "Kabot · 카카오톡 연결 확인"
    )
    root.geometry("780x590")
    root.minsize(650, 480)
    root.configure(background="#f5f6f8")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Kabot 연결 확인", font=("Malgun Gothic", 18, "bold")).pack(anchor="w")
    ttk.Label(
        frame,
        text="입력한 암호는 이 컴퓨터에서만 처리되며 채팅에 전달되지 않습니다.",
        wraplength=650,
    ).pack(anchor="w", pady=(10, 16))
    information = tk.StringVar(
        value=(
            "기존 세션 파일 암호와 카카오 계정 정보를 직접 입력해 주세요."
            if mode == "login"
            else "저장된 세션으로 채팅 서버에 연결할 준비를 하고 있습니다."
        )
    )
    ttk.Label(frame, textvariable=information, wraplength=650).pack(anchor="w", pady=(0, 12))
    history_frame = ttk.Frame(frame)
    history_frame.pack(fill="both", expand=True, pady=(0, 12))
    history = tk.Text(
        history_frame, height=9, wrap="word", state="disabled", font=("Malgun Gothic", 10)
    )
    scroll = ttk.Scrollbar(history_frame, orient="vertical", command=history.yview)
    history.configure(yscrollcommand=scroll.set)
    history.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    label = tk.StringVar(value="잠시 기다려 주세요.")
    ttk.Label(frame, textvariable=label, wraplength=650).pack(anchor="w")
    entry = ttk.Entry(frame, show="●", font=("Malgun Gothic", 12))
    entry.pack(fill="x", pady=(8, 12))
    entry.configure(state="disabled")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    def submit(event=None):
        nonlocal active
        if active is None:
            return
        prompt = active
        active = None
        prompt.answer = entry.get()
        entry.delete(0, "end")
        entry.configure(state="disabled")
        confirm.configure(state="disabled")
        label.set("처리 중입니다.")
        prompt.done.set()

    confirm = ttk.Button(buttons, text="확인", command=submit, state="disabled")
    confirm.pack(side="left")
    ttk.Button(buttons, text="닫기", command=lambda: shutdown()).pack(side="right")
    entry.bind("<Return>", submit)

    def shutdown():
        closed.set()
        if active is not None:
            active.done.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", shutdown)

    def prompt(text, secret=False):
        request = Prompt(text, secret)
        messages.put(("prompt", request))
        while not request.done.wait(0.2):
            if closed.is_set():
                raise KeyboardInterrupt
        if request.answer is None or closed.is_set():
            raise KeyboardInterrupt
        answer = request.answer
        request.answer = None
        return answer

    def output(message):
        messages.put(("information", str(message)))

    def worker():
        try:
            if mode == "bot-test":
                from .live_test import run_reply_test

                result = asyncio.run(
                    run_reply_test(
                        session_path,
                        status_path=status_path,
                        input_fn=prompt,
                        secret_fn=lambda text: prompt(text, True),
                        print_fn=output,
                        target_name=target_name,
                        allow_open=allow_open,
                    )
                )
                if not result:
                    messages.put(("finished", "답장 테스트가 취소되었습니다."))
                    return
            elif mode == "verify":
                asyncio.run(
                    verify_saved_session(
                        session_path,
                        status_path=status_path,
                        secret_fn=lambda text: prompt(text, True),
                        print_fn=output,
                    )
                )
            else:
                result = asyncio.run(
                    interactive_login(
                        session_path,
                        status_path=status_path,
                        replace=replace,
                        input_fn=prompt,
                        secret_fn=lambda text: prompt(text, True),
                        print_fn=output,
                    )
                )
                if result is None:
                    messages.put(("finished", "로그인이 취소되었습니다."))
                    return
            messages.put(("finished", "연결 처리가 완료되었습니다."))
        except KeyboardInterrupt:
            LoginStatus(Path(status_path) if status_path else None).update("canceled")
        except Exception as error:
            from .live_test import ReplyTestWriteError

            if isinstance(error, SessionStoreError):
                message = "세션 파일을 열지 못했습니다. 암호 또는 파일 상태를 확인해 주세요."
            elif isinstance(error, AndroidAuthError):
                if error.phase == "login" and error.server_status in (12, 30):
                    message = (
                        f"서버가 로그인 정보를 거부했습니다 (코드 {error.server_status}). "
                        "카카오 계정 이메일과 비밀번호를 확인하고 다시 시도해 주세요."
                    )
                else:
                    message = (
                        f"계정 인증을 완료하지 못했습니다. 단계: {error.phase}, "
                        f"HTTP: {error.http_status}, 서버 코드: {error.server_status}"
                    )
            elif isinstance(error, LocoStatusError):
                if error.method == "LOGINLIST" and error.status == -950:
                    messages.put(
                        (
                            "expired",
                            "저장된 로그인 토큰이 만료되었거나 무효합니다. 다시 로그인해 주세요.",
                        )
                    )
                    return
                message = f"서버가 요청을 거부했습니다. 단계: {error.method}, 코드: {error.status}"
            elif isinstance(error, ReplyTestWriteError):
                message = "답장 전송을 한 번 시도했으나 완료 여부를 확인하지 못했습니다. 자동 재전송하지 않았습니다."
            else:
                message = f"연결을 완료하지 못했습니다. 오류 종류: {type(error).__name__}"
            messages.put(("failed", message))

    def poll():
        nonlocal active
        while True:
            try:
                kind, value = messages.get_nowait()
            except queue.Empty:
                break
            if kind == "prompt":
                active = value
                label.set(value.text)
                entry.configure(state="normal", show="●" if value.secret else "")
                confirm.configure(state="normal", text="확인", command=submit)
                entry.focus_set()
            elif kind == "information":
                information.set(value.splitlines()[0][:250] if "\n" in value else value[:400])
                history.configure(state="normal")
                history.insert("end", value + "\n")
                history.see("end")
                history.configure(state="disabled")
            else:
                information.set(value)
                label.set("진행 결과는 확인 창과 로컬 상태 파일에 표시됩니다.")
                entry.configure(state="disabled")
                if kind == "expired":
                    confirm.configure(state="normal", text="다시 로그인", command=restart_login)
                elif kind == "failed":
                    confirm.configure(state="normal", text="다시 시도", command=lambda: restart())
                else:
                    confirm.configure(state="disabled")
        if not closed.is_set():
            root.after(100, poll)

    root.after(100, poll)

    def restart():
        confirm.configure(state="disabled")
        information.set("다시 연결할 준비를 하고 있습니다.")
        threading.Thread(target=worker, daemon=True).start()

    def restart_login():
        nonlocal mode, replace
        mode, replace = "login", Path(session_path).exists()
        root.title("Kabot · 계정 재로그인")
        restart()

    root.after(200, lambda: threading.Thread(target=worker, daemon=True).start())
    root.lift()
    root.attributes("-topmost", True)
    root.after(1500, lambda: root.attributes("-topmost", False))
    root.mainloop()
