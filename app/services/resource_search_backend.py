from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.clients.feishu_client import FeishuClient
from app.clients.lark_cli_client import ensure_lark_cli_stdout, format_lark_cli_error, run_lark_cli_subprocess
from app.config import Settings, get_settings
from app.core.external_read_guard import should_allow_external_read
from app.models import SourceEvent, TaskContract
from app.services.resource_ranker import (
    build_resource_queries,
    classify_resource_confidence,
    extract_referenced_doc_names,
    normalize_resource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceSearchResult:
    high_confidence: list[dict[str, Any]]
    low_confidence: list[dict[str, Any]]
    raw_results: list[dict[str, Any]]
    search_queries: list[str]
    backend: str
    dry_run: bool


class ResourceSearchBackend:
    backend = "base"

    def search_resources(
        self,
        user_id: str,
        task_contract: TaskContract,
        source_event: SourceEvent,
    ) -> ResourceSearchResult:
        raise NotImplementedError


class MockResourceSearchBackend(ResourceSearchBackend):
    backend = "mock"

    def __init__(self, settings: Settings | None = None, backend_name: str = "mock", dry_run: bool = True) -> None:
        self.settings = settings or get_settings()
        self.backend = backend_name
        self.dry_run = dry_run

    def search_resources(
        self,
        user_id: str,
        task_contract: TaskContract,
        source_event: SourceEvent,
    ) -> ResourceSearchResult:
        queries = build_resource_queries(task_contract, source_event, self.settings)
        raw_results = self._mock_raw_results(task_contract, source_event, queries)
        high, low = _rank_results(raw_results, task_contract, source_event, self.settings)
        return ResourceSearchResult(
            high_confidence=high[: self.settings.resource_search_top_k],
            low_confidence=low[: self.settings.resource_search_top_k],
            raw_results=raw_results,
            search_queries=queries,
            backend=self.backend,
            dry_run=self.dry_run,
        )

    def _mock_raw_results(
        self,
        task_contract: TaskContract,
        source_event: SourceEvent,
        queries: list[str],
    ) -> list[dict[str, Any]]:
        raw_results: list[dict[str, Any]] = []
        for index, url in enumerate(task_contract.mentioned_resources or [], start=1):
            raw_results.append(
                {
                    "title": f"Explicit resource {index}",
                    "url": url,
                    "source_type": "explicit_link",
                    "confidence": 0.96,
                    "reason": "Task candidate explicitly mentioned this resource link.",
                    "matched_keywords": ["explicit_link"],
                }
            )

        for evidence in task_contract.evidence or []:
            for doc_name in extract_referenced_doc_names(evidence):
                raw_results.append(
                    {
                        "title": f"{doc_name} 文档",
                        "url": f"https://mock.feishu.local/docs/{doc_name}",
                        "source_type": "mentioned_doc",
                        "confidence": 0.91,
                        "reason": f"Evidence explicitly says to reference {doc_name}.",
                        "matched_keywords": [doc_name],
                    }
                )

        for index, query in enumerate(queries, start=1):
            raw_results.append(
                {
                    "title": f"{query} related project notes",
                    "url": f"https://mock.feishu.local/search/{index}",
                    "source_type": "semantic_match",
                    "confidence": 0.62,
                    "reason": "Semantic match from task title, project, or keywords.",
                    "matched_keywords": [query],
                }
            )
        return raw_results


class LarkCliResourceSearchBackend(ResourceSearchBackend):
    backend = "lark_cli"

    def __init__(self, feishu_client: FeishuClient, settings: Settings | None = None) -> None:
        self.feishu_client = feishu_client
        self.settings = settings or get_settings()

    def search_resources(
        self,
        user_id: str,
        task_contract: TaskContract,
        source_event: SourceEvent,
    ) -> ResourceSearchResult:
        logger.info(
            "LarkCliResourceSearchBackend search user_id=%s contract_id=%s dry_run=%s real_read=%s sources=%s",
            user_id,
            task_contract.id,
            self.settings.resource_search_dry_run or not self.settings.resource_search_real_read,
            should_allow_external_read(self.settings),
            self.settings.resource_search_sources,
        )
        if (
            self.settings.resource_search_dry_run
            or not self.settings.resource_search_real_read
            or not should_allow_external_read(self.settings)
        ):
            return MockResourceSearchBackend(self.settings, backend_name="lark_cli", dry_run=True).search_resources(
                user_id,
                task_contract,
                source_event,
            )

        raw_results: list[dict[str, Any]] = []
        queries = build_resource_queries(task_contract, source_event, self.settings)
        for query in queries:
            raw_results.extend(self._search_query(user_id, query))
        raw_results = _dedupe_by_url(raw_results)
        high, low = _rank_results(raw_results, task_contract, source_event, self.settings)
        return ResourceSearchResult(
            high_confidence=high[: self.settings.resource_search_top_k],
            low_confidence=low[: self.settings.resource_search_top_k],
            raw_results=raw_results,
            search_queries=queries,
            backend=self.backend,
            dry_run=False,
        )

    def _search_query(self, user_id: str, query: str) -> list[dict[str, Any]]:
        raw_results: list[dict[str, Any]] = []
        for source in self.settings.resource_search_sources:
            command = [
                self.settings.lark_cli_path,
                "search",
                "+query",
                "--source",
                source,
                "--query",
                query,
                "--limit",
                str(self.settings.feishu_doc_search_top_k),
                "--as",
                "user" if self.settings.feishu_read_as_user else "bot",
            ]
            redacted_command = _redact_command(command)
            logger.info("lark-cli resource search command=%s", redacted_command)
            completed = run_lark_cli_subprocess(command, timeout_seconds=self.settings.feishu_read_timeout_seconds)
            logger.info(
                "lark-cli resource search returncode=%s stdout=%s stderr=%s",
                completed.returncode,
                _redact_text(completed.stdout),
                _redact_text(completed.stderr),
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    format_lark_cli_error(
                        operation="resource_search",
                        command=redacted_command,
                        returncode=completed.returncode,
                        stdout=completed.stdout,
                        stderr=completed.stderr,
                        reason="non-zero exit",
                    )
                )
            stdout = ensure_lark_cli_stdout("resource_search", completed, redacted_command)
            for item in parse_lark_cli_search_output(stdout):
                normalized = normalize_resource_result({**item, "matched_keywords": [query], "source": source})
                raw_results.append(normalized)
        return raw_results


def create_resource_search_backend(
    feishu_client: FeishuClient,
    settings: Settings | None = None,
) -> ResourceSearchBackend:
    settings = settings or get_settings()
    if settings.feishu_mock or settings.resource_search_backend != "lark_cli":
        return MockResourceSearchBackend(settings)
    return LarkCliResourceSearchBackend(feishu_client, settings)


def parse_lark_cli_search_output(raw_output: str | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(raw_output, dict):
        payload = raw_output
    else:
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    items = data.get("items") or data.get("results") or data.get("docs") or []
    if isinstance(items, dict):
        items = [items]
    return [item for item in items if isinstance(item, dict)]


def normalize_resource_result(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("source") or raw.get("source_type") or raw.get("type") or "semantic_match"
    title = raw.get("title") or raw.get("name") or raw.get("document_title") or "Untitled"
    url = raw.get("url") or raw.get("link") or raw.get("web_url") or raw.get("source_url")
    return {
        "title": title,
        "url": url,
        "source_type": _source_type(source),
        "confidence": float(raw.get("confidence") or raw.get("score") or 0.6),
        "reason": raw.get("reason") or f"Returned by lark-cli {source} search.",
        "matched_keywords": raw.get("matched_keywords") or [],
        "owner": raw.get("owner") or raw.get("creator"),
        "updated_at": raw.get("updated_at") or raw.get("last_edited_time"),
    }


def _rank_results(
    raw_results: list[dict[str, Any]],
    task_contract: TaskContract,
    source_event: SourceEvent,
    settings: Settings,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    high: list[dict[str, Any]] = []
    low: list[dict[str, Any]] = []
    for raw in raw_results:
        bucket = classify_resource_confidence(raw, task_contract, source_event, settings)
        if bucket == "ignore":
            continue
        normalized = normalize_resource(raw, task_contract, source_event, settings)
        if bucket == "high":
            high.append(normalized)
        else:
            low.append(normalized)
    high.sort(key=lambda item: item["confidence"], reverse=True)
    low.sort(key=lambda item: item["confidence"], reverse=True)
    return high, low


def _dedupe_by_url(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for resource in resources:
        url = str(resource.get("url") or "")
        key = url or f"{resource.get('title')}:{resource.get('source_type')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(resource)
    return deduped


def _source_type(source: str) -> str:
    lowered = str(source).lower()
    if "minute" in lowered:
        return "historical_minutes"
    if "base" in lowered or "bitable" in lowered:
        return "base_match"
    if "doc" in lowered:
        return "semantic_match"
    return lowered or "semantic_match"


def _redact_command(command: list[str]) -> list[str]:
    return [_redact_text(item) for item in command]


def _redact_text(text: str | None) -> str:
    text = "" if text is None else str(text)
    redacted = text
    for name in ("FEISHU_APP_SECRET", "FEISHU_ACCESS_TOKEN", "LARK_ACCESS_TOKEN", "FEISHU_BITABLE_APP_TOKEN"):
        value = os.getenv(name)
        if value:
            redacted = redacted.replace(value, "<redacted>")
    redacted = re.sub(r"(token|secret|authorization)[=:/\s]+[^\s/&]+", r"\1=<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"/(docx|wiki|minutes|base)/[A-Za-z0-9._-]+", r"/\1/<redacted>", redacted)
    return redacted
