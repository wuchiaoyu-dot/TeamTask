from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.permissions import can_write_personal_todo
from app.models import (
    CardAction,
    ChangeProposal,
    PersonalTodoProjection,
    SourceEvent,
    TaskContract,
    User,
    UserAuthGrant,
)
from app.schemas.llm_task_schema import TaskCandidate
from app.state_machine import TaskStatus


def get_or_create_user(db: Session, user_id: str, display_name: str | None = None) -> User:
    user = db.get(User, user_id)
    if user:
        return user
    user = User(id=user_id, display_name=display_name or user_id)
    db.add(user)
    db.flush()
    return user


def create_auth_grant(
    db: Session,
    user_id: str,
    scope: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
) -> UserAuthGrant:
    user = get_or_create_user(db, user_id)
    grant = UserAuthGrant(
        user_id=user.id,
        scope=scope,
        subject_type=subject_type,
        subject_id=subject_id,
        is_active=True,
    )
    db.add(grant)
    db.flush()
    return grant


def find_source_event_by_external_id(db: Session, external_event_id: str | None) -> SourceEvent | None:
    if not external_event_id:
        return None
    return db.scalar(select(SourceEvent).where(SourceEvent.external_event_id == external_event_id))


def find_contract_by_source_event(db: Session, source_event_id: int) -> TaskContract | None:
    return db.scalar(
        select(TaskContract)
        .where(TaskContract.source_event_id == source_event_id)
        .order_by(TaskContract.id.asc())
    )


def create_task_contract(db: Session, source_event: SourceEvent, candidate: TaskCandidate) -> TaskContract:
    get_or_create_user(db, candidate.initiator)
    get_or_create_user(db, candidate.assignee)
    contract = TaskContract(
        source_event_id=source_event.id,
        status=TaskStatus.CANDIDATE_EXTRACTED.value,
        title=candidate.task_title,
        description=candidate.task_description,
        project_name=candidate.project_name,
        parent_task_title=candidate.parent_task_title,
        initiator_user_id=candidate.initiator,
        assignee_user_id=candidate.assignee,
        task_type=candidate.task_type,
        workload_level=candidate.workload_level,
        deadline=candidate.deadline,
        resource_keywords=candidate.resource_keywords,
        mentioned_resources=candidate.mentioned_resources,
        evidence=candidate.evidence,
        missing_fields=candidate.missing_fields,
        confidence=candidate.confidence,
    )
    db.add(contract)
    db.flush()
    return contract


def create_todo_projection(
    db: Session,
    contract: TaskContract,
    actor: User,
    owner: User,
    role: str,
) -> PersonalTodoProjection:
    if not can_write_personal_todo(actor, owner):
        raise PermissionError("Users can only write their own personal Todo projection")

    existing = db.scalar(
        select(PersonalTodoProjection).where(
            PersonalTodoProjection.contract_id == contract.id,
            PersonalTodoProjection.owner_user_id == owner.id,
        )
    )
    if existing:
        return existing

    todo = PersonalTodoProjection(
        contract_id=contract.id,
        owner_user_id=owner.id,
        role=role,
        title=contract.title,
        description=contract.description,
        deadline=contract.deadline,
        status=contract.status,
    )
    db.add(todo)
    db.flush()
    return todo


def create_change_proposal(
    db: Session,
    contract: TaskContract,
    proposer: User,
    title: str | None = None,
    description: str | None = None,
    deadline=None,
    reason: str | None = None,
) -> ChangeProposal:
    proposal = ChangeProposal(
        contract_id=contract.id,
        proposer_user_id=proposer.id,
        proposed_title=title,
        proposed_description=description,
        proposed_deadline=deadline,
        reason=reason,
    )
    db.add(proposal)
    db.flush()
    return proposal


def find_matching_change_proposal(
    db: Session,
    contract: TaskContract,
    proposer: User,
    title: str | None = None,
    description: str | None = None,
    deadline=None,
) -> ChangeProposal | None:
    return db.scalar(
        select(ChangeProposal)
        .where(ChangeProposal.contract_id == contract.id)
        .where(ChangeProposal.proposer_user_id == proposer.id)
        .where(ChangeProposal.proposed_title.is_(None) if title is None else ChangeProposal.proposed_title == title)
        .where(
            ChangeProposal.proposed_description.is_(None)
            if description is None
            else ChangeProposal.proposed_description == description
        )
        .where(
            ChangeProposal.proposed_deadline.is_(None)
            if deadline is None
            else ChangeProposal.proposed_deadline == deadline
        )
        .order_by(ChangeProposal.id.desc())
    )


def get_existing_card_action(
    db: Session,
    action_key: str,
    actor_user_id: str,
    contract_id: int | None = None,
) -> CardAction | None:
    statement = (
        select(CardAction)
        .where(CardAction.action_key == action_key)
        .where(CardAction.actor_user_id == actor_user_id)
        .order_by(CardAction.id.desc())
    )
    if contract_id is not None:
        statement = statement.where(CardAction.contract_id == contract_id)
    return db.scalar(statement)


def record_card_action(
    db: Session,
    action_key: str,
    actor_user_id: str,
    contract_id: int | None = None,
    payload: dict | None = None,
) -> CardAction:
    action = CardAction(
        contract_id=contract_id,
        action_key=action_key,
        actor_user_id=actor_user_id,
        payload=payload or {},
    )
    db.add(action)
    db.flush()
    return action


def find_matching_contract_for_progress(
    db: Session,
    requester_user_id: str,
    assignee_user_id: str,
    query_text: str,
) -> TaskContract | None:
    statement: Select[tuple[TaskContract]] = (
        select(TaskContract)
        .where(TaskContract.assignee_user_id == assignee_user_id)
        .where(TaskContract.status.in_([TaskStatus.ACTIVE.value, TaskStatus.PROGRESS_UPDATED.value]))
        .order_by(TaskContract.updated_at.desc())
    )
    candidates = list(db.scalars(statement))
    if not candidates:
        return None

    requester_owned = [
        contract for contract in candidates if contract.initiator_user_id == requester_user_id
    ]
    candidates = requester_owned or candidates

    query_tokens = {token for token in query_text.lower().split() if len(token) > 1}
    for contract in candidates:
        haystack = f"{contract.title} {contract.description or ''}".lower()
        if any(token in haystack for token in query_tokens):
            return contract
    return candidates[0]
