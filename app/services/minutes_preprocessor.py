from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.services.minutes_backend import MinutesContent


@dataclass(frozen=True)
class NormalizedMeetingText:
    title: str
    participants: list[str]
    full_text: str
    action_sections: list[str]
    evidence_blocks: list[str]
    source_link: str | None
    truncated: bool = False


def normalize_minutes_content(
    minutes_content: MinutesContent,
    settings: Settings | None = None,
) -> NormalizedMeetingText:
    settings = settings or get_settings()
    speaker_text = "\n".join(
        f"{segment.get('speaker', 'unknown')}: {segment.get('text', '')}"
        for segment in minutes_content.speaker_segments
    )
    parts = [
        f"Title: {minutes_content.title}",
        f"Participants: {', '.join(minutes_content.participants)}",
        f"Summary:\n{minutes_content.summary_text}",
        f"Todos:\n{minutes_content.todos_text}",
        f"Transcript:\n{speaker_text or minutes_content.transcript_text}",
    ]
    full_text = "\n\n".join(part for part in parts if part.strip())
    action_sections = _extract_action_sections(full_text, settings.minutes_task_section_hints)
    evidence_blocks = action_sections[:]
    if not evidence_blocks and minutes_content.speaker_segments:
        evidence_blocks = [
            f"{segment.get('speaker', 'unknown')}: {segment.get('text', '')}"
            for segment in minutes_content.speaker_segments[:5]
        ]

    truncated = False
    if len(full_text) > settings.minutes_text_max_chars:
        full_text = full_text[: settings.minutes_text_max_chars]
        truncated = True

    return NormalizedMeetingText(
        title=minutes_content.title,
        participants=minutes_content.participants,
        full_text=full_text,
        action_sections=action_sections,
        evidence_blocks=evidence_blocks,
        source_link=minutes_content.source_url,
        truncated=truncated,
    )


def _extract_action_sections(full_text: str, hints: tuple[str, ...]) -> list[str]:
    lines = [line.strip() for line in full_text.splitlines()]
    sections: list[str] = []
    for index, line in enumerate(lines):
        if not line:
            continue
        if any(hint.lower() in line.lower() for hint in hints):
            start = max(0, index - 1)
            end = min(len(lines), index + 5)
            section = "\n".join(item for item in lines[start:end] if item)
            if section and section not in sections:
                sections.append(section)
    return sections
