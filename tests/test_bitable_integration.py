from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.clients.bitable_client import BitableClient, LarkCliBitableClient, MockBitableClient, create_bitable_client
from app.config import Settings, get_settings, validate_bitable_config
from app.core.external_write_guard import should_allow_external_write
from app.models import PersonalTodoProjection, TaskContract
from app.services.reconciliation_service import start_reconciliation
from app.services.todo_backend import BitableTodoBackend
from app.services.todo_field_mapper import map_bitable_record_to_snapshot


def test_feishu_mock_true_uses_mock_bitable_client(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_MOCK", "true")

    client = create_bitable_client(get_settings())

    assert isinstance(client, MockBitableClient)


def test_lark_dry_run_create_record_returns_dry_run_record_id() -> None:
    settings = Settings(feishu_mock=False, lark_dry_run=True, todo_backend="bitable")
    client = LarkCliBitableClient(settings)

    record_id = client.create_record("app_token_secret", "tbl", {"Title": "Task"})

    assert record_id.startswith("dry_run_record_")


def test_validate_bitable_config_reports_missing_required_values() -> None:
    settings = Settings(feishu_mock=False, lark_dry_run=False, todo_backend="bitable")

    with pytest.raises(ValueError) as exc:
        validate_bitable_config(settings)

    assert "FEISHU_BITABLE_APP_TOKEN" in str(exc.value)
    assert "FEISHU_BITABLE_TABLE_ID" in str(exc.value)


def test_bitable_backend_create_calls_bitable_client(monkeypatch) -> None:
    settings = _real_write_settings()
    spy = _SpyBitableClient()
    monkeypatch.setattr("app.services.todo_backend.should_allow_external_write", lambda settings=None: True)
    backend = BitableTodoBackend(spy, settings)

    record_id = backend.create_personal_todo_projection("u_initiator", _contract_stub(), "initiator")

    assert record_id == "rec_created"
    assert spy.created_fields
    assert spy.created_fields["Title"] == "Stub task"


def test_bitable_backend_update_calls_bitable_client(monkeypatch) -> None:
    settings = _real_write_settings()
    spy = _SpyBitableClient()
    monkeypatch.setattr("app.services.todo_backend.should_allow_external_write", lambda settings=None: True)
    backend = BitableTodoBackend(spy, settings)

    backend.update_personal_todo_projection("u_assignee", "rec_1", {"progress_text": "Done", "completion_status": "completed"})

    assert spy.updated_record_id == "rec_1"
    assert spy.updated_fields["progress_text"] == "Done"
    assert spy.updated_fields["Status"] == "completed"


def test_bitable_backend_get_projection_snapshot_maps_record() -> None:
    settings = _real_write_settings()
    spy = _SpyBitableClient()
    spy.records["rec_1"] = {
        "record_id": "rec_1",
        "fields": {
            "Title": "Mapped title",
            "Description": "Mapped description",
            "Deadline": _millis(date(2026, 6, 1)),
            "Status": "in_progress",
            "progress_text": "Half done",
        },
    }
    backend = BitableTodoBackend(spy, settings)

    snapshot = backend.get_projection_snapshot("u_assignee", "rec_1")

    assert spy.got_record_id == "rec_1"
    assert snapshot["title"] == "Mapped title"
    assert snapshot["deadline"] == "2026-06-01"
    assert snapshot["progress_text"] == "Half done"
    assert snapshot["completion_status"] == "in_progress"


def test_map_bitable_record_to_snapshot_maps_deadline_progress_and_status() -> None:
    settings = _real_write_settings()
    record = {
        "record_id": "rec_2",
        "fields": {
            "Title": "Snapshot task",
            "Deadline": _millis(date(2026, 5, 8)),
            "Status": "blocked",
            "progress_text": "Waiting on data",
        },
    }

    snapshot = map_bitable_record_to_snapshot(record, settings)

    assert snapshot["title"] == "Snapshot task"
    assert snapshot["deadline"] == "2026-05-08"
    assert snapshot["completion_status"] == "blocked"
    assert snapshot["progress_text"] == "Waiting on data"


def test_should_allow_external_write_false_in_mock_and_dry_run() -> None:
    assert should_allow_external_write(Settings(feishu_mock=True, lark_dry_run=False, todo_backend="bitable")) is False
    assert should_allow_external_write(Settings(feishu_mock=False, lark_dry_run=True, todo_backend="bitable")) is False


def test_debug_bitable_create_real_does_not_write_in_mock_or_dry_run(
    client: TestClient,
) -> None:
    contract_id = _create_candidate_contract(client, "evt-bitable-debug-create")

    response = client.post(
        "/debug/bitable/create-real",
        json={"contract_id": contract_id, "owner_user_id": "u_initiator", "role": "initiator"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["would_write"] is True
    assert body["external_write_allowed"] is False
    assert body["record_id"].startswith("dry_run_record_")
    assert body["fields"]


def test_lark_cli_bitable_logs_redact_token_and_secret(caplog) -> None:
    settings = Settings(feishu_mock=False, lark_dry_run=True, todo_backend="bitable")
    client = LarkCliBitableClient(settings)

    with caplog.at_level(logging.INFO):
        client.create_record("app_token_secret_123", "tbl", {"app_secret": "secret_456", "Title": "Task"})

    logs = caplog.text
    assert "app_token_secret_123" not in logs
    assert "secret_456" not in logs
    assert "<redacted>" in logs


def test_reconciliation_service_uses_bitable_snapshot_for_diff(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-bitable-reconcile")
    _grant_pair(client)
    with session_factory() as db:
        initiator = _projection(db, contract_id, "u_initiator")
        assignee = _projection(db, contract_id, "u_assignee")
        assert initiator is not None
        assert assignee is not None
        initiator.external_record_id = "rec_init"
        assignee.external_record_id = "rec_assignee"
        db.commit()

    with session_factory() as db:
        run = start_reconciliation(
            db,
            todo_backend=_SnapshotTodoBackend(),
            requester_user_id="u_initiator",
            scope="single_task",
            contract_id=contract_id,
        )
        db.commit()
        item = run.items[0]

    assert item.diff_status == "has_diff"
    assert "progress_text" in item.field_diffs_json


class _SpyBitableClient(BitableClient):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.created_fields: dict[str, Any] = {}
        self.updated_fields: dict[str, Any] = {}
        self.updated_record_id: str | None = None
        self.got_record_id: str | None = None

    def create_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> str:
        self.created_fields = fields
        self.records["rec_created"] = {"record_id": "rec_created", "fields": fields}
        return "rec_created"

    def update_record(self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        self.updated_record_id = record_id
        self.updated_fields = fields

    def get_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        self.got_record_id = record_id
        return self.records[record_id]

    def search_records(self, app_token: str, table_id: str, filter_expr: str) -> list[dict[str, Any]]:
        return list(self.records.values())


class _SnapshotTodoBackend:
    provider = "snapshot"

    def create_personal_todo_projection(self, owner_user_id: str, contract: TaskContract, role: str) -> str:
        raise AssertionError("Not used")

    def update_personal_todo_projection(self, owner_user_id: str, external_record_id: str, patch: dict[str, Any]) -> None:
        raise AssertionError("Not used")

    def find_existing_projection(self, owner_user_id: str, contract_id: int) -> str | None:
        return None

    def get_personal_todo(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        return self.get_projection_snapshot(owner_user_id, external_record_id)

    def get_projection_snapshot(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        if owner_user_id == "u_initiator":
            return {"record_id": external_record_id, "progress_text": "", "completion_status": "in_progress"}
        return {"record_id": external_record_id, "progress_text": "External progress", "completion_status": "in_progress"}


def _real_write_settings() -> Settings:
    return Settings(
        feishu_mock=False,
        lark_dry_run=False,
        todo_backend="bitable",
        feishu_bitable_app_token="app_token",
        feishu_bitable_table_id="tbl",
        lark_cli_path="lark-cli",
        feishu_todo_title_field="Title",
        feishu_todo_description_field="Description",
        feishu_todo_status_field="Status",
        feishu_todo_deadline_field="Deadline",
        feishu_todo_resource_field="Resources",
        feishu_todo_evidence_field="Evidence",
    )


def _millis(value: date) -> int:
    return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp() * 1000)


def _contract_stub() -> TaskContract:
    return TaskContract(
        id=1,
        source_event_id=1,
        status="active",
        title="Stub task",
        description="Stub description",
        initiator_user_id="u_initiator",
        assignee_user_id="u_assignee",
        deadline=date(2026, 6, 1),
    )


def _create_candidate_contract(client: TestClient, event_id: str) -> int:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": "Please assign u_assignee to finish Bitable integration by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
        },
    )
    assert response.status_code == 200
    return response.json()["contract_id"]


def _create_active_contract(client: TestClient, session_factory: sessionmaker[Session], event_id: str) -> int:
    contract_id = _create_candidate_contract(client, event_id)
    response = client.post(
        "/feishu/card-callback",
        json={"action_key": "initiator_confirm", "contract_id": contract_id, "recipient_user_id": "u_initiator"},
    )
    assert response.status_code == 200
    response = client.post(
        "/feishu/card-callback",
        json={"action_key": "assignee_accept", "contract_id": contract_id, "recipient_user_id": "u_assignee"},
    )
    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        contract.title = "Bitable integration"
        db.commit()
    return contract_id


def _grant_pair(client: TestClient) -> None:
    for user_id, subject_id in (("u_initiator", "u_assignee"), ("u_assignee", "u_initiator")):
        response = client.post(
            "/dev/auth-grants",
            json={
                "user_id": user_id,
                "scope": "progress_reconcile",
                "subject_type": "user",
                "subject_id": subject_id,
            },
        )
        assert response.status_code == 200


def _projection(db: Session, contract_id: int, owner_user_id: str) -> PersonalTodoProjection | None:
    return db.scalar(
        select(PersonalTodoProjection).where(
            PersonalTodoProjection.contract_id == contract_id,
            PersonalTodoProjection.owner_user_id == owner_user_id,
        )
    )
