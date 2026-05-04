from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProgressQuery, SourceEvent, TaskContract
from app.state_machine import TaskStatus

QUERY_STATUS_PENDING = "pending_assignee_confirm"
QUERY_STATUS_CONFIRMED = "confirmed"
QUERY_STATUS_NO_MATCHING_TASK = "no_matching_task"
QUERY_STATUS_CANCELLED = "cancelled"

COMPLETION_NOT_STARTED = "not_started"
COMPLETION_IN_PROGRESS = "in_progress"
COMPLETION_BLOCKED = "blocked"
COMPLETION_COMPLETED = "completed"
COMPLETION_DELAYED = "delayed"
COMPLETION_UNKNOWN = "unknown"

PROGRESS_QUERY_KEYWORDS = {
    "progress",
    "status",
    "done",
    "finished",
    "complete",
    "completed",
    "blocked",
    "delay",
    "delayed",
    "\u8fdb\u5c55",
    "\u8fdb\u5ea6",
    "\u505a\u5b8c",
    "\u5b8c\u6210",
    "\u600e\u4e48\u6837",
    "\u5230\u54ea",
}

STOPWORDS = {
    "teamtask",
    "please",
    "check",
    "query",
    "task",
    "that",
    "the",
    "is",
    "are",
    "has",
    "have",
    "done",
    "finished",
    "complete",
    "completed",
    "progress",
    "status",
    "\u90a3\u4e2a",
    "\u4efb\u52a1",
    "\u8fdb\u5c55",
    "\u8fdb\u5ea6",
    "\u505a\u5b8c",
    "\u5b8c\u6210",
    "\u4e86\u5417",
}


@dataclass(frozen=True)
class ProgressQueryIntent:
    requester_user_id: str
    assignee_name: str | None = None
    assignee_user_id: str | None = None
    task_keywords: list[str] = field(default_factory=list)
    project_name: str | None = None
    deadline_hint: date | None = None
    confidence: float = 0.0
    missing_fields: list[str] = field(default_factory=list)


def detect_progress_query(text: str) -> bool:
    lowered = text.lower()
    if "?" in text or "\uff1f" in text or "\u5417" in text:
        if any(keyword in lowered for keyword in PROGRESS_QUERY_KEYWORDS):
            return True
    return any(keyword in lowered for keyword in {"progress?", "status?", "done?", "finished?"})


def extract_progress_query_entities(text: str, requester_user_id: str = "") -> ProgressQueryIntent:
    assignee_user_id = _extract_user_id(text)
    assignee_name = _extract_assignee_name(text, assignee_user_id)
    task_keywords = _extract_task_keywords(text)
    missing_fields: list[str] = []
    if not assignee_user_id and not assignee_name:
        missing_fields.append("assignee")
    if not task_keywords:
        missing_fields.append("task_keywords")
    confidence = 0.85
    if missing_fields:
        confidence = 0.55 if task_keywords else 0.35
    return ProgressQueryIntent(
        requester_user_id=requester_user_id,
        assignee_name=assignee_name,
        assignee_user_id=assignee_user_id,
        task_keywords=task_keywords,
        project_name=_extract_project_name(text),
        deadline_hint=_extract_deadline(text),
        confidence=confidence,
        missing_fields=missing_fields,
    )


def match_task_contract(
    db: Session,
    requester_user_id: str,
    assignee_user_id: str | None,
    query_text: str,
    source_event: SourceEvent | None = None,
) -> list[TaskContract]:
    statement = select(TaskContract).where(
        TaskContract.status.in_(
            [
                TaskStatus.ACTIVE.value,
                TaskStatus.PROGRESS_UPDATED.value,
                TaskStatus.COMPLETED.value,
            ]
        )
    )
    if assignee_user_id:
        statement = statement.where(TaskContract.assignee_user_id == assignee_user_id)

    contracts = list(db.scalars(statement))
    scored = [
        (contract, _score_contract(contract, requester_user_id, query_text, source_event))
        for contract in contracts
    ]
    matched = [(contract, score) for contract, score in scored if score > 0]
    matched.sort(key=lambda item: (item[1], item[0].updated_at), reverse=True)
    return [contract for contract, _ in matched]


