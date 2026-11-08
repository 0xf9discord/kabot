"""Transport-independent command routing for Kakao channel skills."""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Pattern

from .models import Response, SkillRequest, text
from .state import SQLiteStore


@dataclass
class Context:
    request: SkillRequest
    store: SQLiteStore | None = None
    args: str = ""
    match: re.Match | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def user_id(self) -> str:
        return self.request.user_request.user.id

    @property
    def scope(self) -> str:
        # Bot user keys are scoped to each bot, not global Kakao account IDs.
        return f"{self.request.bot.get('id', 'local')}:{self.user_id}"

    @property
    def message(self) -> str:
        return self.request.user_request.utterance

    @property
    def params(self) -> dict[str, Any]:
        return self.request.action.params


@dataclass
class Route:
    kind: str
    value: str | Pattern
    handler: Callable
    deferred: bool = False


async def invoke(function: Callable, *args: Any) -> Any:
    if inspect.iscoroutinefunction(function):
        return await function(*args)
    result = await asyncio.to_thread(function, *args)
    return await result if inspect.isawaitable(result) else result


class Bot:
    def __init__(
        self,
        *,
        prefix: str = "/",
        store: SQLiteStore | None = None,
        fallback: str = "알 수 없는 명령입니다. /도움말을 입력해 주세요.",
    ):
        self.prefix, self.store, self.fallback = prefix, store, fallback
        self.routes: list[Route] = []
        self.before_hooks: list[Callable] = []

    def _register(self, kind: str, value: str | Pattern, *, deferred: bool = False):
        def decorator(function: Callable):
            self.routes.append(Route(kind, value, function, deferred))
            return function

        return decorator

    def command(self, name: str, *, deferred: bool = False):
        if not name or any(c.isspace() for c in name):
            raise ValueError("command name must be a non-empty single word")
        return self._register("command", name, deferred=deferred)

    def hears(self, pattern: str, *, deferred: bool = False):
        return self._register("regex", re.compile(pattern), deferred=deferred)

    def action(self, name: str, *, deferred: bool = False):
        return self._register("action", name, deferred=deferred)

    def on_message(self, *, deferred: bool = False):
        return self._register("all", "", deferred=deferred)

    def before(self, function: Callable):
        """Return a response to stop routing, or None to continue."""
        self.before_hooks.append(function)
        return function

    def resolve(self, request: SkillRequest) -> tuple[Route | None, Context]:
        ctx = Context(request, self.store)
        message = ctx.message.strip()
        for route in self.routes:
            if route.kind == "command":
                parts = message.split(maxsplit=1)
                if not parts or parts[0] != self.prefix + route.value:
                    continue
                ctx.args = parts[1] if len(parts) > 1 else ""
            elif route.kind == "regex":
                ctx.match = route.value.search(message)
                if ctx.match is None:
                    continue
            elif route.kind == "action" and request.action.name != route.value:
                continue
            return route, ctx
        return None, ctx

    async def execute(self, route: Route | None, ctx: Context) -> Response:
        for hook in self.before_hooks:
            result = await invoke(hook, ctx)
            if result is not None:
                return self._response(result)
        return self._response(await invoke(route.handler, ctx) if route else self.fallback)

    @staticmethod
    def _response(value: Response | str) -> Response:
        result = text(value) if isinstance(value, str) else value
        if not isinstance(result, Response):
            raise TypeError("A bot handler must return a string or kabot.Response")
        result.to_dict()
        return result

    async def handle(self, payload: dict | SkillRequest) -> Response:
        """Local/test dispatch. Does not send messages or enforce HTTP deadlines."""
        request = (
            payload if isinstance(payload, SkillRequest) else SkillRequest.model_validate(payload)
        )
        return await self.execute(*self.resolve(request))
