from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.clients.feishu_client import FeishuClient
from app.config import Settings, get_settings
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
            "LarkCliResourceSearchBackend search user_id=%s contract_id=%s dry_run=%s sources=%s",
            user_id,
            task_contract.id,
            self.settings.resource_search_dry_run or self.settings.lark_dry_run,
            self.settings.resource_search_sources,
        )
        if self.settings.resource_search_dry_run or self.settings.lark_dry_run:
            return MockResourceSearchBackend(self.settings, backend_name="lark_cli", dry_run=True).search_resources(
                user_id,
                task_contract,
                source_event,
            )

        raw_results: list[dict[str, Any]] = []
        queries = build_resource_queries(task_contract, source_event, self.settings)
        for query in queries:
            for result in self.feishu_client.search_docs(user_id, query):
                raw_results.append(
                    {
                        "title": result.get("title") or result.get("name"),
                        "url": result.get("url") or result.get("link"),
                        "source_type": result.get("source_type") or "semantic_match",
                        "confidence": result.get("confidence") or 0.6,
                        "reason": result.get("reason") or "Returned by lark-cli document search.",
                        "matched_keywords": [query],
                    }
                )
        high, low = _rank_results(raw_results, task_contract, source_event, self.settings)
        return ResourceSearchResult(
            high_confidence=high[: self.settings.resource_search_top_k],
            low_confidence=low[: self.settings.resource_search_top_k],
            raw_results=raw_results,
            search_queries=queries,
            backend=self.backend,
            dry_run=False,
        )


def create_resource_search_backend(
    feishu_client: FeishuClient,
    settings: Settings | None = None,
) -> ResourceSearchBackend:
    settings = settings or get_settings()
    if settings.feishu_mock or settings.resource_search_backend != "lark_cli":
        return MockResourceSearchBackend(settings)
    return LarkCliResourceSearchBackend(feishu_client, settings)


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
