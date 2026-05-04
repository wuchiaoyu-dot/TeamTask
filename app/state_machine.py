from __future__ import annotations

from enum import StrEnum

from app.models import TaskContract


class InvalidStateTransition(ValueError):
    pass


class TaskStatus(StrEnum):
    CANDIDATE_EXTRACTED = "candidate_extracted"
    PENDING_INITIATOR_CONFIRM = "pending_initiator_confirm"
    PENDING_ASSIGNEE_CONFIRM = "pending_assignee_confirm"
    ACTIVE = "active"
    PROGRESS_UPDATED = "progress_updated"
    CHANGE_PENDING_INITIATOR_REVIEW = "change_pending_initiator_review"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    IGNORED = "ignored"


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.CANDIDATE_EXTRACTED: {
        TaskStatus.PENDING_INITIATOR_CONFIRM,
        TaskStatus.PENDING_ASSIGNEE_CONFIRM,
        TaskStatus.IGNORED,
    },
    TaskStatus.PENDING_INITIATOR_CONFIRM: {
        TaskStatus.PENDING_ASSIGNEE_CONFIRM,
        TaskStatus.IGNORED,
    },
    TaskStatus.PENDING_ASSIGNEE_CONFIRM: {
        TaskStatus.ACTIVE,
        TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW,
        TaskStatus.IGNORED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.ACTIVE: {
        TaskStatus.PROGRESS_UPDATED,
        TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.PROGRESS_UPDATED: {
        TaskStatus.PROGRESS_UPDATED,
        TaskStatus.ACTIVE,
        TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW,
        TaskStatus.COMPLETED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW: {
        TaskStatus.ACTIVE,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.IGNORED: set(),
}


def _as_status(value: str) -> TaskStatus:
    try:
        return TaskStatus(value)
    except ValueError as exc:
        raise InvalidStateTransition(f"Unknown task status: {value}") from exc


def transition(contract: TaskContract, next_status: TaskStatus) -> TaskContract:
    current = _as_status(contract.status)
    if next_status not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"Illegal task state transition: {current} -> {next_status}")
    contract.status = next_status.value
    return contract


def mark_pending_initiator_confirm(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.PENDING_INITIATOR_CONFIRM)


def confirm_initiator(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.PENDING_ASSIGNEE_CONFIRM)


def assignee_accept(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.ACTIVE)


def assignee_propose_change(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW)


def record_progress_update(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.PROGRESS_UPDATED)


def reactivate_after_progress(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.ACTIVE)


def resolve_change_review(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.ACTIVE)


def complete_contract(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.COMPLETED)


def cancel_contract(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.CANCELLED)


def ignore_contract(contract: TaskContract) -> TaskContract:
    return transition(contract, TaskStatus.IGNORED)
