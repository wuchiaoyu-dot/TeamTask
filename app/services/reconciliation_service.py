from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cards.builders import build_reconciliation_review_card, build_reconciliation_summary_card
from app.core.permissions import PROGRESS_RECONCILE_SCOPE
from app.models import (
    PersonalTodoProjection,
    ReconciliationItem,
    ReconciliationRun,
    TaskContract,
    User,
    UserAuthGrant,
    utc_now,
)
from app.services.field_ownership import get_field_owner, get_resolution_policy, suggested_action_for_policy
from app.services.todo_backend import TodoBackend

RECONCILIATION_ALIGN_SCOPE = "reconciliation_align"

RUN_STATUS_PENDING = "pending"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_SKIPPED = "skipped"
RUN_STATUS_FAILED = "failed"

DIFF_CONSISTENT = "consistent"
DIFF_HAS_DIFF = "has_diff"
DIFF_MISSING_INITIATOR = "missing_initiator_projection"
DIFF_MISSING_ASSIGNEE = "missing_assignee_projection"
DIFF_PERMISSION_DENIED = "permission_denied"
DIFF_FAILED = "failed"

RECONCILE_FIELDS = [
    "title",
    "description",
    "deadline",
    "workload_level",
    "project_name",
    "progress_text",
    "completion_status",
    "progress_updated_at",
    "blocker_reason",
    "related_resources_json",
    "mentioned_resources",
    "evidence",
]


def start_reconciliation(
    db: Session,
    *,
    todo_backend: TodoBackend,
    requester_user_id: str,
    scope: str,
    run_type: str = "manual",
    contract_id: int | None = None,
    assignee_user_id: str | None = None,
    project_name: str | None = None,
) -> ReconciliationRun:
    contracts = _select_contracts(
        db,
        scope=scope,
        contract_id=contract_id,
        assignee_user_id=assignee_user_id,
        project_name=project_name,
    )
    first = contracts[0] if contracts else None
    run = ReconciliationRun(
        requester_user_id=requester_user_id,
        initiator_user_id=first.initiator_user_id if first else None,
        assignee_user_id=assignee_user_id or (first.assignee_user_id if first else None),
        contract_id=contract_id,
        scope=scope,
        run_type=run_type,
        status=RUN_STATUS_PENDING,
    )
    db.add(run)
    db.flush()

    if not contracts:
        run.status = RUN_STATUS_SKIPPED
        run.summary = "No task contracts matched reconciliation scope."
        return run

    for contract in contracts:
        item = _reconcile_contract(db, todo_backend, run, contract, requester_user_id)
        db.add(item)
    db.flush()
    run.status = RUN_STATUS_COMPLETED
    run.summary = build_reconciliation_summary(run)
    return run


def check_reconciliation_permissions(
    db: Session,
    requester_user_id: str,
    initiator_user_id: str,
    assignee_user_id: str,
    contract: TaskContract,
) -> bool:
    requester_allowed = requester_user_id in {initiator_user_id, assignee_user_id} or _has_active_grant(
        db,
        requester_user_id,
        RECONCILIATION_ALIGN_SCOPE,
        str(contract.id),
    )
    if not requester_allowed:
        return False
    initiator_authorized = _has_active_grant(db, initiator_user_id, PROGRESS_RECONCILE_SCOPE, assignee_user_id)
    assignee_authorized = _has_active_grant(db, assignee_user_id, PROGRESS_RECONCILE_SCOPE, initiator_user_id)
    return initiator_authorized and assignee_authorized


def load_pair_projections(
    db: Session,
    contract_id: int,
) -> tuple[PersonalTodoProjection | None, PersonalTodoProjection | None]:
    projections = list(
        db.scalars(
            select(PersonalTodoProjection).where(PersonalTodoProjection.contract_id == contract_id)
        )
    )
    initiator_projection = next((item for item in projections if item.role == "initiator"), None)
    assignee_projection = next((item for item in projections if item.role == "assignee"), None)
    return initiator_projection, assignee_projection


