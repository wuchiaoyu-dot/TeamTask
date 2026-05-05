from __future__ import annotations

import subprocess
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import PersonalTodoProjection, ReconciliationItem, TaskContract


def test_reconciliation_permission_denied_without_both_grants(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-no-grants")

    response = _run_reconciliation(client, "u_initiator", contract_id)

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["diff_status"] == "permission_denied"


def test_only_initiator_grant_cannot_read_assignee_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-one-grant")
    _grant(client, "u_initiator", "u_assignee")

    response = _run_reconciliation(client, "u_initiator", contract_id)

    assert response.status_code == 200
    assert response.json()["items"][0]["diff_status"] == "permission_denied"


def test_both_grants_allow_reconcile_pair_projections(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-both-grants")
    _grant_pair(client)

    response = _run_reconciliation(client, "u_initiator", contract_id)

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["diff_status"] == "consistent"
    assert item["field_diffs_json"] == {}


def test_deadline_diff_requires_initiator_review(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-deadline")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"deadline": "2026-05-08"},
        assignee={"deadline": "2026-05-10"},
    )

    item = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]

    assert item["diff_status"] == "has_diff"
    assert item["field_diffs_json"]["deadline"]["resolution_policy"] == "initiator_review_required"
    assert item["field_diffs_json"]["deadline"]["suggested_action"] == "create_change_proposal"


def test_progress_text_diff_suggests_sync_progress(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-progress")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"progress_text": ""},
        assignee={"progress_text": "Draft is 70 percent complete."},
    )

    item = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]

    assert item["field_diffs_json"]["progress_text"]["field_owner"] == "assignee"
    assert item["field_diffs_json"]["progress_text"]["suggested_action"] == "sync_progress"


def test_related_resources_diff_suggests_merge_resources(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-resources")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"related_resources_json": {"high_confidence": [{"title": "A", "url": "https://a"}]}},
        assignee={"related_resources_json": {"high_confidence": [{"title": "B", "url": "https://b"}]}},
    )

    item = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]

    assert item["field_diffs_json"]["related_resources_json"]["suggested_action"] == "merge_resources"


def test_evidence_diff_does_not_allow_auto_overwrite(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-evidence")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"evidence": ["meeting note"]},
        assignee={"evidence": ["private note"]},
    )

    item = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]

    assert item["field_diffs_json"]["evidence"]["resolution_policy"] == "manual_review_no_auto_overwrite"
    assert item["field_diffs_json"]["evidence"]["suggested_action"] == "manual_review"


def test_title_description_approve_only_by_initiator(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-title")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"title": "Old title"},
        assignee={"title": "New title"},
    )
    item_id = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]["id"]

    forbidden = _apply_reconciliation_action(client, item_id, "reconciliation_approve_change", "u_assignee", "title")
    allowed = _apply_reconciliation_action(client, item_id, "reconciliation_approve_change", "u_initiator", "title")

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
    assert contract is not None
    assert contract.title == "New title"


def test_requester_cannot_approve_someone_else_field(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-requester-forbidden")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"deadline": "2026-05-08"},
        assignee={"deadline": "2026-05-10"},
    )
    item_id = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]["id"]

    response = _apply_reconciliation_action(client, item_id, "reconciliation_approve_change", "u_other", "deadline")

    assert response.status_code == 403


def test_reconciliation_sync_progress_updates_initiator_projection(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-sync-progress")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"progress_text": ""},
        assignee={"progress_text": "Done with first draft."},
    )
    item_id = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]["id"]

    response = _apply_reconciliation_action(
        client,
        item_id,
        "reconciliation_sync_progress",
        "u_assignee",
        "progress_text",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        initiator_projection = _projection(db, contract_id, "u_initiator")

    assert contract is not None
    assert contract.progress_text == "Done with first draft."
    assert initiator_projection is not None
    assert initiator_projection.snapshot_json["progress_text"] == "Done with first draft."


def test_reconciliation_approve_change_updates_contract_and_both_projections(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-approve-deadline")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"deadline": "2026-05-08"},
        assignee={"deadline": "2026-05-10"},
    )
    item_id = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]["id"]

    response = _apply_reconciliation_action(
        client,
        item_id,
        "reconciliation_approve_change",
        "u_initiator",
        "deadline",
    )

    assert response.status_code == 200
    with session_factory() as db:
        contract = db.get(TaskContract, contract_id)
        initiator_projection = _projection(db, contract_id, "u_initiator")
        assignee_projection = _projection(db, contract_id, "u_assignee")

    assert contract is not None
    assert contract.deadline == date(2026, 5, 10)
    assert initiator_projection is not None
    assert assignee_projection is not None
    assert initiator_projection.deadline == date(2026, 5, 10)
    assert assignee_projection.deadline == date(2026, 5, 10)


