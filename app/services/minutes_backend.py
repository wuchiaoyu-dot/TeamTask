from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings

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
            "LarkCliMinutesBackend get_minutes_content dry_run=%s token_or_url=<redacted>",
            self.settings.minutes_dry_run,
        )
        if self.settings.minutes_dry_run:
            return MockMinutesBackend().get_minutes_content(minutes_token_or_url)

        command = [
            self.settings.lark_cli_path,
            "vc",
            "+minutes",
            "--minutes-token",
            minutes_token_or_url,
            "--as",
            "user",
        ]
        logger.info("lark-cli minutes command=%s", _redact_command(command))
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            raise RuntimeError(f"lark-cli minutes failed: {completed.returncode} {_redact_text(completed.stderr)}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {"transcript_text": completed.stdout}
        return MinutesContent(
            minutes_token=_safe_token(minutes_token_or_url),
            title=str(payload.get("title") or "Feishu Minutes"),
            meeting_start_time=payload.get("meeting_start_time"),
            participants=list(payload.get("participants") or []),
            transcript_text=str(payload.get("transcript_text") or payload.get("transcript") or ""),
            speaker_segments=list(payload.get("speaker_segments") or []),
            summary_text=str(payload.get("summary_text") or payload.get("summary") or ""),
            todos_text=str(payload.get("todos_text") or payload.get("todos") or ""),
            source_url=minutes_token_or_url if minutes_token_or_url.startswith("http") else None,
            raw_payload=payload,
        )


def create_minutes_backend(settings: Settings | None = None) -> MinutesBackend:
    settings = settings or get_settings()
    if settings.minutes_backend == "lark_cli" and not settings.feishu_mock:
        return LarkCliMinutesBackend(settings)
    return MockMinutesBackend()


def _safe_token(value: str) -> str | None:
    if value.startswith("http"):
        return None
    return value


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
    return redacted
