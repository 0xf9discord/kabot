"""Validated Kakao skill requests and response builders."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    type: str = "botUserKey"
    properties: dict[str, Any] = Field(default_factory=dict)


class UserRequest(BaseModel):
    utterance: str = Field(max_length=20000)
    user: User
    lang: str = "ko"
    timezone: str = "Asia/Seoul"
    callback_url: str | None = Field(default=None, alias="callbackUrl", repr=False)


class Action(BaseModel):
    name: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    detail_params: dict[str, Any] = Field(default_factory=dict, alias="detailParams")
    client_extra: dict[str, Any] | None = Field(default=None, alias="clientExtra")


class SkillRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_request: UserRequest = Field(alias="userRequest")
    bot: dict[str, Any] = Field(default_factory=dict)
    action: Action = Field(default_factory=Action)
    contexts: list[dict[str, Any]] = Field(default_factory=list)


def _string(value: str, maximum: int, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must contain 1..{maximum} characters")
    return value


def _url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username:
        raise ValueError("A complete HTTP(S) URL without credentials is required")
    return value


def message_button(label: str, message: str) -> dict:
    return {
        "action": "message",
        "label": _string(label, 14, "label"),
        "messageText": _string(message, 1000, "message"),
    }


def link_button(label: str, url: str) -> dict:
    return {"action": "webLink", "label": _string(label, 14, "label"), "webLinkUrl": _url(url)}


def quick_reply(label: str, message: str) -> dict:
    return {
        "action": "message",
        "label": _string(label, 14, "label"),
        "messageText": _string(message, 1000, "message"),
    }


@dataclass
class Response:
    outputs: list[dict[str, Any]]
    quick_replies: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        if not 1 <= len(self.outputs) <= 3:
            raise ValueError("Kakao allows 1..3 outputs per response")
        if len(self.quick_replies) > 10:
            raise ValueError("Kakao allows at most 10 quick replies")
        template: dict[str, Any] = {"outputs": self.outputs}
        if self.quick_replies:
            template["quickReplies"] = self.quick_replies
        result = {"version": "2.0", "template": template}
        if self.data:
            result["data"] = self.data
        return deepcopy(result)

    def with_quick_replies(self, *replies: dict) -> Response:
        result = Response(deepcopy(self.outputs), list(deepcopy(replies)), deepcopy(self.data))
        result.to_dict()
        return result


def text(message: str) -> Response:
    """Split long text into at most three 1000-character bubbles; never truncate."""
    _string(message, 3000, "message")
    return Response(
        [{"simpleText": {"text": message[i : i + 1000]}} for i in range(0, len(message), 1000)]
    )


def image(url: str, alt: str = "이미지") -> Response:
    return Response([{"simpleImage": {"imageUrl": _url(url), "altText": _string(alt, 50, "alt")}}])


def card(
    title: str, description: str, image_url: str, *, buttons: list[dict] | None = None
) -> Response:
    if buttons is not None and len(buttons) > 3:
        raise ValueError("A vertical card supports at most 3 buttons")
    value = {
        "title": _string(title, 50, "title"),
        "description": _string(description, 230, "description"),
        "thumbnail": {"imageUrl": _url(image_url)},
        "buttonLayout": "vertical",
    }
    if buttons:
        value["buttons"] = deepcopy(buttons)
    return Response([{"basicCard": value}])