def create_progress_query(
    db: Session,
    *,
    external_event_id: str | None,
    requester_user_id: str,
    assignee_user_id: str | None,
    matched_contract_id: int | None,
    query_text: str,
    query_status: str,
    raw_payload_json: dict[str, Any] | None = None,
) -> ProgressQuery:
    existing = find_progress_query_by_external_event_id(db, external_event_id)
    if existing:
        return existing
    query = ProgressQuery(
        external_event_id=external_event_id,
        requester_user_id=requester_user_id,
        assignee_user_id=assignee_user_id,
        matched_contract_id=matched_contract_id,
        query_text=query_text,
        query_status=query_status,
        raw_payload_json=raw_payload_json or {},
    )
    db.add(query)
    db.flush()
    return query


def find_progress_query_by_external_event_id(db: Session, external_event_id: str | None) -> ProgressQuery | None:
    if not external_event_id:
        return None
    return db.scalar(select(ProgressQuery).where(ProgressQuery.external_event_id == external_event_id))


def build_progress_summary(progress_query: ProgressQuery, task_contract: TaskContract | None) -> str:
    if task_contract is None or progress_query.query_status == QUERY_STATUS_NO_MATCHING_TASK:
        assignee = progress_query.assignee_user_id or "\u6267\u884c\u8005"
        return f"{assignee} reported that the requested task was not confirmed."

    status_text = task_contract.completion_status or COMPLETION_UNKNOWN
    progress_text = task_contract.progress_text or task_contract.progress_summary or "No progress details provided."
    return (
        f"{task_contract.assignee_user_id} confirmed '{task_contract.title}' as {status_text}. "
        f"Progress: {progress_text}"
    )


def _score_contract(
    contract: TaskContract,
    requester_user_id: str,
    query_text: str,
    source_event: SourceEvent | None,
) -> int:
    lowered = query_text.lower()
    keywords = _extract_task_keywords(query_text)
    haystack = " ".join(
        str(value or "")
        for value in [
            contract.title,
            contract.description,
            contract.project_name,
            contract.parent_task_title,
            " ".join(contract.resource_keywords or []),
            " ".join(contract.evidence or []),
        ]
    ).lower()

    strong_score = 0
    if contract.title and contract.title.lower() in lowered:
        strong_score += 4
    if contract.project_name and contract.project_name.lower() in lowered:
        strong_score += 3
    for keyword in keywords:
        if keyword.lower() in haystack:
            strong_score += 3
    if strong_score == 0:
        return 0

    score = strong_score
    if contract.initiator_user_id == requester_user_id:
        score += 1
    if source_event is not None:
        query_chat = (source_event.event_metadata or {}).get("chat_id")
        contract_chat = (contract.source_event.event_metadata or {}).get("chat_id") if contract.source_event else None
        if query_chat and contract_chat and query_chat == contract_chat:
            score += 1
    return score


def _extract_task_keywords(text: str) -> list[str]:
    lowered = text.lower()
    lowered = re.sub(r"@\w+", " ", lowered)
    lowered = re.sub(r"\bu_[A-Za-z0-9_]+\b", " ", lowered)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|\d{4}-\d{1,2}-\d{1,2}|[\u4e00-\u9fff]{2,}", lowered)
    results: list[str] = []
    for token in tokens:
        token = token.strip("_-?？.,，。")
        if not token or token in STOPWORDS or token in PROGRESS_QUERY_KEYWORDS:
            continue
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", token):
            continue
        if token not in results:
            results.append(token[:80])
    return results[:8]


def _extract_user_id(text: str) -> str | None:
    match = re.search(r"\bu_[A-Za-z0-9_]+\b", text)
    return match.group(0) if match else None


def _extract_assignee_name(text: str, assignee_user_id: str | None) -> str | None:
    if assignee_user_id:
        return None
    match = re.search(r"([\u4e00-\u9fff]{2,4})\u90a3\u4e2a", text)
    if match:
        return match.group(1)
    return None


def _extract_project_name(text: str) -> str | None:
    match = re.search(r"(?:project|project_name)[:=]\s*([A-Za-z0-9_-]{2,80})", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_deadline(text: str) -> date | None:
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None
