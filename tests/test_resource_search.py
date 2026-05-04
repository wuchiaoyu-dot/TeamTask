from __future__ import annotations

import subprocess
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.clients.feishu_client import MockFeishuClient
from app.config import Settings
from app.models import TaskContract
from app.services.resource_ranker import build_resource_queries, classify_resource_confidence
from app.services.resource_search_backend import LarkCliResourceSearchBackend, ResourceSearchResult


def test_mentioned_resource_link_enters_high_confidence(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    url = "https://example.feishu.cn/docx/resource-alpha"
    contract_id = _submit_event(
        client,
        "evt-resource-explicit-link",
        f"Please assign u_assignee to finish TeamTask resource review by 2026-06-01. See {url}",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)

    assert contract is not None
    high = contract.related_resources_json["high_confidence"]
    assert any(item["url"] == url and item["source_type"] == "explicit_link" for item in high)


def test_evidence_reference_doc_generates_high_confidence(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    reference_text = "\u53c2\u8003 LaunchPlan \u6587\u6863"
    contract_id = _submit_event(
        client,
        "evt-resource-evidence-doc",
        f"Please assign u_assignee to finish TeamTask launch review by 2026-06-01. {reference_text}",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)

    assert contract is not None
    high = contract.related_resources_json["high_confidence"]
    assert any(item["source_type"] == "mentioned_doc" and "LaunchPlan" in item["title"] for item in high)


def test_keyword_only_semantic_match_is_low_confidence(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _submit_event(
        client,
        "evt-resource-keyword-low",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        raw_resource = {
            "title": "Enablement notes",
            "url": "https://mock.feishu.local/docs/enablement",
            "source_type": "semantic_match",
            "confidence": 0.62,
            "matched_keywords": ["enablement"],
        }
        bucket = classify_resource_confidence(raw_resource, contract, contract.source_event)

    assert bucket == "low"


def test_resource_below_low_threshold_is_ignored(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _submit_event(
        client,
        "evt-resource-ignore",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        raw_resource = {
            "title": "Unrelated page",
            "url": "https://mock.feishu.local/docs/noise",
            "source_type": "semantic_match",
            "confidence": 0.2,
        }
        bucket = classify_resource_confidence(raw_resource, contract, contract.source_event)

    assert bucket == "ignore"


def test_build_resource_queries_combines_title_project_and_keywords(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _submit_event(
        client,
        "evt-resource-query-build",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        contract.title = "Launch Plan"
        contract.project_name = "ProjectPhoenix"
        contract.resource_keywords = ["deck", "metrics"]
        queries = build_resource_queries(contract, contract.source_event)

    assert "ProjectPhoenix" in queries
    assert "Launch" in queries or "Plan" in queries
    assert "deck" in queries
    assert "metrics" in queries


def test_initiator_confirm_card_contains_related_resources(client: TestClient) -> None:
    response = _submit_event_response(
        client,
        "evt-resource-initiator-card",
        "Please assign u_assignee to finish TeamTask resource review by 2026-06-01.",
    )

    card = response["initiator_card"]["card"]

    assert "related_resources" in card
    assert card["related_resources"]["status"] == "completed"
    assert card["related_resources"]["high_confidence"] or card["related_resources"]["low_confidence"]


def test_assignee_confirm_card_inherits_initiator_resources(client: TestClient) -> None:
    url = "https://example.feishu.cn/docx/inherited-resource"
    contract_id = _submit_event(
        client,
        "evt-resource-assignee-card",
        f"Please assign u_assignee to finish TeamTask resource review by 2026-06-01. See {url}",
    )

    response = _card_callback(client, "initiator_confirm", contract_id, "u_initiator")

    assert response.status_code == 200
    card = response.json()["assignee_card"]["card"]
    assert any(item["url"] == url for item in card["related_resources"]["high_confidence"])


def test_initiator_request_resource_search_updates_contract_resources(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _submit_event(
        client,
        "evt-resource-manual-search",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        contract.related_resources_json = {"high_confidence": [], "low_confidence": []}
        contract.resource_search_status = "not_started"
        contract.resource_keywords = ["manual-search"]
        db.commit()

    response = _card_callback(client, "initiator_request_resource_search", contract_id, "u_initiator")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resource_search_status"] == "completed"
    assert payload["related_resources"]["low_confidence"]
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        assert contract.resource_search_status == "completed"


def test_mock_resource_backend_does_not_call_lark_cli(
    client: TestClient,
    monkeypatch,
) -> None:
    def fail_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        raise AssertionError("subprocess.run should not be called by mock resource search")

    monkeypatch.setenv("RESOURCE_SEARCH_BACKEND", "mock")
    monkeypatch.setattr(subprocess, "run", fail_run)
    contract_id = _submit_event(
        client,
        "evt-resource-mock-no-cli",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )

    response = client.post(
        "/debug/resources/search",
        json={"contract_id": contract_id, "user_id": "u_initiator"},
    )

    assert response.status_code == 200
    assert response.json()["backend"] == "mock"


def test_lark_cli_resource_dry_run_does_not_call_external_search(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _submit_event(
        client,
        "evt-resource-lark-dry-run",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        settings = Settings(
            feishu_mock=False,
            lark_dry_run=True,
            resource_search_backend="lark_cli",
            resource_search_dry_run=True,
        )
        backend = LarkCliResourceSearchBackend(_FailingSearchClient(), settings)
        result = backend.search_resources("u_initiator", contract, contract.source_event)

    assert result.backend == "lark_cli"
    assert result.dry_run is True


def test_resource_search_failure_does_not_interrupt_task_confirmation(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    class FailingBackend:
        def search_resources(
            self,
            user_id: str,
            task_contract: TaskContract,
            source_event: object,
        ) -> ResourceSearchResult:
            raise RuntimeError("resource search unavailable")

    monkeypatch.setattr("app.main.create_resource_search_backend", lambda *args, **kwargs: FailingBackend())

    response = _submit_event_response(
        client,
        "evt-resource-failure-soft",
        "Please assign u_assignee to finish TeamTask review by 2026-06-01.",
    )

    assert response["contract_status"] == "pending_initiator_confirm"
    with session_factory() as db:
        contract = db.get(TaskContract, response["contract_id"])
        assert contract is not None
        assert contract.resource_search_status == "failed"
        assert "resource search unavailable" in (contract.resource_search_error or "")


class _FailingSearchClient(MockFeishuClient):
    def search_docs(self, user_id: str, query: str) -> list[dict[str, Any]]:
        raise AssertionError("search_docs should not run during resource dry-run")


def _submit_event(client: TestClient, event_id: str, text: str) -> int:
    return _submit_event_response(client, event_id, text)["contract_id"]


def _submit_event_response(client: TestClient, event_id: str, text: str) -> dict:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": text,
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask",
        },
    )
    assert response.status_code == 200
    return response.json()


def _card_callback(client: TestClient, action_key: str, contract_id: int, recipient_user_id: str):
    return client.post(
        "/feishu/card-callback",
        json={
            "action_key": action_key,
            "contract_id": contract_id,
            "recipient_user_id": recipient_user_id,
        },
    )
