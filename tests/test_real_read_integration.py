from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.external_read_guard import mask_sensitive_resource_id, should_allow_external_read
from app.models import SourceEvent, TaskContract
from app.services.minutes_backend import LarkCliMinutesBackend, parse_lark_cli_minutes_output
from app.services.resource_search_backend import (
    LarkCliResourceSearchBackend,
    normalize_resource_result,
    parse_lark_cli_search_output,
)


def test_feishu_mock_true_forbids_real_read() -> None:
    settings = Settings(feishu_mock=True, lark_dry_run=False, feishu_enable_real_read=True)

    assert should_allow_external_read(settings) is False


def test_lark_dry_run_minutes_returns_would_read_without_subprocess(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("LARK_DRY_RUN", "true")
    monkeypatch.setenv("MINUTES_BACKEND", "lark_cli")
    monkeypatch.setenv("MINUTES_DRY_RUN", "true")
    monkeypatch.setattr(subprocess, "run", _fail_subprocess_run)
    _grant_scopes(client, "u_reader", ["minutes:read"])

    response = client.post(
        "/debug/minutes/read-real",
        json={"minutes_token_or_url": "minutes_secure_token_123456", "user_id": "u_reader"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["would_read"] is True
    assert payload["allowed"] is False
    assert payload["minutes_content"]["raw_payload"]["would_read"] is True
    assert payload["minutes_content"]["raw_payload"]["dry_run"] is True


def test_lark_dry_run_resource_search_returns_would_search_without_subprocess(
    client: TestClient,
    monkeypatch,
) -> None:
    contract_id = _submit_event(client, "evt-real-read-resource-dry-run")
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("LARK_DRY_RUN", "true")
    monkeypatch.setenv("RESOURCE_SEARCH_BACKEND", "lark_cli")
    monkeypatch.setenv("RESOURCE_SEARCH_DRY_RUN", "true")
    monkeypatch.setattr(subprocess, "run", _fail_subprocess_run)
    _grant_scopes(client, "u_initiator", ["docs:read", "minutes:read", "drive:read", "base:read"])

    response = client.post(
        "/debug/resources/search-real",
        json={"contract_id": contract_id, "user_id": "u_initiator"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["would_search"] is True
    assert payload["allowed"] is False
    assert payload["backend"] == "lark_cli"
    assert payload["dry_run"] is True


def test_feishu_enable_real_read_false_forbids_external_read() -> None:
    settings = Settings(feishu_mock=False, lark_dry_run=False, feishu_enable_real_read=False)

    assert should_allow_external_read(settings) is False


def test_test_environment_forbids_external_read(monkeypatch) -> None:
    monkeypatch.setenv("TEAMTASK_SKIP_DB_INIT", "1")
    settings = Settings(
        feishu_mock=False,
        lark_dry_run=False,
        feishu_enable_real_read=True,
        lark_cli_path="lark-cli",
    )

    assert should_allow_external_read(settings) is False


def test_no_user_auth_grants_cannot_read_private_minutes(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("FEISHU_ENABLE_REAL_READ", "true")
    monkeypatch.setenv("LARK_DRY_RUN", "false")

    response = client.post(
        "/debug/minutes/read-real",
        json={"minutes_token_or_url": "minutes_private_token", "user_id": "u_no_grant"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is False
    assert "minutes:read" in payload["missing_scopes"]
    assert payload["minutes_content"] is None


def test_missing_required_scopes_are_reported(client: TestClient) -> None:
    _grant_scopes(client, "u_scope_test", ["docs:read"])

    response = client.post(
        "/debug/auth/scopes",
        json={"user_id": "u_scope_test", "required_scopes": ["minutes:read", "docs:read"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_required_scopes"] is False
    assert payload["missing_scopes"] == ["minutes:read"]
    assert any(grant["scope"] == "docs:read" for grant in payload["current_grants"])


def test_parse_lark_cli_minutes_output_parses_mock_raw_output() -> None:
    content = parse_lark_cli_minutes_output(
        {
            "data": {
                "minutes_token": "token_should_not_log",
                "title": "Launch Review",
                "meeting_start_time": "2026-05-04T10:00:00+08:00",
                "participants": ["u_alice", "u_bob"],
                "summary": "Reviewed launch plan.",
                "todos": "- u_bob finish rollout checklist",
                "transcript": {
                    "segments": [
                        {"speaker_name": "u_alice", "content": "Please finish the rollout checklist."},
                        {"speaker_name": "u_bob", "content": "I will do it."},
                    ]
                },
                "url": "https://example.feishu.cn/minutes/mincnxxxx",
            }
        }
    )

    assert content.title == "Launch Review"
    assert content.participants == ["u_alice", "u_bob"]
    assert "u_alice: Please finish" in content.transcript_text
    assert content.todos_text == "- u_bob finish rollout checklist"


def test_parse_lark_cli_search_output_parses_mock_search_output() -> None:
    results = parse_lark_cli_search_output(
        json.dumps(
            {
                "data": {
                    "items": [
                        {
                            "title": "Launch Plan",
                            "url": "https://example.feishu.cn/docx/doc-token",
                            "type": "doc",
                            "score": 0.84,
                            "owner": "u_owner",
                        }
                    ]
                }
            }
        )
    )
    normalized = normalize_resource_result(results[0])

    assert normalized["title"] == "Launch Plan"
    assert normalized["url"].endswith("doc-token")
    assert normalized["source_type"] == "semantic_match"
    assert normalized["owner"] == "u_owner"


def test_lark_cli_resource_search_deduplicates_by_url(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    contract_id = _submit_event(client, "evt-real-read-dedupe")
    monkeypatch.setattr("app.services.resource_search_backend.should_allow_external_read", lambda settings: True)

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        output = {
            "data": {
                "items": [
                    {
                        "title": "Launch Plan",
                        "url": "https://example.feishu.cn/docx/same-token",
                        "type": "doc",
                        "score": 0.88,
                    },
                    {
                        "title": "Launch Plan Duplicate",
                        "url": "https://example.feishu.cn/docx/same-token",
                        "type": "doc",
                        "score": 0.77,
                    },
                ]
            }
        }
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=json.dumps(output), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    settings = Settings(
        feishu_mock=False,
        lark_dry_run=False,
        feishu_enable_real_read=True,
        resource_search_backend="lark_cli",
        resource_search_dry_run=False,
        resource_search_sources=("docs",),
        lark_cli_path="lark-cli",
    )

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        backend = LarkCliResourceSearchBackend(_NoopFeishuClient(), settings)
        result = backend.search_resources("u_initiator", contract, contract.source_event)

    assert [item["url"] for item in result.raw_results] == ["https://example.feishu.cn/docx/same-token"]


def test_resource_search_failure_does_not_interrupt_confirmation_flow(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    class FailingBackend:
        def search_resources(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("real search unavailable")

    monkeypatch.setattr("app.main.create_resource_search_backend", lambda *args, **kwargs: FailingBackend())

    response = _submit_event_response(client, "evt-real-read-search-fail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_status"] == "pending_initiator_confirm"
    with session_factory() as db:
        contract = db.get(TaskContract, payload["contract_id"])
        assert contract is not None
        assert contract.resource_search_status == "failed"
        assert contract.resource_search_error == "real search unavailable"


def test_minutes_read_failure_does_not_create_empty_task_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    class FailingMinutesBackend:
        def get_minutes_content(self, minutes_token_or_url: str) -> Any:
            raise RuntimeError("minutes API unavailable")

    monkeypatch.setattr("app.main.create_minutes_backend", lambda *args, **kwargs: FailingMinutesBackend())

    response = client.post(
        "/feishu/events",
        json={
            "event_id": "evt-real-read-minutes-fail",
            "event_type": "meeting_minutes",
            "text": "https://example.feishu.cn/minutes/mincn-failure-token",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
        },
    )

    assert response.status_code == 502
    assert "Please paste meeting notes manually" in response.json()["detail"]
    with session_factory() as db:
        assert db.scalar(select(TaskContract).where(TaskContract.source_event_id.is_not(None))) is None
        assert db.scalar(select(SourceEvent).where(SourceEvent.external_event_id == "evt-real-read-minutes-fail")) is None


def test_sensitive_resource_ids_are_masked_in_logs(caplog) -> None:
    token = "minutes_secret_token_abcdef123456"
    caplog.set_level(logging.INFO)
    settings = Settings(feishu_mock=False, lark_dry_run=True, minutes_backend="lark_cli", minutes_dry_run=True)
    backend = LarkCliMinutesBackend(settings)

    backend.get_minutes_content(token)

    assert token not in caplog.text
    assert mask_sensitive_resource_id(token) in caplog.text
    assert "minutes_secret_token_abcdef123456" not in caplog.text


class _NoopFeishuClient:
    def search_docs(self, user_id: str, query: str) -> list[dict[str, Any]]:
        return []


def _fail_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    raise AssertionError("subprocess.run should not be called in mock or dry-run mode")


def _submit_event(client: TestClient, event_id: str) -> int:
    response = _submit_event_response(client, event_id)
    assert response.status_code == 200
    return response.json()["contract_id"]


def _submit_event_response(client: TestClient, event_id: str):
    return client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": "Please assign u_assignee to finish TeamTask launch review by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask",
        },
    )


def _grant_scopes(client: TestClient, user_id: str, scopes: list[str]) -> None:
    for scope in scopes:
        response = client.post("/dev/auth-grants", json={"user_id": user_id, "scope": scope})
        assert response.status_code == 200
