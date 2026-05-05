from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from typing import Any

from app.config import Settings, get_settings
from app.models import TaskContract


def map_contract_to_bitable_fields(
    owner_user_id: str,
    contract: TaskContract,
    role: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        settings.feishu_todo_owner_field: owner_user_id,
        settings.feishu_todo_contract_id_field: str(contract.id),
        settings.feishu_todo_title_field: contract.title,
        settings.feishu_todo_description_field: contract.description or "",
        settings.feishu_todo_initiator_field: contract.initiator_user_id,
        settings.feishu_todo_assignee_field: contract.assignee_user_id,
        settings.feishu_todo_status_field: contract.status,
        settings.feishu_todo_deadline_field: _date_to_bitable_timestamp(contract.deadline),
        settings.feishu_todo_source_field: _source_text(contract),
        settings.feishu_todo_evidence_field: "\n".join(contract.evidence or []),
        settings.feishu_todo_resource_field: _resources_text(contract),
        settings.feishu_todo_role_field: role,
    }


def map_patch_to_bitable_fields(patch: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    fields: dict[str, Any] = {}
    mapping = {
        "title": settings.feishu_todo_title_field,
        "task_title": settings.feishu_todo_title_field,
        "description": settings.feishu_todo_description_field,
        "task_description": settings.feishu_todo_description_field,
        "deadline": settings.feishu_todo_deadline_field,
        "status": settings.feishu_todo_status_field,
        "completion_status": settings.feishu_todo_status_field,
        "progress_text": "progress_text",
        "related_resources_json": settings.feishu_todo_resource_field,
    }
    for key, value in patch.items():
        field_name = mapping.get(key)
        if not field_name:
            fields[key] = _serialize_field_value(value)
            continue
        if key == "deadline":
            fields[field_name] = _date_to_bitable_timestamp(_parse_date_like(value))
        elif key == "related_resources_json":
            fields[field_name] = json.dumps(value, ensure_ascii=False, default=str)
        else:
            fields[field_name] = _serialize_field_value(value)
    return fields


def map_bitable_record_to_snapshot(record: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else record
    snapshot = {
        "title": fields.get(settings.feishu_todo_title_field),
        "description": fields.get(settings.feishu_todo_description_field),
        "deadline": _bitable_date_to_iso(fields.get(settings.feishu_todo_deadline_field)),
        "status": fields.get(settings.feishu_todo_status_field),
        "completion_status": fields.get(settings.feishu_todo_status_field),
        "progress_text": fields.get("progress_text") or fields.get("进度") or fields.get("Progress"),
        "related_resources_json": _parse_jsonish(fields.get(settings.feishu_todo_resource_field)),
        "mentioned_resources": _split_lines(fields.get(settings.feishu_todo_resource_field)),
        "evidence": _split_lines(fields.get(settings.feishu_todo_evidence_field)),
    }
    return {key: value for key, value in snapshot.items() if not _is_empty_snapshot_value(value)}


def _date_to_bitable_timestamp(value) -> int | None:
    if value is None:
        return None
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp() * 1000)


def _bitable_date_to_iso(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).date().isoformat()
    parsed = _parse_date_like(value)
    return parsed.isoformat() if parsed else str(value)


def _parse_date_like(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).date()
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _serialize_field_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _split_lines(value: Any) -> list[str]:
    if value in {None, ""}:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _is_empty_snapshot_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


def _source_text(contract: TaskContract) -> str:
    event = contract.source_event
    if not event:
        return ""
    metadata = event.event_metadata or {}
    source_link = metadata.get("source_link")
    if source_link:
        return str(source_link)
    if event.source_id:
        return f"{event.event_type}:{event.source_id}"
    return event.event_type


def _resources_text(contract: TaskContract) -> str:
    resources = []
    resources.extend(contract.resource_keywords or [])
    resources.extend(contract.mentioned_resources or [])
    return "\n".join(str(resource) for resource in resources if resource)
