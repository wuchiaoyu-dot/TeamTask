from __future__ import annotations

import re
from typing import Any

from app.config import Settings, get_settings
from app.models import SourceEvent, TaskContract


def build_resource_queries(
    task_contract: TaskContract,
    source_event: SourceEvent,
    settings: Settings | None = None,
) -> list[str]:
    settings = settings or get_settings()
    terms: list[str] = []
    _add_terms(terms, task_contract.project_name)
    _add_terms(terms, task_contract.title)
    for keyword in task_contract.resource_keywords or []:
        _add_terms(terms, keyword)
    _add_terms(terms, task_contract.description)
    for evidence in task_contract.evidence or []:
        for doc_name in extract_referenced_doc_names(evidence):
            _add_terms(terms, doc_name)

    deduped: list[str] = []
    for term in terms:
        normalized = term.strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
        if len(deduped) >= settings.resource_search_max_query_terms:
            break
    return deduped


def classify_resource_confidence(
    raw_resource: dict[str, Any],
    task_contract: TaskContract,
    source_event: SourceEvent,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    score = score_resource(raw_resource, task_contract, source_event, settings)
    if score >= settings.resource_search_high_confidence_threshold:
        return "high"
    if score >= settings.resource_search_low_confidence_threshold:
        return "low"
    return "ignore"


def score_resource(
    raw_resource: dict[str, Any],
    task_contract: TaskContract,
    source_event: SourceEvent,
    settings: Settings | None = None,
) -> float:
    if not raw_resource.get("title") or not raw_resource.get("url"):
        return 0.0

    source_type = raw_resource.get("source_type")
    explicit_urls = set(task_contract.mentioned_resources or [])
    evidence_text = "\n".join(task_contract.evidence or [])
    title = str(raw_resource.get("title") or "")
    url = str(raw_resource.get("url") or "")

    if source_type in {"explicit_link", "mentioned_doc"} or url in explicit_urls:
        return max(float(raw_resource.get("confidence") or 0.0), 0.95)
    if _evidence_references_title(evidence_text, title):
        return max(float(raw_resource.get("confidence") or 0.0), 0.9)
    if source_type == "source_context":
        return max(float(raw_resource.get("confidence") or 0.0), 0.85)

    base_score = float(raw_resource.get("confidence") or 0.0)
    haystack = f"{title} {raw_resource.get('reason') or ''}".lower()
    strong_terms = [task_contract.project_name or "", task_contract.title or ""]
    if any(term and term.lower() in haystack for term in strong_terms):
        base_score = max(base_score, 0.82)

    matched = raw_resource.get("matched_keywords") or []
    if matched:
        base_score = max(base_score, min(0.75, 0.5 + 0.08 * len(matched)))
    return base_score


def normalize_resource(
    raw_resource: dict[str, Any],
    task_contract: TaskContract,
    source_event: SourceEvent,
    settings: Settings | None = None,
) -> dict[str, Any]:
    score = score_resource(raw_resource, task_contract, source_event, settings)
    return {
        "title": raw_resource.get("title"),
        "url": raw_resource.get("url"),
        "source_type": raw_resource.get("source_type") or "semantic_match",
        "confidence": round(score, 2),
        "reason": raw_resource.get("reason") or "Matched by TeamTask resource search.",
        "matched_keywords": raw_resource.get("matched_keywords") or [],
    }


def extract_referenced_doc_names(text: str) -> list[str]:
    results: list[str] = []
    patterns = [
        r"参考\s*([^\s，。,.]{2,40})\s*文档",
        r"refer(?:ence)?\s+([A-Za-z0-9 _-]{2,60})\s+doc",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(1).strip()
            if value and value not in results:
                results.append(value)
    return results


def _evidence_references_title(evidence_text: str, title: str) -> bool:
    if not title:
        return False
    references = extract_referenced_doc_names(evidence_text)
    return any(reference.lower() in title.lower() or title.lower() in reference.lower() for reference in references)


def _add_terms(terms: list[str], value: str | None) -> None:
    if not value:
        return
    for token in re.split(r"[\s,，。:：;；/|]+", value):
        token = token.strip("-_")
        if len(token) >= 2:
            terms.append(token[:80])