def test_ignore_diff_marks_item_without_deleting_diff(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-ignore")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"deadline": "2026-05-08"},
        assignee={"deadline": "2026-05-10"},
    )
    item_id = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]["id"]

    response = _apply_reconciliation_action(
        client,
        item_id,
        "reconciliation_ignore_diff",
        "u_initiator",
        "deadline",
    )

    assert response.status_code == 200
    updated = response.json()["updated_item"]
    assert "deadline" in updated["field_diffs_json"]
    assert updated["field_diffs_json"]["deadline"]["resolution_status"] == "ignored"


def test_daily_run_does_not_read_todo_without_authorization(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-daily-permission")
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"progress_text": ""},
        assignee={"progress_text": "Should not be read."},
    )

    response = client.post(
        "/reconciliation/daily-run",
        json={"requester_user_id": "u_initiator", "assignee_user_id": "u_assignee"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["diff_status"] == "permission_denied"


def test_feishu_mock_reconciliation_does_not_call_real_feishu(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    def fail_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        raise AssertionError("subprocess.run should not be called in FEISHU_MOCK=true")

    monkeypatch.setattr(subprocess, "run", fail_run)
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-mock-safe")
    _grant_pair(client)

    response = _run_reconciliation(client, "u_initiator", contract_id)

    assert response.status_code == 200


def test_lark_dry_run_reconciliation_does_not_write_external_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    contract_id = _create_active_contract(client, session_factory, "evt-reconcile-lark-dry")
    _grant_pair(client)
    _set_projection_snapshots(
        session_factory,
        contract_id,
        initiator={"progress_text": ""},
        assignee={"progress_text": "Dry run progress."},
    )
    item_id = _run_reconciliation(client, "u_initiator", contract_id).json()["items"][0]["id"]
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("TODO_BACKEND", "bitable")
    monkeypatch.setenv("LARK_DRY_RUN", "true")

    response = _apply_reconciliation_action(
        client,
        item_id,
        "reconciliation_sync_progress",
        "u_assignee",
        "progress_text",
    )

    assert response.status_code == 200
    with session_factory() as db:
        projection = _projection(db, contract_id, "u_initiator")
    assert projection is not None
    assert projection.snapshot_json["progress_text"] == "Dry run progress."


def _create_active_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
    event_id: str,
) -> int:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "text": "Please assign u_assignee to finish Reconciliation task by 2026-06-01.",
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
        contract.title = "Reconciliation task"
        contract.description = "Reconciliation task details"
        contract.deadline = date(2026, 6, 1)
        contract.completion_status = "in_progress"
        for projection in contract.todo_projections:
            projection.snapshot_json = None
        db.commit()
    return contract_id


def _grant_pair(client: TestClient) -> None:
    _grant(client, "u_initiator", "u_assignee")
    _grant(client, "u_assignee", "u_initiator")


def _grant(client: TestClient, user_id: str, subject_id: str) -> None:
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


def _run_reconciliation(client: TestClient, requester_user_id: str, contract_id: int):
    return client.post(
        "/debug/reconciliation/run",
        json={
            "requester_user_id": requester_user_id,
            "scope": "single_task",
            "contract_id": contract_id,
        },
    )


def _apply_reconciliation_action(
    client: TestClient,
    item_id: int,
    action_key: str,
    actor_user_id: str,
    field_name: str,
):
    return client.post(
        "/debug/reconciliation/apply-action",
        json={
            "reconciliation_item_id": item_id,
            "action_key": action_key,
            "actor_user_id": actor_user_id,
            "field_name": field_name,
        },
    )


def _set_projection_snapshots(
    session_factory: sessionmaker[Session],
    contract_id: int,
    initiator: dict[str, Any],
    assignee: dict[str, Any],
) -> None:
    with session_factory() as db:
        initiator_projection = _projection(db, contract_id, "u_initiator")
        assignee_projection = _projection(db, contract_id, "u_assignee")
        assert initiator_projection is not None
        assert assignee_projection is not None
        initiator_projection.snapshot_json = initiator
        assignee_projection.snapshot_json = assignee
        db.commit()


def _projection(db: Session, contract_id: int, owner_user_id: str) -> PersonalTodoProjection | None:
    return db.scalar(
        select(PersonalTodoProjection).where(
            PersonalTodoProjection.contract_id == contract_id,
            PersonalTodoProjection.owner_user_id == owner_user_id,
        )
    )
