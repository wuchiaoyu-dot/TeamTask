from __future__ import annotations

from app.models import SourceEvent, TaskContract, User

PROGRESS_RECONCILE_SCOPE = "progress_reconcile"
SOURCE_CONTEXT_READ_SCOPE = "source_context:read"


def _has_active_grant(user: User, scope: str, subject_id: str | None = None) -> bool:
    for grant in user.auth_grants:
        if not grant.is_active or grant.scope != scope:
            continue
        if grant.subject_id is None or subject_id is None or grant.subject_id == subject_id:
            return True
    return False


def can_read_source_context(user: User, source_event: SourceEvent) -> bool:
    if user.id == source_event.sender_user_id:
        return True
    if user.id in (source_event.participant_user_ids or []):
        return True
    return _has_active_grant(user, SOURCE_CONTEXT_READ_SCOPE, str(source_event.id))


def can_write_personal_todo(user: User, todo_owner: User) -> bool:
    return user.id == todo_owner.id


def can_confirm_as_initiator(user: User, task_contract: TaskContract) -> bool:
    return user.id == task_contract.initiator_user_id


def can_confirm_as_assignee(user: User, task_contract: TaskContract) -> bool:
    return user.id == task_contract.assignee_user_id


def can_reconcile_pair(requester: User, initiator: User, assignee: User) -> bool:
    if requester.id not in {initiator.id, assignee.id}:
        return False
    initiator_authorized = _has_active_grant(initiator, PROGRESS_RECONCILE_SCOPE, assignee.id)
    assignee_authorized = _has_active_grant(assignee, PROGRESS_RECONCILE_SCOPE, initiator.id)
    return initiator_authorized and assignee_authorized
