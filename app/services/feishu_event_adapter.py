from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from app.services.minutes_link_parser import extract_minutes_url, is_minutes_link


@dataclass(frozen=True)
class SourceEventCreate:
    external_event_id: str
    source_type: str
    chat_id: str | None
    message_id: str | None
    trigger_user_id: str
    text: str
    source_link: str | None
    raw_payload: dict[str, Any]
    participant_user_ids: list[str]


def adapt_feishu_event(payload: dict[str, Any]) -> SourceEventCreate:
    header = payload.get("header") or {}
    event = payload.get("event") or payload
    event_type = header.get("event_type") or payload.get("event_type") or payload.get("type")

    if event_type not in {"im.message.receive_v1", "message", "im.message.receive"}:
        raise ValueError(f"Unsupported Feishu event type: {event_type}")

    message = event.get("message") or {}
    sender = event.get("sender") or {}
    text = _extract_message_text(message)
    source_link = extract_minutes_url(text) or _extract_first_url(text, message)
    source_type = "meeting_minutes" if is_minutes_link(text) else "group_message"

    return SourceEventCreate(
        external_event_id=str(header.get("event_id") or message.get("message_id") or payload.get("event_id") or ""),
        source_type=source_type,
        chat_id=message.get("chat_id"),
        message_id=message.get("message_id"),
        trigger_user_id=_extract_user_id(sender),
        text=text,
        source_link=source_link,
        raw_payload=payload,
        participant_user_ids=_extract_participant_user_ids(message, sender, text),
    )


def _extract_user_id(sender: dict[str, Any]) -> str:
    sender_id = sender.get("sender_id") or sender.get("user_id") or {}
    if isinstance(sender_id, dict):
        return sender_id.get("user_id") or sender_id.get("open_id") or sender_id.get("union_id") or "unknown_user"
    if isinstance(sender_id, str):
        return sender_id
    return "unknown_user"


def _extract_message_text(message: dict[str, Any]) -> str:
    content = message.get("content") or ""
    message_type = message.get("message_type") or message.get("msg_type")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
    else:
        parsed = content

    if isinstance(parsed, dict):
        if isinstance(parsed.get("text"), str):
            return parsed["text"]
        if message_type == "post" or "content" in parsed:
            text = _flatten_post_text(parsed.get("content"))
            if text:
                return text
        if isinstance(parsed.get("title"), str):
            return parsed["title"]
    return str(parsed)


def _flatten_post_text(value: Any) -> str:
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text") or node.get("href") or node.get("url")
            if isinstance(text, str):
                parts.append(text)
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return " ".join(part for part in parts if part).strip()


def _extract_first_url(text: str, message: dict[str, Any]) -> str | None:
    match = re.search(r"https?://\S+", text)
    if match:
        return match.group(0).rstrip(").,，。\"'")

    content = message.get("content") or ""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, default=str)
    match = re.search(r"https?://\S+", content)
    return match.group(0).rstrip(").,，。\"'") if match else None


def _extract_participant_user_ids(message: dict[str, Any], sender: dict[str, Any], text: str) -> list[str]:
    users: list[str] = []
    sender_id = _extract_user_id(sender)
    if sender_id != "unknown_user":
        users.append(sender_id)

    mentions = message.get("mentions") or []
    for index, mention in enumerate(mentions):
        user_id = _extract_mention_user_id(mention)
        if _should_ignore_mention(user_id, mention, index, mentions, text):
            continue
        if user_id and user_id not in users:
            users.append(user_id)
    return users


def _extract_mention_user_id(mention: dict[str, Any]) -> str | None:
    key = mention.get("id") or mention.get("user_id") or {}
    if isinstance(key, dict):
        return key.get("user_id") or key.get("open_id") or key.get("union_id")
    return key if key else None


def _should_ignore_mention(
    user_id: str | None,
    mention: dict[str, Any],
    index: int,
    mentions: list[dict[str, Any]],
    text: str,
) -> bool:
    if not user_id:
        return False
    if user_id in _ignored_mention_user_ids():
        return True
    return _looks_like_leading_bot_trigger(mention, index, mentions, text)


def _ignored_mention_user_ids() -> set[str]:
    return {
        value
        for env_name in ("FEISHU_BOT_OPEN_IDS", "FEISHU_BOT_USER_IDS", "FEISHU_IGNORE_MENTION_USER_IDS")
        for value in _env_csv(env_name)
    }


def _looks_like_leading_bot_trigger(
    mention: dict[str, Any],
    index: int,
    mentions: list[dict[str, Any]],
    text: str,
) -> bool:
    if index != 0 or len(mentions) < 2:
        return False
    key = mention.get("key")
    return isinstance(key, str) and bool(key) and text.lstrip().startswith(key)


def _env_csv(name: str) -> tuple[str, ...]:
    raw_value = os.getenv(name, "")
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())
