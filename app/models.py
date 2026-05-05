from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    feishu_open_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    auth_grants: Mapped[list[UserAuthGrant]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserAuthGrant(Base, TimestampMixin):
    __tablename__ = "user_auth_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="auth_grants")


class SourceEvent(Base, TimestampMixin):
    __tablename__ = "source_events"
    __table_args__ = (
        UniqueConstraint("external_event_id", name="uq_source_events_external_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(64), default="feishu", nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sender_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    participant_user_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    parsed_context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class TaskContract(Base, TimestampMixin):
    __tablename__ = "task_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_event_id: Mapped[int] = mapped_column(ForeignKey("source_events.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_task_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    initiator_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    assignee_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workload_level: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    resource_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mentioned_resources: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    progress_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_status: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    related_resources_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {"high_confidence": [], "low_confidence": []},
        nullable=False,
    )
    resource_search_status: Mapped[str] = mapped_column(String(64), default="not_started", nullable=False)
    resource_search_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_event: Mapped[SourceEvent] = relationship()
    initiator: Mapped[User] = relationship(foreign_keys=[initiator_user_id])
    assignee: Mapped[User] = relationship(foreign_keys=[assignee_user_id])
    todo_projections: Mapped[list[PersonalTodoProjection]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
    )
    change_proposals: Mapped[list[ChangeProposal]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
    )


class PersonalTodoProjection(Base, TimestampMixin):
    __tablename__ = "personal_todo_projections"
    __table_args__ = (
        UniqueConstraint("contract_id", "owner_user_id", name="uq_todo_contract_owner"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("task_contracts.id"), nullable=False, index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="open", nullable=False)
    todo_provider: Mapped[str] = mapped_column(String(64), default="mock", nullable=False)
    external_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    contract: Mapped[TaskContract] = relationship(back_populates="todo_projections")
    owner: Mapped[User] = relationship()


class ChangeProposal(Base, TimestampMixin):
    __tablename__ = "change_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("task_contracts.id"), nullable=False, index=True)
    proposer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    proposed_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proposed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="pending_initiator_review", nullable=False)

    contract: Mapped[TaskContract] = relationship(back_populates="change_proposals")
    proposer: Mapped[User] = relationship()


class CardAction(Base, TimestampMixin):
    __tablename__ = "card_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("task_contracts.id"), nullable=True, index=True)
    action_key: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    contract: Mapped[TaskContract | None] = relationship()
    actor: Mapped[User] = relationship()


class ProgressQuery(Base, TimestampMixin):
    __tablename__ = "progress_queries"
    __table_args__ = (
        UniqueConstraint("external_event_id", name="uq_progress_queries_external_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    requester_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    matched_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_contracts.id"),
        nullable=True,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_status: Mapped[str] = mapped_column(String(64), default="pending_assignee_confirm", nullable=False)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    requester: Mapped[User] = relationship(foreign_keys=[requester_user_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_user_id])
    matched_contract: Mapped[TaskContract | None] = relationship()


class ReconciliationRun(Base, TimestampMixin):
    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requester_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    initiator_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assignee_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("task_contracts.id"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    run_type: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="pending", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    requester: Mapped[User] = relationship(foreign_keys=[requester_user_id])
    initiator: Mapped[User | None] = relationship(foreign_keys=[initiator_user_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_user_id])
    contract: Mapped[TaskContract | None] = relationship()
    items: Mapped[list[ReconciliationItem]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ReconciliationItem(Base, TimestampMixin):
    __tablename__ = "reconciliation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False, index=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("task_contracts.id"), nullable=False, index=True)
    initiator_projection_id: Mapped[int | None] = mapped_column(
        ForeignKey("personal_todo_projections.id"),
        nullable=True,
        index=True,
    )
    assignee_projection_id: Mapped[int | None] = mapped_column(
        ForeignKey("personal_todo_projections.id"),
        nullable=True,
        index=True,
    )
    diff_status: Mapped[str] = mapped_column(String(64), nullable=False)
    field_diffs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_card_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    run: Mapped[ReconciliationRun] = relationship(back_populates="items")
    contract: Mapped[TaskContract] = relationship()
    initiator_projection: Mapped[PersonalTodoProjection | None] = relationship(foreign_keys=[initiator_projection_id])
    assignee_projection: Mapped[PersonalTodoProjection | None] = relationship(foreign_keys=[assignee_projection_id])
