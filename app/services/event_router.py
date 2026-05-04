from __future__ import annotations

import re
from datetime import date

from app.models import SourceEvent
from app.schemas.api import EventIn
from app.schemas.llm_task_schema import TaskCandidate
from app.services.progress_query_service import detect_progress_query
from app.services.task_extractor import extract_task_candidates


ASSIGN_KEYWORDS = (
    "安排",
    "负责",
    "完成",
    "跟进",
    "请",
    "分配",
    "交付",
    "assign",
    "assigned",
    "please do",
    "responsible for",
    "by friday",
    "due",
    "todo",
    "task",
)
PROGRESS_QUERY_KEYWORDS = ("进展", "进度", "怎么样", "到哪", "状态")
PROGRESS_UPDATE_KEYWORDS = ("已完成", "完成了", "更新进度", "推进到", "blocked", "done")
RESOURCE_KEYWORDS = ("资料", "文档", "链接", "附件", "资源")
LOW_CONFIDENCE_KEYWORDS = ("可能", "也许", "待定", "不确定", "低置信度")


def classify_intent(text: str) -> str:
    lowered = text.lower()
    if detect_progress_query(text):
        return "ask_progress"
    if any(keyword in lowered or keyword in text for keyword in ASSIGN_KEYWORDS):
        return "assign_task"
    if any(keyword in lowered for keyword in PROGRESS_UPDATE_KEYWORDS):
        return "update_progress"
    if any(keyword in text for keyword in PROGRESS_QUERY_KEYWORDS):
        return "ask_progress"
    if any(keyword in text for keyword in RESOURCE_KEYWORDS):
        return "attach_resource"
    return "smalltalk"


def route_source_event(source_event: SourceEvent) -> str:
    source_event.intent = classify_intent(source_event.raw_text)
    return source_event.intent


def extract_task_candidate(source_event: SourceEvent, payload: EventIn) -> TaskCandidate:
    return extract_task_candidates(source_event, payload)[0]


def _guess_assignee(initiator: str, participant_user_ids: list[str]) -> str | None:
    for user_id in participant_user_ids:
        if user_id != initiator:
            return user_id
    return None


def _guess_title(text: str) -> str:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return "待确认任务"
    sentence = re.split(r"[。！？!?]", normalized, maxsplit=1)[0]
    return sentence[:80] or "待确认任务"


def _guess_deadline(text: str) -> date | None:
    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://\S+", text)
