from __future__ import annotations

from typing import Any, Literal

FieldOwner = Literal["initiator", "assignee", "both", "system"]

INITIATOR_OWNED_FIELDS = {
    "task_title",
    "title",
    "task_description",
    "description",
    "deadline",
    "workload_level",
    "project_name",
}
ASSIGNEE_OWNED_FIELDS = {
    "progress_text",
    "completion_status",
    "progress_updated_at",
    "blocker_reason",
}
BOTH_OWNED_FIELDS = {
    "related_resources_json",
    "mentioned_resources",
    "evidence",
}
SYSTEM_FIELDS = {
    "id",
    "contract_id",
    "status",
    "external_record_id",
    "todo_provider",
    "last_synced_at",
    "created_at",
    "updated_at",
}


def get_field_owner(field_name: str) -> FieldOwner:
    normalized = _normalize_field_name(field_name)
    if normalized in INITIATOR_OWNED_FIELDS:
        return "initiator"
    if normalized in ASSIGNEE_OWNED_FIELDS:
        return "assignee"
    if normalized in BOTH_OWNED_FIELDS:
        return "both"
    return "system"


def get_resolution_policy(field_name: str, diff: dict[str, Any] | None = None) -> str:
    owner = get_field_owner(field_name)
    normalized = _normalize_field_name(field_name)
    if normalized in {"title", "task_title", "description", "task_description", "deadline"}:
        return "initiator_review_required"
    if owner == "assignee":
        return "sync_to_initiator_after_notice"
    if normalized == "related_resources_json":
        return "merge_resources"
    if normalized == "mentioned_resources":
        return "merge_resources"
    if normalized == "evidence":
        return "manual_review_no_auto_overwrite"
    if owner == "system":
        return "system_managed_no_card_edit"
    return "manual_review"


def suggested_action_for_policy(policy: str) -> str:
    return {
        "initiator_review_required": "create_change_proposal",
        "sync_to_initiator_after_notice": "sync_progress",
        "merge_resources": "merge_resources",
        "manual_review_no_auto_overwrite": "manual_review",
        "system_managed_no_card_edit": "ignore_system_field",
    }.get(policy, "manual_review")


def _normalize_field_name(field_name: str) -> str:
    if field_name == "task_title":
        return "title"
    if field_name == "task_description":
        return "description"
    return field_name