def fetch_projection_snapshot(
    owner_user_id: str,
    projection: PersonalTodoProjection,
    todo_backend: TodoBackend,
) -> dict[str, Any]:
    contract = projection.contract
    base = _projection_to_snapshot(projection)
    if projection.snapshot_json:
        base.update(projection.snapshot_json)
        return _normalize_snapshot(base)
    if projection.external_record_id:
        external = todo_backend.get_projection_snapshot(owner_user_id, projection.external_record_id)
        if external and not external.get("dry_run"):
            base.update(external)
    if contract:
        base.setdefault("project_name", contract.project_name)
        base.setdefault("workload_level", contract.workload_level)
        base.setdefault("progress_text", contract.progress_text)
        base.setdefault("completion_status", contract.completion_status)
        base.setdefault(
            "progress_updated_at",
            contract.progress_updated_at.isoformat() if contract.progress_updated_at else None,
        )
        base.setdefault("related_resources_json", contract.related_resources_json)
        base.setdefault("mentioned_resources", contract.mentioned_resources)
        base.setdefault("evidence", contract.evidence)
    return _normalize_snapshot(base)


def diff_projection_snapshots(
    initiator_snapshot: dict[str, Any],
    assignee_snapshot: dict[str, Any],
    contract: TaskContract,
) -> dict[str, Any]:
    diffs: dict[str, Any] = {}
    for field in RECONCILE_FIELDS:
        initiator_value = _canonical_value(initiator_snapshot.get(field))
        assignee_value = _canonical_value(assignee_snapshot.get(field))
        if initiator_value == assignee_value:
            continue
        policy = get_resolution_policy(field)
        diffs[field] = {
            "initiator_value": initiator_value,
            "assignee_value": assignee_value,
            "field_owner": get_field_owner(field),
            "resolution_policy": policy,
            "suggested_action": suggested_action_for_policy(policy),
        }
    return diffs


def create_reconciliation_item(
    run: ReconciliationRun,
    contract: TaskContract,
    diffs: dict[str, Any],
    initiator_projection: PersonalTodoProjection | None = None,
    assignee_projection: PersonalTodoProjection | None = None,
    diff_status: str | None = None,
) -> ReconciliationItem:
    status = diff_status or (DIFF_HAS_DIFF if diffs else DIFF_CONSISTENT)
    item = ReconciliationItem(
        run_id=run.id,
        contract_id=contract.id,
        initiator_projection_id=initiator_projection.id if initiator_projection else None,
        assignee_projection_id=assignee_projection.id if assignee_projection else None,
        diff_status=status,
        field_diffs_json=diffs,
    )
    return item


def build_reconciliation_summary(run: ReconciliationRun) -> str:
    counts: dict[str, int] = {}
    for item in run.items:
        counts[item.diff_status] = counts.get(item.diff_status, 0) + 1
    return (
        f"Reconciled {len(run.items)} task(s): "
        f"{counts.get(DIFF_CONSISTENT, 0)} consistent, "
        f"{counts.get(DIFF_HAS_DIFF, 0)} with diffs, "
        f"{counts.get(DIFF_PERMISSION_DENIED, 0)} permission denied, "
        f"{counts.get(DIFF_MISSING_INITIATOR, 0) + counts.get(DIFF_MISSING_ASSIGNEE, 0)} missing projections."
    )


