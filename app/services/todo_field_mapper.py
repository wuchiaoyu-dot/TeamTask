from __future__ import annotations

from datetime import UTC, datetime, time
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


def _date_to_bitable_timestamp(value) -> int | None:
    if value is None:
        return None
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp() * 1000)


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
