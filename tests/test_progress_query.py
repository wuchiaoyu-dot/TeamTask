from __future__ import annotations

import subprocess
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CardAction, ChangeProposal, PersonalTodoProjection, ProgressQuery, TaskContract


def test_ask_progress_message_does_not_create_new_task_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-progress-base", "Competitive analysis")
    with session_factory() as db:
        before_count = len(db.scalars(select(TaskContract)).all())

    response = _submit_progress_event(
        client,
        "evt-progress-ask-no-new-task",
        "Is u_assignee Competitive analysis done?",
    )

    assert response.status_code == 200
    assert response.json()["intent"] == "ask_progress"
    assert response.json()["contract_id"] == contract_id
    with session_factory() as db:
        after_count = len(db.scalars(select(TaskContract)).all())
        progress_query = db.get(ProgressQuery, response.json()["progress_query_id"])

    assert after_count == before_count
    assert progress_query is not None
    assert progress_query.query_status == "pending_assignee_confirm"


def test_progress_query_matches_unique_task_by_assignee_and_keyword(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-progress-unique", "Launch checklist")

    response = client.post(
        "/debug/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "Is u_assignee Launch checklist done?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched_contracts"][0]["contract_id"] == contract_id
    assert body["generated_card_json"]["card_type"] == "progress_confirm"


def test_multiple_progress_matches_generate_task_select_card(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    first_id = _create_active_contract(client, session_factory, "evt-progress-multi-1", "Competitive analysis A")
    second_id = _create_active_contract(client, session_factory, "evt-progress-multi-2", "Competitive analysis B")

    response = client.post(
        "/debug/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "Is u_assignee Competitive analysis done?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert {item["contract_id"] for item in body["matched_contracts"]} == {first_id, second_id}
    assert body["generated_card_json"]["card_type"] == "progress_task_select"


def test_progress_query_without_match_returns_no_matching_task(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _create_active_contract(client, session_factory, "evt-progress-no-match-base", "Known task")

    response = client.post(
        "/debug/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "Is u_assignee impossible migration done?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched_contracts"] == []
    assert body["progress_query_status"] == "no_matching_task"
    assert "reported" in body["response_summary"]


def test_only_assignee_can_click_progress_confirm_action(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-permission",
        "Permission task",
    )

    response = _progress_callback(
        client,
        "progress_mark_completed",
        contract_id,
        "u_other",
        progress_query_id,
        progress_text="Done",
    )

    assert response.status_code == 403


def test_requester_cannot_mark_assignee_task_completed(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-requester-forbidden",
        "Requester task",
    )

    response = _progress_callback(
        client,
        "progress_mark_completed",
        contract_id,
        "u_initiator",
        progress_query_id,
        progress_text="Done",
    )

    assert response.status_code == 403


def test_progress_mark_completed_updates_completion_status_and_assignee_projection(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-completed",
        "Completion task",
    )

    response = _progress_callback(
        client,
        "progress_mark_completed",
        contract_id,
        "u_assignee",
        progress_query_id,
        progress_text="All done.",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        projection = _assignee_projection(db, contract_id)

    assert contract is not None
    assert contract.status == "completed"
    assert contract.completion_status == "completed"
    assert contract.progress_text == "All done."
    assert projection is not None
    assert projection.status == "completed"


def test_progress_mark_in_progress_updates_progress_text(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-in-progress",
        "In progress task",
    )

    response = _progress_callback(
        client,
        "progress_mark_in_progress",
        contract_id,
        "u_assignee",
        progress_query_id,
        progress_text="Draft is 60 percent complete.",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)

    assert contract is not None
    assert contract.status == "progress_updated"
    assert contract.completion_status == "in_progress"
    assert contract.progress_text == "Draft is 60 percent complete."


def test_progress_mark_blocked_records_block_reason(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-blocked",
        "Blocked task",
    )

    response = _progress_callback(
        client,
        "progress_mark_blocked",
        contract_id,
        "u_assignee",
        progress_query_id,
        progress_text="Blocked by missing data access.",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)

    assert contract is not None
    assert contract.completion_status == "blocked"
    assert contract.progress_text == "Blocked by missing data access."


def test_progress_mark_delayed_with_new_deadline_creates_change_proposal(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-delayed",
        "Delayed task",
    )

    response = _progress_callback(
        client,
        "progress_mark_delayed",
        contract_id,
        "u_assignee",
        progress_query_id,
        progress_text="Need another review cycle.",
        new_deadline="2026-06-15",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        proposal = db.scalar(select(ChangeProposal).where(ChangeProposal.contract_id == contract_id))

    assert contract is not None
    assert contract.deadline == date(2026, 6, 1)
    assert contract.completion_status == "delayed"
    assert contract.status == "change_pending_initiator_review"
    assert proposal is not None
    assert proposal.proposed_deadline == date(2026, 6, 15)


def test_repeated_progress_confirm_action_is_idempotent(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-idempotent",
        "Idempotent task",
    )

    first = _progress_callback(
        client,
        "progress_mark_in_progress",
        contract_id,
        "u_assignee",
        progress_query_id,
        progress_text="First update.",
    )
    second = _progress_callback(
        client,
        "progress_mark_in_progress",
        contract_id,
        "u_assignee",
        progress_query_id,
        progress_text="Second update should be ignored.",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        actions = db.scalars(
            select(CardAction).where(
                CardAction.contract_id == contract_id,
                CardAction.action_key == "progress_mark_in_progress",
            )
        ).all()

    assert contract is not None
    assert contract.progress_text == "First update."
    assert len(actions) == 1


def test_feishu_mock_true_progress_query_does_not_call_lark_cli(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    def fail_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        raise AssertionError("subprocess.run should not be called in FEISHU_MOCK=true")

    monkeypatch.setattr(subprocess, "run", fail_run)
    _create_active_contract(client, session_factory, "evt-progress-mock-safe", "Mock safe task")

    response = _submit_progress_event(
        client,
        "evt-progress-mock-safe-query",
        "Is u_assignee Mock safe task done?",
    )

    assert response.status_code == 200
    assert response.json()["progress_query_status"] == "pending_assignee_confirm"


def test_lark_dry_run_true_progress_update_does_not_real_write_external_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    contract_id, progress_query_id = _create_progress_query(
        client,
        session_factory,
        "evt-progress-dry-run",
        "Dry run task",
    )
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("TODO_BACKEND", "bitable")
    monkeypatch.setenv("LARK_DRY_RUN", "true")

    response = client.post(
        "/debug/progress/confirm",
        json={
            "progress_query_id": progress_query_id,
            "assignee_user_id": "u_assignee",
            "action_key": "progress_mark_in_progress",
            "progress_text": "Dry-run update.",
        },
    )

    assert response.status_code == 200
    with session_factory() as db:
        projection = _assignee_projection(db, contract_id)

    assert projection is not None
    assert projection.status == "in_progress"


def _create_progress_query(
    client: TestClient,
    session_factory: sessionmaker[Session],
    event_id: str,
    title: str,
) -> tuple[int, int]:
    contract_id = _create_active_contract(client, session_factory, event_id, title)
    response = client.post(
        "/debug/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": f"Is u_assignee {title} done?",
        },
    )
    assert response.status_code == 200
    return contract_id, response.json()["progress_query_id"]


def _create_active_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
    event_id: str,
    title: str,
) -> int:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": f"Please assign u_assignee to finish {title} by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask",
        },
    )
    assert response.status_code == 200
    contract_id = response.json()["contract_id"]
    response = client.post(
        "/feishu/card-callback",
        json={
            "action_key": "initiator_confirm",
            "contract_id": contract_id,
            "recipient_user_id": "u_initiator",
        },
    )
    assert response.status_code == 200
    response = client.post(
        "/feishu/card-callback",
        json={
            "action_key": "assignee_accept",
            "contract_id": contract_id,
            "recipient_user_id": "u_assignee",
        },
    )
    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        assert contract is not None
        contract.title = title
        contract.description = f"{title} details"
        contract.deadline = date(2026, 6, 1)
        db.commit()
    return contract_id


def _submit_progress_event(client: TestClient, event_id: str, text: str):
    return client.post(
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


def _progress_callback(
    client: TestClient,
    action_key: str,
    contract_id: int,
    recipient_user_id: str,
    progress_query_id: int,
    **extra: object,
):
    return client.post(
        "/feishu/card-callback",
        json={
            "action_key": action_key,
            "contract_id": contract_id,
            "recipient_user_id": recipient_user_id,
            "progress_query_id": progress_query_id,
            **extra,
        },
    )


def _assignee_projection(db: Session, contract_id: int) -> PersonalTodoProjection | None:
    return db.scalar(
        select(PersonalTodoProjection).where(
            PersonalTodoProjection.contract_id == contract_id,
            PersonalTodoProjection.owner_user_id == "u_assignee",
        )
    )