def apply_reconciliation_action(
    db: Session,
    *,
    item: ReconciliationItem,
    action_key: str,
    actor_user_id: str,
    field_name: str | None,
    resolution_value: Any | None = None,
) -> dict[str, Any]:
    contract = item.contract
    diffs = dict(item.field_diffs_json or {})
    if action_key == "reconciliation_ignore_diff":
        _mark_diff_resolution(diffs, field_name, "ignored")
        item.field_diffs_json = diffs
        item.generated_card_json = {**(item.generated_card_json or {}), "ignored": True, "ignored_field": field_name}
        return _action_response(item)

    if not field_name or field_name not in diffs:
        raise PermissionError("field_name must reference an existing diff")
    diff = diffs[field_name]
    owner = diff.get("field_owner")

    if action_key in {"reconciliation_approve_change", "reconciliation_reject_change"}:
        if actor_user_id != contract.initiator_user_id:
            raise PermissionError("Only the initiator can approve or reject initiator-owned changes")
        if owner != "initiator":
            raise PermissionError("Approve/reject is only for initiator-owned fields")
        if action_key == "reconciliation_reject_change":
            _mark_diff_resolution(diffs, field_name, "rejected")
            item.field_diffs_json = diffs
            return _action_response(item)
        value = resolution_value if resolution_value is not None else diff.get("assignee_value")
        _apply_contract_field(contract, field_name, value)
        _sync_projection_field(item.initiator_projection, field_name, value)
        _sync_projection_field(item.assignee_projection, field_name, value)
        _mark_diff_resolution(diffs, field_name, "approved")
        item.field_diffs_json = diffs
        return _action_response(item)

    if action_key == "reconciliation_sync_progress":
        if actor_user_id != contract.assignee_user_id:
            raise PermissionError("Only the assignee can confirm progress sync")
        if owner != "assignee":
            raise PermissionError("Progress sync is only for assignee-owned fields")
        value = resolution_value if resolution_value is not None else diff.get("assignee_value")
        _apply_contract_field(contract, field_name, value)
        _sync_projection_field(item.initiator_projection, field_name, value)
        _sync_projection_field(item.assignee_projection, field_name, value)
        _mark_diff_resolution(diffs, field_name, "synced")
        item.field_diffs_json = diffs
        return _action_response(item)

    if action_key == "reconciliation_merge_resources":
        if owner != "both":
            raise PermissionError("Only both-owned resource fields can be merged")
        merged = _merge_values(diff.get("initiator_value"), diff.get("assignee_value"))
        _apply_contract_field(contract, field_name, merged)
        _sync_projection_field(item.initiator_projection, field_name, merged)
        _sync_projection_field(item.assignee_projection, field_name, merged)
        _mark_diff_resolution(diffs, field_name, "merged")
        item.field_diffs_json = diffs
        return _action_response(item)

    if action_key == "reconciliation_request_more_info":
        _mark_diff_resolution(diffs, field_name, "more_info_requested")
        item.field_diffs_json = diffs
        return _action_response(item)

    raise PermissionError("Unsupported reconciliation action")


def _reconcile_contract(
    db: Session,
    todo_backend: TodoBackend,
    run: ReconciliationRun,
    contract: TaskContract,
    requester_user_id: str,
) -> ReconciliationItem:
    initiator_projection, assignee_projection = load_pair_projections(db, contract.id)
    if not check_reconciliation_permissions(
        db,
        requester_user_id,
        contract.initiator_user_id,
        contract.assignee_user_id,
        contract,
    ):
        return create_reconciliation_item(
            run,
            contract,
            {},
            initiator_projection,
            assignee_projection,
            diff_status=DIFF_PERMISSION_DENIED,
        )
    if initiator_projection is None:
        return create_reconciliation_item(run, contract, {}, None, assignee_projection, DIFF_MISSING_INITIATOR)
    if assignee_projection is None:
        return create_reconciliation_item(run, contract, {}, initiator_projection, None, DIFF_MISSING_ASSIGNEE)
    try:
        initiator_snapshot = fetch_projection_snapshot(contract.initiator_user_id, initiator_projection, todo_backend)
        assignee_snapshot = fetch_projection_snapshot(contract.assignee_user_id, assignee_projection, todo_backend)
        diffs = diff_projection_snapshots(initiator_snapshot, assignee_snapshot, contract)
        item = create_reconciliation_item(run, contract, diffs, initiator_projection, assignee_projection)
        if diffs:
            # Item needs an id before the card can include reconciliation_item_id.
            db.add(item)
            db.flush()
            item.generated_card_json = build_reconciliation_review_card(item, contract, contract.initiator_user_id)
        return item
    except Exception as exc:  # pragma: no cover - defensive path
        item = create_reconciliation_item(
            run,
            contract,
            {"error": {"message": str(exc)}},
            initiator_projection,
            assignee_projection,
            diff_status=DIFF_FAILED,
        )
        return item


def _select_contracts(
    db: Session,
    *,
    scope: str,
    contract_id: int | None,
    assignee_user_id: str | None,
    project_name: str | None,
) -> list[TaskContract]:
    statement = select(TaskContract).order_by(TaskContract.updated_at.desc())
    if scope == "single_task" and contract_id is not None:
        statement = statement.where(TaskContract.id == contract_id)
    if assignee_user_id:
        statement = statement.where(TaskContract.assignee_user_id == assignee_user_id)
    if scope == "project" and project_name:
        statement = statement.where(TaskContract.project_name == project_name)
    return list(db.scalars(statement))


def _projection_to_snapshot(projection: PersonalTodoProjection) -> dict[str, Any]:
    return _normalize_snapshot(
        {
            "title": projection.title,
            "description": projection.description,
            "deadline": projection.deadline.isoformat() if projection.deadline else None,
        }
    )


