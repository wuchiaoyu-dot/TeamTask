from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ChangeProposal, PersonalTodoProjection, TaskContract


def test_initiator_confirm_does_not_write_assignee_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_candidate_contract(client)

    response = client.post(
        "/cards/initiator/confirm",
        json={"actor_user_id": "u_initiator", "contract_id": contract_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending_assignee_confirm"

    with session_factory() as db:
        todos = db.scalars(
            select(PersonalTodoProjection).where(PersonalTodoProjection.contract_id == contract_id)
        ).all()

    assert [(todo.owner_user_id, todo.role) for todo in todos] == [("u_initiator", "initiator")]


def test_assignee_accept_creates_only_their_own_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_candidate_contract(client)
    client.post(
        "/cards/initiator/confirm",
        json={"actor_user_id": "u_initiator", "contract_id": contract_id},
    )

    response = client.post(
        "/cards/assignee/accept",
        json={"actor_user_id": "u_assignee", "contract_id": contract_id},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"

    with session_factory() as db:
        assignee_todo = db.scalar(
            select(PersonalTodoProjection).where(
                PersonalTodoProjection.contract_id == contract_id,
                PersonalTodoProjection.owner_user_id == "u_assignee",
            )
        )

    assert assignee_todo is not None
    assert assignee_todo.role == "assignee"


def test_assignee_deadline_change_creates_change_proposal_without_overwriting_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_candidate_contract(client)
    client.post(
        "/cards/initiator/confirm",
        json={"actor_user_id": "u_initiator", "contract_id": contract_id},
    )

    response = client.post(
        "/cards/assignee/propose-change",
        json={
            "actor_user_id": "u_assignee",
            "contract_id": contract_id,
            "deadline": "2026-06-15",
            "reason": "需要更多评审时间",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "change_pending_initiator_review"

    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        proposal = db.scalar(
            select(ChangeProposal).where(ChangeProposal.contract_id == contract_id)
        )

    assert contract is not None
    assert contract.deadline == date(2026, 6, 1)
    assert proposal is not None
    assert proposal.proposed_deadline == date(2026, 6, 15)


def test_progress_reconciliation_requires_both_authorizations(
    client: TestClient,
) -> None:
    contract_id = _create_active_contract(client)

    response = client.post(
        "/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "这个任务进度怎么样",
        },
    )
    assert response.status_code == 403

    client.post(
        "/dev/auth-grants",
        json={
            "user_id": "u_initiator",
            "scope": "progress_reconcile",
            "subject_type": "user",
            "subject_id": "u_assignee",
        },
    )
    response = client.post(
        "/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "这个任务进度怎么样",
        },
    )
    assert response.status_code == 403

    client.post(
        "/dev/auth-grants",
        json={
            "user_id": "u_assignee",
            "scope": "progress_reconcile",
            "subject_type": "user",
            "subject_id": "u_initiator",
        },
    )
    response = client.post(
        "/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "这个任务进度怎么样",
        },
    )

    assert response.status_code == 200
    assert response.json()["contract_id"] == contract_id


def test_low_confidence_llm_candidate_does_not_auto_write_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/events/group-message",
        json={
            "source_id": "msg-low-confidence",
            "text": "可能请 u_assignee 负责整理一下方案，时间待定，低置信度",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_candidate"]["confidence"] < 0.6

    with session_factory() as db:
        todos = db.scalars(select(PersonalTodoProjection)).all()
        contract = db.get(TaskContract, body["contract_id"])

    assert todos == []
    assert contract is not None
    assert contract.status == "candidate_extracted"


def _create_candidate_contract(client: TestClient) -> int:
    response = client.post(
        "/events/group-message",
        json={
            "source_id": "msg-001",
            "text": "请 u_assignee 负责完成 TeamTask V1 联调，截止 2026-06-01。",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask",
        },
    )
    assert response.status_code == 200
    return response.json()["contract_id"]


def _create_active_contract(client: TestClient) -> int:
    contract_id = _create_candidate_contract(client)
    client.post(
        "/cards/initiator/confirm",
        json={"actor_user_id": "u_initiator", "contract_id": contract_id},
    )
    response = client.post(
        "/cards/assignee/accept",
        json={"actor_user_id": "u_assignee", "contract_id": contract_id},
    )
    assert response.status_code == 200
    return contract_id
