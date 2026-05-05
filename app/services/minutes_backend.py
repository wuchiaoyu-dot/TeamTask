from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.core.external_read_guard import mask_sensitive_resource_id, should_allow_external_read

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MinutesContent:
    minutes_token: str | None
    title: str
    meeting_start_time: str | None
    participants: list[str]
    transcript_text: str
    speaker_segments: list[dict[str, str]]
    summary_text: str
    todos_text: str
    source_url: str | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


class MinutesBackend:
    def get_minutes_content(self, minutes_token_or_url: str) -> MinutesContent:
        raise NotImplementedError


class MockMinutesBackend(MinutesBackend):
    def get_minutes_content(self, minutes_token_or_url: str) -> MinutesContent:
        token = _safe_token(minutes_token_or_url)
        logger.info("MockMinutesBackend get_minutes_content token_or_url=<redacted>")
        return MinutesContent(
            minutes_token=token,
            title="TeamTask Weekly Planning",
            meeting_start_time="2026-05-04T10:00:00+08:00",
            participants=["u_initiator", "u_alice", "u_bob", "u_cara"],
            transcript_text=(
                "u_initiator: We reviewed TeamTask progress.\n"
                "u_alice: I will finish the API checklist by 2026-06-01.\n"
                "u_bob: I can prepare the rollout notes by 2026-06-03.\n"
                "u_cara: I can prepare the rollout notes by 2026-06-03.\n"
                "u_initiator: We should also推进一下 dashboard work, owner TBD."
            ),
            speaker_segments=[
                {"speaker": "u_initiator", "text": "We reviewed TeamTask progress."},
                {"speaker": "u_alice", "text": "I will finish the API checklist by 2026-06-01."},
                {"speaker": "u_bob", "text": "I can prepare the rollout notes by 2026-06-03."},
                {"speaker": "u_cara", "text": "I can prepare the rollout notes by 2026-06-03."},
            ],
            summary_text="Discussed TeamTask delivery and rollout preparation.",
            todos_text=(
                "行动项:\n"
                "- u_alice 负责 API checklist，截止 2026-06-01。\n"
                "- u_bob, u_cara 负责 rollout notes，截止 2026-06-03。\n"
                "- 我们推进一下 dashboard work，负责人待定。"
            ),
            source_url=minutes_token_or_url if minutes_token_or_url.startswith("http") else None,
            raw_payload={"mock": True, "token": "<redacted>"},
        )


class LarkCliMinutesBackend(MinutesBackend):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_minutes_content(self, minutes_token_or_url: str) -> MinutesContent:
        logger.info(
            "LarkCliMinutesBackend get_minutes_content dry_run=%s real_read=%s token_or_url=%s",
            self.settings.minutes_dry_run or self.settings.lark_dry_run,
            should_allow_external_read(self.settings),
            mask_sensitive_resource_id(minutes_token_or_url),
        )
        if self.settings.minutes_dry_run or not should_allow_external_read(self.settings):
            mock = MockMinutesBackend().get_minutes_content(minutes_token_or_url)
            return MinutesContent(
                **{
                    **mock.__dict__,
                    "raw_payload": {
                        **mock.raw_payload,
                        "would_read": True,
                        "allowed": should_allow_external_read(self.settings),
                        "dry_run": True,
                    },
                }
            )

        command = [
            self.settings.lark_cli_path,
            "vc",
            "+minutes",
            "--minutes-token",
            minutes_token_or_url,
            "--as",
            "user" if self.settings.feishu_read_as_user else "bot",
        ]
        logger.info("lark-cli minutes command=%s", _redact_command(command))
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.settings.feishu_read_timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"lark-cli minutes failed: {completed.returncode} {_redact_text(completed.stderr)}")
        content = parse_lark_cli_minutes_output(completed.stdout)
        return MinutesContent(
            **{
                **content.__dict__,
                "minutes_token": _safe_token(minutes_token_or_url),
                "source_url": minutes_token_or_url if minutes_token_or_url.startswith("http") else content.source_url,
            }
        )


def create_minutes_backend(settings: Settings | None = None) -> MinutesBackend:
    settings = settings or get_settings()
    if settings.minutes_backend == "lark_cli" and not settings.feishu_mock:
        return LarkCliMinutesBackend(settings)
    return MockMinutesBackend()


def parse_lark_cli_minutes_output(raw_output: str | dict[str, Any]) -> MinutesContent:
    if isinstance(raw_output, dict):
        payload = raw_output
    else:
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            payload = {"transcript_text": raw_output}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw_segments = data.get("speaker_segments") or data.get("segments")
    if raw_segments is None and isinstance(data.get("transcript"), dict):
        raw_segments = data["transcript"].get("segments")
    speaker_segments = normalize_minutes_segments(raw_segments or [])
    transcript_text = data.get("transcript_text")
    if not transcript_text and isinstance(data.get("transcript"), str):
        transcript_text = data.get("transcript")
    if not transcript_text and speaker_segments:
        transcript_text = "\n".join(f"{item['speaker']}: {item['text']}" for item in speaker_segments)
    return MinutesContent(
        minutes_token=data.get("minutes_token") or data.get("token"),
        title=str(data.get("title") or data.get("meeting_title") or "Feishu Minutes"),
        meeting_start_time=data.get("meeting_start_time") or data.get("start_time"),
        participants=list(data.get("participants") or data.get("attendees") or []),
        transcript_text=str(transcript_text or ""),
        speaker_segments=speaker_segments,
        summary_text=str(data.get("summary_text") or data.get("summary") or ""),
        todos_text=str(data.get("todos_text") or data.get("todos") or data.get("action_items") or ""),
        source_url=data.get("source_url") or data.get("url"),
        raw_payload=payload,
    )


def normalize_minutes_segments(raw_segments: list[Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for segment in raw_segments:
        if isinstance(segment, str):
            speaker, text = _split_speaker_line(segment)
        else:
            speaker = str(segment.get("speaker") or segment.get("speaker_name") or segment.get("user_id") or "")
            text = str(segment.get("text") or segment.get("content") or "")
        if text:
            normalized.append({"speaker": speaker or "unknown", "text": text})
    return normalized


def _safe_token(value: str) -> str | None:
    if value.startswith("http"):
        return None
    return value


def _split_speaker_line(value: str) -> tuple[str, str]:
    match = re.match(r"([^:：]{1,80})[:：]\s*(.*)", value)
    if not match:
        return "unknown", value
    return match.group(1).strip(), match.group(2).strip()


def _redact_command(command: list[str]) -> list[str]:
    redacted = []
    redact_next = False
    for item in command:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
        else:
            redacted.append(_redact_text(item))
            if "token" in item.lower() or "secret" in item.lower():
                redact_next = True
    return redacted


def _redact_text(text: str) -> str:
    redacted = text
    for name in ("FEISHU_APP_SECRET", "FEISHU_ACCESS_TOKEN", "LARK_ACCESS_TOKEN"):
        value = os.getenv(name)
        if value:
            redacted = redacted.replace(value, "<redacted>")
    redacted = re.sub(r"(minutes[-_]?token[=:/\s]+)[^\s/&]+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(/minutes/)[A-Za-z0-9._-]+", r"\1<redacted>", redacted)
    return redacted