def _normalize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(snapshot)
    if "task_title" in normalized and "title" not in normalized:
        normalized["title"] = normalized["task_title"]
    if "task_description" in normalized and "description" not in normalized:
        normalized["description"] = normalized["task_description"]
    if isinstance(normalized.get("deadline"), date):
        normalized["deadline"] = normalized["deadline"].isoformat()
    if isinstance(normalized.get("progress_updated_at"), datetime):
        normalized["progress_updated_at"] = normalized["progress_updated_at"].isoformat()
    return normalized


def _canonical_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _has_active_grant(db: Session, user_id: str, scope: str, subject_id: str | None = None) -> bool:
    grants = db.scalars(
        select(UserAuthGrant).where(
            UserAuthGrant.user_id == user_id,
            UserAuthGrant.scope == scope,
            UserAuthGrant.is_active.is_(True),
        )
    ).all()
    for grant in grants:
        if grant.subject_id is None or subject_id is None or grant.subject_id == subject_id:
            return True
    return False


def _apply_contract_field(contract: TaskContract, field_name: str, value: Any) -> None:
    if field_name in {"title", "task_title"}:
        contract.title = str(value or "")
    elif field_name in {"description", "task_description"}:
        contract.description = str(value or "")
    elif field_name == "deadline":
        contract.deadline = _parse_date(value)
    elif field_name == "project_name":
        contract.project_name = str(value or "")
    elif field_name == "workload_level":
        contract.workload_level = str(value or "")
    elif field_name == "progress_text":
        contract.progress_text = str(value or "")
        contract.progress_summary = contract.progress_text
        contract.progress_updated_at = utc_now()
    elif field_name == "completion_status":
        contract.completion_status = str(value or "unknown")
        contract.progress_updated_at = utc_now()
    elif field_name == "progress_updated_at":
        contract.progress_updated_at = utc_now()
    elif field_name == "related_resources_json":
        contract.related_resources_json = value if isinstance(value, dict) else {"merged": value}
    elif field_name == "mentioned_resources":
        contract.mentioned_resources = value if isinstance(value, list) else [value]
    elif field_name == "evidence":
        return


def _sync_projection_field(projection: PersonalTodoProjection | None, field_name: str, value: Any) -> None:
    if projection is None:
        return
    if field_name in {"title", "task_title"}:
        projection.title = str(value or "")
    elif field_name in {"description", "task_description"}:
        projection.description = str(value or "")
    elif field_name == "deadline":
        projection.deadline = _parse_date(value)
    elif field_name == "completion_status":
        projection.status = str(value or "unknown")
    projection.snapshot_json = {**(projection.snapshot_json or {}), field_name: _canonical_value(value)}
    projection.last_synced_at = utc_now()


def _parse_date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _merge_values(initiator_value: Any, assignee_value: Any) -> Any:
    if isinstance(initiator_value, dict) or isinstance(assignee_value, dict):
        return _merge_resource_dicts(
            initiator_value if isinstance(initiator_value, dict) else {},
            assignee_value if isinstance(assignee_value, dict) else {},
        )
    merged: list[Any] = []
    for source, value in (("initiator", initiator_value), ("assignee", assignee_value)):
        items = value if isinstance(value, list) else [value]
        for item in items:
            if item in {"", None}:
                continue
            enriched = item
            if isinstance(item, dict):
                enriched = {**item, "resource_source": item.get("resource_source") or source}
            if enriched not in merged:
                merged.append(enriched)
    return merged


def _merge_resource_dicts(initiator_value: dict[str, Any], assignee_value: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for bucket in set(initiator_value) | set(assignee_value):
        merged[bucket] = _merge_values(initiator_value.get(bucket) or [], assignee_value.get(bucket) or [])
    return merged


def _mark_diff_resolution(diffs: dict[str, Any], field_name: str | None, resolution: str) -> None:
    if field_name and field_name in diffs:
        diffs[field_name] = {**diffs[field_name], "resolution_status": resolution}
        return
    diffs["_item_resolution"] = resolution


def _action_response(item: ReconciliationItem) -> dict[str, Any]:
    return {
        "updated_item": item,
        "updated_contract": item.contract,
        "updated_projections": [item.initiator_projection, item.assignee_projection],
    }
