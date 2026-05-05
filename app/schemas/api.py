from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    source_id: str | None = None
    external_event_id: str | None = None
    text: str = Field(min_length=1)
    sender_user_id: str
    participant_user_ids: list[str] = Field(default_factory=list)
    initiator_user_id: str | None = None
    assignee_user_id: str | None = None
    project_name: str | None = None
    chat_id: str | None = None
    message_id: str | None = None
    source_link: str | None = None
    raw_payload: dict | None = None
    parsed_context_json: dict | None = None


class ContractActionIn(BaseModel):
    actor_user_id: str
    contract_id: int


class AssigneeChangeIn(ContractActionIn):
    title: str | None = None
    description: str | None = None
    deadline: date | None = None
    reason: str | None = None


class ProgressQueryIn(BaseModel):
    requester_user_id: str
    assignee_user_id: str
    query_text: str = Field(min_length=1)


class ProgressConfirmIn(ContractActionIn):
    progress_summary: str = Field(min_length=1)


class DevAuthGrantIn(BaseModel):
    user_id: str
    scope: str
    subject_type: str | None = None
    subject_id: str | None = None


class DebugBitableDryRunCreateIn(BaseModel):
    contract_id: int
    owner_user_id: str


class DebugBitableCreateRealIn(BaseModel):
    contract_id: int
    owner_user_id: str
    role: str


class DebugBitableGetRecordIn(BaseModel):
    owner_user_id: str
    external_record_id: str


class DebugBitableUpdateRecordIn(BaseModel):
    owner_user_id: str
    external_record_id: str
    patch: dict


class DebugMinutesParseLinkIn(BaseModel):
    text: str = Field(min_length=1)


class DebugMinutesExtractTasksIn(BaseModel):
    minutes_token_or_url: str = Field(min_length=1)


class DebugMinutesReadRealIn(BaseModel):
    minutes_token_or_url: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class DebugResourceSearchIn(BaseModel):
    contract_id: int
    user_id: str
    write_back: bool = False


class DebugResourceBuildQueriesIn(BaseModel):
    contract_id: int


class DebugResourceSearchRealIn(BaseModel):
    contract_id: int
    user_id: str
    write_back: bool = False


class DebugAuthScopesIn(BaseModel):
    user_id: str = Field(min_length=1)
    required_scopes: list[str] = Field(default_factory=list)


class DebugProgressQueryIn(BaseModel):
    requester_user_id: str
    assignee_user_id: str | None = None
    query_text: str = Field(min_length=1)


class DebugProgressConfirmIn(BaseModel):
    progress_query_id: int
    assignee_user_id: str
    action_key: str = Field(min_length=1)
    progress_text: str | None = None
    new_deadline: date | None = None


class DebugReconciliationRunIn(BaseModel):
    requester_user_id: str
    scope: Literal["single_task", "all_tasks", "project"]
    contract_id: int | None = None
    assignee_user_id: str | None = None
    project_name: str | None = None


class DebugReconciliationApplyActionIn(BaseModel):
    reconciliation_item_id: int
    action_key: str = Field(min_length=1)
    actor_user_id: str
    field_name: str | None = None
    resolution_value: object | None = None


class DailyReconciliationRunIn(BaseModel):
    requester_user_id: str
    assignee_user_id: str | None = None
    project_name: str | None = None


class FeishuEventIn(BaseModel):
    event_id: str = Field(min_length=1)
    event_type: Literal["group_message", "meeting_minutes"]
    text: str | None = None
    sender_user_id: str
    participant_user_ids: list[str] = Field(default_factory=list)
    initiator_user_id: str | None = None
    assignee_user_id: str | None = None
    project_name: str | None = None
    chat_id: str | None = None
    minutes_token: str | None = None
    raw_event: dict | None = None


class FeishuCardCallbackIn(BaseModel):
    action_key: str = Field(min_length=1)
    contract_id: int
    recipient_user_id: str = Field(min_length=1)
    title: str | None = None
    description: str | None = None
    deadline: date | None = None
    reason: str | None = None
    progress_summary: str | None = None
    progress_text: str | None = None
    progress_query_id: int | None = None
    new_deadline: date | None = None
    reconciliation_item_id: int | None = None
    field_name: str | None = None
    resolution_value: object | None = None
    proposal_id: int | None = None
    payload: dict = Field(default_factory=dict)
