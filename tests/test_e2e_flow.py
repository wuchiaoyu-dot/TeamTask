from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ChangeProposal, PersonalTodoProjection, SourceEvent, TaskContract


def test_group_message_to_active_task_e2e(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    event_response = _submit_group_message(client, "evt-e2e-active")

    assert event_response["contract_status"] == "pending_initiator_confirm"
    contract_id = event_response["contract_id"]

    initiator_response = _card_callback(client, "initiator_confirm", contract_id, "u_initiator")

    assert initiator_response.status_code == 200
    assert initiator_response.json()["status"] == "pending_assignee_confirm"

    with session_factory() as db:
        initiator_todo = _todo_for(db, contract_id, "u_initiator")

    assert initiator_todo is not None

    assignee_response = _card_callback(client, "assignee_accept", contract_id, "u_assignee")

    assert assignee_response.status_code == 200
    assert assignee_response.json()["status"] == "active"

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assignee_todo = _todo_for(db, contract_id, "u_assignee")
        todos = db.scalars(
            select(PersonalTodoProjection).where(PersonalTodoProjection.contract_id == contract_id)
        ).all()

    assert contract is not None
    assert contract.status == "active"
    assert assignee_todo is not None
    assert len(todos) == 2


def test_assignee_propose_deadline_change_creates_proposal(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, "evt-e2e-change")

    response = _card_callback(
        client,
        "assignee_propose_change",
        contract_id,
        "u_assignee",
        deadline="2026-06-15",
        reason="Need review buffer",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "change_pending_initiator_review"

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        proposal = db.scalar(select(ChangeProposal).where(ChangeProposal.contract_id == contract_id))

    assert contract is not None
    assert contract.deadline == date(2026, 6, 1)
    assert proposal is not None
    assert proposal.proposed_deadline == date(2026, 6, 15)


def test_card_callback_rejects_wrong_recipient_permissions(client: TestClient) -> None:
    event_response = _submit_group_message(client, "evt-e2e-permissions")
    contract_id = event_response["contract_id"]

    wrong_initiator = _card_callback(client, "initiator_confirm", contract_id, "u_assignee")
    assert wrong_initiator.status_code == 403

    right_initiator = _card_callback(client, "initiator_confirm", contract_id, "u_initiator")
    assert right_initiator.status_code == 200

    wrong_assignee = _card_callback(client, "assignee_accept", contract_id, "u_initiator")
    assert wrong_assignee.status_code == 403


def test_event_and_confirm_action_idempotency(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    first = _submit_group_message(client, "evt-e2e-dedup")
    second = _submit_group_message(client, "evt-e2e-dedup")

    assert second["deduplicated"] is True
    assert second["contract_id"] == first["contract_id"]
    contract_id = first["contract_id"]

    first_confirm = _card_callback(client, "initiator_confirm", contract_id, "u_initiator")
    second_confirm = _card_callback(client, "initiator_confirm", contract_id, "u_initiator")

    assert first_confirm.status_code == 200
    assert second_confirm.status_code == 200
    assert second_confirm.json()["status"] == "pending_assignee_confirm"

    with session_factory() as db:
        source_events = db.scalars(
            select(SourceEvent).where(SourceEvent.external_event_id == "evt-e2e-dedup")
        ).all()
        contracts = db.scalars(
            select(TaskContract).where(TaskContract.source_event_id == source_events[0].id)
        ).all()
        initiator_todos = db.scalars(
            select(PersonalTodoProjection).where(
                PersonalTodoProjection.contract_id == contract_id,
                PersonalTodoProjection.owner_user_id == "u_initiator",
            )
        ).all()

    assert len(source_events) == 1
    assert len(contracts) == 1
    assert len(initiator_todos) == 1


def _submit_group_message(client: TestClient, event_id: str) -> dict:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": "Please assign u_assignee to finish the TeamTask E2E task by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask",
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_active_contract(client: TestClient, event_id: str) -> int:
    event_response = _submit_group_message(client, event_id)
    contract_id = event_response["contract_id"]
    response = _card_callback(client, "initiator_confirm", contract_id, "u_initiator")
    assert response.status_code == 200
    response = _card_callback(client, "assignee_accept", contract_id, "u_assignee")
    assert response.status_code == 200
    return contract_id


def _card_callback(
    client: TestClient,
    action_key: str,
    contract_id: int,
    recipient_user_id: str,
    **extra: object,
):
    return client.post(
        "/feishu/card-callback",
        json={
            "action_key": action_key,
            "contract_id": contract_id,
            "recipient_user_id": recipient_user_id,
            **extra,
        },
    )


def _todo_for(db: Session, contract_id: int, owner_user_id: str) -> PersonalTodoProjection | None:
    return db.scalar(
        select(PersonalTodoProjection).where(
            PersonalTodoProjection.contract_id == contract_id,
            PersonalTodoProjection.owner_user_id == owner_user_id,
        )
    )
