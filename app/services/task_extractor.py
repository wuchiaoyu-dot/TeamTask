from __future__ import annotations

import re
from datetime import date

from app.models import SourceEvent
from app.schemas.api import EventIn
from app.schemas.llm_task_schema import TaskCandidate


def extract_task_candidates(source_event: SourceEvent, payload: EventIn) -> list[TaskCandidate]:
    if source_event.event_type == "meeting" or (payload.parsed_context_json or {}).get("source_type") == "meeting_minutes":
        candidates = _extract_minutes_candidates(source_event, payload)
        return candidates or [_fallback_candidate(source_event, payload)]
    return [_fallback_candidate(source_event, payload)]


def _extract_minutes_candidates(source_event: SourceEvent, payload: EventIn) -> list[TaskCandidate]:
    parsed = payload.parsed_context_json or {}
    action_sections = parsed.get("action_sections") or []
    evidence_blocks = parsed.get("evidence_blocks") or []
    text = "\n".join(action_sections) if action_sections else payload.text
    lines = [line.strip("-• \t") for line in text.splitlines() if line.strip()]
    candidates: list[TaskCandidate] = []

    for line in lines:
        assignees = _extract_user_ids(line)
        if not _looks_actionable(line):
            continue
        if not assignees and line.rstrip().endswith(":"):
            continue
        if not assignees:
            candidates.append(
                _candidate_from_line(
                    source_event,
                    payload,
                    line,
                    assignee=payload.sender_user_id,
                    evidence=evidence_blocks or [line],
                    confidence=0.45,
                    missing_fields=["assignee"],
                )
            )
            continue

        parent_title = _guess_title(line) if len(assignees) > 1 else None
        for assignee in assignees:
            candidates.append(
                _candidate_from_line(
                    source_event,
                    payload,
                    line,
                    assignee=assignee,
                    evidence=evidence_blocks or [line],
                    confidence=0.82,
                    parent_task_title=parent_title,
                )
            )
    return candidates


def _candidate_from_line(
    source_event: SourceEvent,
    payload: EventIn,
    line: str,
    assignee: str,
    evidence: list[str],
    confidence: float,
    missing_fields: list[str] | None = None,
    parent_task_title: str | None = None,
) -> TaskCandidate:
    return TaskCandidate(
        task_title=_guess_title(line),
        task_description=line,
        project_name=payload.project_name,
        parent_task_title=parent_task_title,
        initiator=payload.initiator_user_id or payload.sender_user_id,
        assignee=assignee,
        task_type="meeting_action_item",
        workload_level="medium",
        deadline=_guess_deadline(line),
        resource_keywords=["meeting_minutes"],
        mentioned_resources=[payload.source_link] if payload.source_link else [],
        evidence=evidence[:5],
        missing_fields=missing_fields or [],
        confidence=confidence,
    )


def _fallback_candidate(source_event: SourceEvent, payload: EventIn) -> TaskCandidate:
    initiator = payload.initiator_user_id or payload.sender_user_id
    assignee = payload.assignee_user_id or _guess_assignee(initiator, payload.participant_user_ids)
    missing_fields: list[str] = []
    confidence = 0.86
    if not assignee:
        assignee = initiator
        missing_fields.append("assignee")
        confidence = 0.45
    if any(keyword in payload.text for keyword in ("maybe", "uncertain", "待定", "不确定", "低置信度")):
        confidence = min(confidence, 0.42)

    return TaskCandidate(
        task_title=_guess_title(payload.text),
        task_description=payload.text,
        project_name=payload.project_name,
        initiator=initiator,
        assignee=assignee,
        task_type="follow_up",
        workload_level="medium",
        deadline=_guess_deadline(payload.text),
        resource_keywords=[],
        mentioned_resources=re.findall(r"https?://\S+", payload.text),
        evidence=[payload.text],
        missing_fields=missing_fields,
        confidence=confidence,
    )


def _looks_actionable(line: str) -> bool:
    lowered = line.lower()
    return any(
        marker in lowered
        for marker in ("todo", "action", "next", "负责", "待办", "行动项", "下一步", "will", "finish", "prepare", "推进")
    )


def _extract_user_ids(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\bu_[A-Za-z0-9_]+\b", text)))


def _guess_assignee(initiator: str, participant_user_ids: list[str]) -> str | None:
    for user_id in participant_user_ids:
        if user_id != initiator:
            return user_id
    return None


def _guess_title(text: str) -> str:
    normalized = " ".join(text.strip().split())
    return normalized[:80] or "Task candidate"


def _guess_deadline(text: str) -> date | None:
    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
