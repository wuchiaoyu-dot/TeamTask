from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.models import SourceEvent
from app.schemas.api import EventIn
from app.schemas.llm_task_schema import TaskCandidate, TaskCandidateExtraction


def extract_task_candidates(source_event: SourceEvent, payload: EventIn) -> list[TaskCandidate]:
    settings = get_settings()
    rule_candidates = extract_rule_task_candidates(source_event, payload)
    if settings.task_extractor_backend == "rule":
        return rule_candidates
    if settings.task_extractor_backend not in {"llm", "auto"}:
        return rule_candidates
    if not _llm_is_configured(settings):
        if settings.task_extractor_llm_fallback:
            return rule_candidates
        raise RuntimeError("LLM task extraction is enabled but LLM_TASK_API_KEY or LLM_TASK_MODEL is missing")
    try:
        llm_candidates = _extract_llm_task_candidates(source_event, payload, rule_candidates, settings)
    except Exception:
        if settings.task_extractor_llm_fallback:
            return rule_candidates
        raise
    return llm_candidates or rule_candidates


def extract_rule_task_candidates(source_event: SourceEvent, payload: EventIn) -> list[TaskCandidate]:
    if source_event.event_type == "meeting" or (payload.parsed_context_json or {}).get("source_type") == "meeting_minutes":
        candidates = _extract_minutes_candidates(source_event, payload)
        return candidates or [_fallback_candidate(source_event, payload)]
    return [_fallback_candidate(source_event, payload)]


def _extract_llm_task_candidates(
    source_event: SourceEvent,
    payload: EventIn,
    rule_candidates: list[TaskCandidate],
    settings: Settings,
) -> list[TaskCandidate]:
    response = _call_llm_task_extractor(source_event, payload, rule_candidates, settings)
    data = _parse_json_object(response)
    extraction = TaskCandidateExtraction.model_validate(data)
    return [_normalize_llm_candidate(candidate, payload) for candidate in extraction.task_candidates]


def _call_llm_task_extractor(
    source_event: SourceEvent,
    payload: EventIn,
    rule_candidates: list[TaskCandidate],
    settings: Settings,
) -> str:
    endpoint = f"{settings.llm_task_api_base}/chat/completions"
    body = {
        "model": settings.llm_task_model,
        "temperature": settings.llm_task_temperature,
        "messages": [
            {
                "role": "system",
                "content": _read_extraction_prompt(settings),
            },
            {
                "role": "user",
                "content": json.dumps(
                    _build_llm_extraction_input(source_event, payload, rule_candidates, settings),
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
    }
    if settings.llm_task_response_format not in {"", "none", "off", "disabled"}:
        body["response_format"] = {"type": settings.llm_task_response_format}
    headers = {
        "Authorization": f"Bearer {settings.llm_task_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.llm_task_timeout_seconds) as client:
        result = client.post(endpoint, headers=headers, json=body)
        if result.status_code >= 400:
            _print_llm_task_http_error(result.status_code, endpoint, result.text, settings.llm_task_api_key)
            if _should_retry_without_response_format(result, body):
                retry_body = dict(body)
                retry_body.pop("response_format", None)
                result = client.post(endpoint, headers=headers, json=retry_body)
                if result.status_code >= 400:
                    _print_llm_task_http_error(result.status_code, endpoint, result.text, settings.llm_task_api_key)
        try:
            result.raise_for_status()
        except httpx.HTTPStatusError as exc:
            _print_llm_task_http_error(
                exc.response.status_code,
                str(exc.request.url),
                exc.response.text,
                settings.llm_task_api_key,
            )
            raise
        raw = result.json()
    return raw["choices"][0]["message"]["content"]


def _build_llm_extraction_input(
    source_event: SourceEvent,
    payload: EventIn,
    rule_candidates: list[TaskCandidate],
    settings: Settings,
) -> dict[str, Any]:
    return {
        "source": {
            "event_type": source_event.event_type,
            "source_id": payload.source_id or source_event.source_id,
            "source_type": (payload.parsed_context_json or {}).get("source_type"),
            "sender_user_id": payload.sender_user_id,
            "participant_user_ids": payload.participant_user_ids,
            "initiator_user_id": payload.initiator_user_id or payload.sender_user_id,
            "assignee_user_id": payload.assignee_user_id,
            "project_name": payload.project_name,
            "source_link": payload.source_link,
        },
        "text": payload.text[: settings.llm_task_max_input_chars],
        "parsed_context_json": payload.parsed_context_json or {},
        "rule_candidates": [candidate.model_dump(mode="json") for candidate in rule_candidates],
        "output_contract": {
            "top_level_key": "task_candidates",
            "date_format": "YYYY-MM-DD",
            "confidence_range": "0.0-1.0",
        },
    }


def _normalize_llm_candidate(candidate: TaskCandidate, payload: EventIn) -> TaskCandidate:
    updates: dict[str, Any] = {}
    known_user_ids = _known_user_ids(payload)
    if candidate.project_name is None and payload.project_name:
        updates["project_name"] = payload.project_name
    if not candidate.evidence:
        updates["evidence"] = [payload.text[:300]]
    if not candidate.initiator or candidate.initiator not in known_user_ids:
        updates["initiator"] = payload.initiator_user_id or payload.sender_user_id
    if not candidate.assignee or candidate.assignee not in known_user_ids:
        updates["assignee"] = payload.assignee_user_id or updates.get("initiator") or candidate.initiator
        updates["missing_fields"] = list(dict.fromkeys(candidate.missing_fields + ["assignee"]))
        updates["confidence"] = min(candidate.confidence, 0.45)
    if candidate.mentioned_resources == []:
        urls = re.findall(r"https?://\S+", payload.text)
        if urls:
            updates["mentioned_resources"] = urls
    return candidate.model_copy(update=updates)


def _read_extraction_prompt(settings: Settings) -> str:
    path = Path(settings.llm_task_prompt_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return _default_extraction_prompt()


def _default_extraction_prompt() -> str:
    return (
        "Extract concrete TeamTask action items from group chat text or meeting minutes. "
        "Return only JSON with a task_candidates array. Do not invent users, deadlines, "
        "or evidence. If assignee is unclear, set assignee to the initiator, add "
        "missing_fields ['assignee'], and keep confidence below 0.6."
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _llm_is_configured(settings: Settings) -> bool:
    return bool(settings.llm_task_api_key and settings.llm_task_model and settings.llm_task_api_base)


def _print_llm_task_http_error(status_code: int, url: str, body: str, api_key: str | None) -> None:
    safe_url = _redact_secret(url, api_key)
    safe_body = _redact_secret(body, api_key)
    print(f"LLM_TASK_HTTP_ERROR status={status_code} url={safe_url} body={safe_body}")


def _redact_secret(value: str, secret: str | None) -> str:
    if not secret:
        return value
    return value.replace(secret, "[REDACTED]")


def _should_retry_without_response_format(result: httpx.Response, body: dict[str, Any]) -> bool:
    if "response_format" not in body:
        return False
    if result.status_code != 400:
        return False
    text = result.text.lower()
    return "response_format" in text and ("not supported" in text or "not valid" in text)


def _known_user_ids(payload: EventIn) -> set[str]:
    users = set(payload.participant_user_ids)
    users.add(payload.sender_user_id)
    if payload.initiator_user_id:
        users.add(payload.initiator_user_id)
    if payload.assignee_user_id:
        users.add(payload.assignee_user_id)
    users.update(_extract_user_ids(payload.text))
    return {user_id for user_id in users if user_id}


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
