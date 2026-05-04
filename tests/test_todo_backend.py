from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.clients.feishu_client import FeishuClient, MockFeishuClient
from app.config import Settings, get_settings
from app.models import PersonalTodoProjection, TaskContract
from app.services.todo_backend import BitableTodoBackend, MockTodoBackend, create_todo_backend
from app.services.todo_field_mapper import map_contract_to_bitable_fields


def test_feishu_mock_true_uses_mock_todo_backend(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_MOCK", "true")
    monkeypatch.setenv("TODO_BACKEND", "bitable")

    backend = create_todo_backend(MockFeishuClient(), get_settings())

    assert isinstance(backend, MockTodoBackend)
    assert backend.provider == "mock"


def test_bitable_dry_run_does_not_call_external_write() -> None:
    settings = Settings(
        feishu_mock=False,
        lark_dry_run=True,
        todo_backend="bitable",
        feishu_bitable_app_token="app_token",
        feishu_bitable_table_id="tbl",
    )
    backend = BitableTodoBackend(_FailingBitableClient(), settings)
    contract = _contract_stub()

    record_id = backend.create_personal_todo_projection("u_initiator", contract, "initiator")

    assert record_id == "dry_run_record_u_initiator_1_initiator"


def test_initiator_confirm_creates_projection_with_external_record_id(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_candidate_contract(client, "evt-backend-init")

    response = _callback(client, "initiator_confirm", contract_id, "u_initiator")

    assert response.status_code == 200
    with session_factory() as db:
        projection = _projection(db, contract_id, "u_initiator")

    assert projection is not None
    assert projection.role == "initiator"
    assert projection.todo_provider == "mock"
    assert projection.external_record_id == f"mock_record_u_initiator_{contract_id}_initiator"
    assert projection.last_synced_at is not None


def test_assignee_accept_creates_projection_with_external_record_id(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_pending_assignee_contract(client, "evt-backend-assignee")

    response = _callback(client, "assignee_accept", contract_id, "u_assignee")

    assert response.status_code == 200
    with session_factory() as db:
        projection = _projection(db, contract_id, "u_assignee")

    assert projection is not None
    assert projection.role == "assignee"
    assert projection.external_record_id == f"mock_record_u_assignee_{contract_id}_assignee"


def test_repeated_initiator_confirm_does_not_create_duplicate_projection(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_candidate_contract(client, "evt-backend-init-repeat")

    first = _callback(client, "initiator_confirm", contract_id, "u_initiator")
    second = _callback(client, "initiator_confirm", contract_id, "u_initiator")

    assert first.status_code == 200
    assert second.status_code == 200
    with session_factory() as db:
        projections = db.scalars(
            select(PersonalTodoProjection).where(
                PersonalTodoProjection.contract_id == contract_id,
                PersonalTodoProjection.owner_user_id == "u_initiator",
            )
        ).all()

    assert len(projections) == 1


def test_repeated_assignee_accept_does_not_create_duplicate_projection(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_pending_assignee_contract(client, "evt-backend-assignee-repeat")

    first = _callback(client, "assignee_accept", contract_id, "u_assignee")
    second = _callback(client, "assignee_accept", contract_id, "u_assignee")

    assert first.status_code == 200
    assert second.status_code == 200
    with session_factory() as db:
        projections = db.scalars(
            select(PersonalTodoProjection).where(
                PersonalTodoProjection.contract_id == contract_id,
                PersonalTodoProjection.owner_user_id == "u_assignee",
            )
        ).all()

    assert len(projections) == 1


def test_propose_change_does_not_update_external_todo_until_approval(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, "evt-backend-propose")
    with session_factory() as db:
        before = _projection(db, contract_id, "u_assignee")
        assert before is not None
        before_external = before.external_record_id
        before_synced_at = before.last_synced_at

    response = _callback(
        client,
        "assignee_propose_change",
        contract_id,
        "u_assignee",
        deadline="2026-06-15",
        reason="Need review buffer",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        after = _projection(db, contract_id, "u_assignee")

    assert contract is not None
    assert contract.deadline == date(2026, 6, 1)
    assert after is not None
    assert after.external_record_id == before_external
    assert after.last_synced_at == before_synced_at


def test_change_proposal_approve_updates_existing_projections(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, "evt-backend-approve")
    propose = _callback(
        client,
        "assignee_propose_change",
        contract_id,
        "u_assignee",
        deadline="2026-06-15",
        reason="Need review buffer",
    )
    proposal_id = propose.json()["change_proposal_id"]

    approve = _callback(
        client,
        "change_proposal_approve",
        contract_id,
        "u_initiator",
        proposal_id=proposal_id,
    )

    assert approve.status_code == 200
    assert approve.json()["proposal_status"] == "approved"
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        initiator = _projection(db, contract_id, "u_initiator")
        assignee = _projection(db, contract_id, "u_assignee")

    assert contract is not None
    assert contract.deadline == date(2026, 6, 15)
    assert initiator is not None and initiator.deadline == date(2026, 6, 15)
    assert assignee is not None and assignee.deadline == date(2026, 6, 15)
    assert initiator.last_synced_at is not None
    assert assignee.last_synced_at is not None


def test_field_mapping_uses_configurable_field_names(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_TODO_TITLE_FIELD", "Custom Title")
    monkeypatch.setenv("FEISHU_TODO_DEADLINE_FIELD", "Custom Deadline")
    settings = get_settings()
    contract = _contract_stub()

    fields = map_contract_to_bitable_fields("u_initiator", contract, "initiator", settings)

    assert "Custom Title" in fields
    assert "Custom Deadline" in fields
    assert "任务标题" not in fields
    assert fields["Custom Title"] == "Stub task"


def _create_candidate_contract(client: TestClient, event_id: str) -> int:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": "Please assign u_assignee to finish backend projection task by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
        },
    )
    assert response.status_code == 200
    return response.json()["contract_id"]


def _create_pending_assignee_contract(client: TestClient, event_id: str) -> int:
    contract_id = _create_candidate_contract(client, event_id)
    response = _callback(client, "initiator_confirm", contract_id, "u_initiator")
    assert response.status_code == 200
    return contract_id


def _create_active_contract(client: TestClient, event_id: str) -> int:
    contract_id = _create_pending_assignee_contract(client, event_id)
    response = _callback(client, "assignee_accept", contract_id, "u_assignee")
    assert response.status_code == 200
    return contract_id


def _callback(client: TestClient, action_key: str, contract_id: int, recipient_user_id: str, **extra: Any):
    return client.post(
        "/feishu/card-callback",
        json={
            "action_key": action_key,
            "contract_id": contract_id,
            "recipient_user_id": recipient_user_id,
            **extra,
        },
    )


def _projection(db: Session, contract_id: int, owner_user_id: str) -> PersonalTodoProjection | None:
    return db.scalar(
        select(PersonalTodoProjection).where(
            PersonalTodoProjection.contract_id == contract_id,
            PersonalTodoProjection.owner_user_id == owner_user_id,
        )
    )


def _contract_stub() -> TaskContract:
    contract = TaskContract(
        id=1,
        source_event_id=1,
        status="active",
        title="Stub task",
        description="Stub description",
        initiator_user_id="u_initiator",
        assignee_user_id="u_assignee",
        deadline=date(2026, 6, 1),
        evidence=["line 1", "line 2"],
        resource_keywords=["design"],
        mentioned_resources=["https://example.com/doc"],
    )
    return contract


class _FailingBitableClient(FeishuClient):
    def create_bitable_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("Dry-run should not call create_bitable_record")

    def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        raise AssertionError("Dry-run should not call update_bitable_record")

    def get_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        raise AssertionError("Not used")

    def send_message(self, user_id: str, text: str) -> dict[str, Any]:
        raise AssertionError("Not used")

    def send_card(self, user_id: str, card_json: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("Not used")

    def send_group_message(self, chat_id: str, text: str) -> dict[str, Any]:
        raise AssertionError("Not used")

    def get_minutes_transcript(self, minutes_token: str) -> dict[str, Any]:
        raise AssertionError("Not used")

    def search_docs(self, user_id: str, query: str) -> list[dict[str, Any]]:
        raise AssertionError("Not used")

    def create_todo_projection(self, user_id: str, task_contract: TaskContract) -> dict[str, Any]:
        raise AssertionError("Not used")

    def update_todo_projection(self, user_id: str, contract_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("Not used")
