from __future__ import annotations

from app.models import ChangeProposal, ProgressQuery, ReconciliationItem, ReconciliationRun, TaskContract

ACTION_INITIATOR_CONFIRM = "initiator_confirm"
ACTION_INITIATOR_IGNORE = "initiator_ignore"
ACTION_INITIATOR_REQUEST_RESOURCE_SEARCH = "initiator_request_resource_search"
ACTION_ASSIGNEE_ACCEPT = "assignee_accept"
ACTION_ASSIGNEE_IGNORE = "assignee_ignore"
ACTION_ASSIGNEE_PROPOSE_CHANGE = "assignee_propose_change"
ACTION_ASSIGNEE_REQUEST_RESOURCE_SEARCH = "assignee_request_resource_search"
ACTION_PROGRESS_CONFIRM = "progress_confirm"
ACTION_PROGRESS_MARK_COMPLETED = "progress_mark_completed"
ACTION_PROGRESS_MARK_IN_PROGRESS = "progress_mark_in_progress"
ACTION_PROGRESS_MARK_DELAYED = "progress_mark_delayed"
ACTION_PROGRESS_MARK_BLOCKED = "progress_mark_blocked"
ACTION_PROGRESS_NO_SUCH_TASK = "progress_no_such_task"
ACTION_PROGRESS_SELECT_TASK = "progress_select_task"
ACTION_CHANGE_PROPOSAL_APPROVE = "change_proposal_approve"
ACTION_CHANGE_PROPOSAL_REJECT = "change_proposal_reject"
ACTION_RECONCILIATION_APPROVE_CHANGE = "reconciliation_approve_change"
ACTION_RECONCILIATION_REJECT_CHANGE = "reconciliation_reject_change"
ACTION_RECONCILIATION_SYNC_PROGRESS = "reconciliation_sync_progress"
ACTION_RECONCILIATION_MERGE_RESOURCES = "reconciliation_merge_resources"
ACTION_RECONCILIATION_IGNORE_DIFF = "reconciliation_ignore_diff"
ACTION_RECONCILIATION_REQUEST_MORE_INFO = "reconciliation_request_more_info"

ALLOWED_CARD_ACTION_KEYS = {
    ACTION_INITIATOR_CONFIRM,
    ACTION_INITIATOR_IGNORE,
    ACTION_INITIATOR_REQUEST_RESOURCE_SEARCH,
    ACTION_ASSIGNEE_ACCEPT,
    ACTION_ASSIGNEE_IGNORE,
    ACTION_ASSIGNEE_PROPOSE_CHANGE,
    ACTION_ASSIGNEE_REQUEST_RESOURCE_SEARCH,
    ACTION_PROGRESS_CONFIRM,
    ACTION_PROGRESS_MARK_COMPLETED,
    ACTION_PROGRESS_MARK_IN_PROGRESS,
    ACTION_PROGRESS_MARK_DELAYED,
    ACTION_PROGRESS_MARK_BLOCKED,
    ACTION_PROGRESS_NO_SUCH_TASK,
    ACTION_PROGRESS_SELECT_TASK,
    ACTION_CHANGE_PROPOSAL_APPROVE,
    ACTION_CHANGE_PROPOSAL_REJECT,
    ACTION_RECONCILIATION_APPROVE_CHANGE,
    ACTION_RECONCILIATION_REJECT_CHANGE,
    ACTION_RECONCILIATION_SYNC_PROGRESS,
    ACTION_RECONCILIATION_MERGE_RESOURCES,
    ACTION_RECONCILIATION_IGNORE_DIFF,
    ACTION_RECONCILIATION_REQUEST_MORE_INFO,
}


def build_initiator_confirm_card(contract: TaskContract, recipient_user_id: str) -> dict:
    actions = [
        _action("Confirm", ACTION_INITIATOR_CONFIRM, contract, recipient_user_id),
        _action("Ignore", ACTION_INITIATOR_IGNORE, contract, recipient_user_id),
        _action("Start resource search", ACTION_INITIATOR_REQUEST_RESOURCE_SEARCH, contract, recipient_user_id),
    ]
    return _card(
        contract=contract,
        recipient_user_id=recipient_user_id,
        card_type="initiator_confirm",
        title="Confirm team task distribution",
        summary=f"Please confirm whether to send this task to {contract.assignee_user_id}.",
        task_fields={
            "title": contract.title,
            "description": contract.description,
            "project_name": contract.project_name,
            "initiator_user_id": contract.initiator_user_id,
            "assignee_user_id": contract.assignee_user_id,
            "deadline": _date(contract.deadline),
            "confidence": contract.confidence,
            "missing_fields": contract.missing_fields,
        },
        actions=actions,
        primary_action_key=ACTION_INITIATOR_CONFIRM,
    )


def build_assignee_confirm_card(contract: TaskContract, recipient_user_id: str) -> dict:
    actions = [
        _action("Accept", ACTION_ASSIGNEE_ACCEPT, contract, recipient_user_id),
        _action("Propose change", ACTION_ASSIGNEE_PROPOSE_CHANGE, contract, recipient_user_id),
        _action("Search resources", ACTION_ASSIGNEE_REQUEST_RESOURCE_SEARCH, contract, recipient_user_id),
        _action("Ignore", ACTION_ASSIGNEE_IGNORE, contract, recipient_user_id),
    ]
    return _card(
        contract=contract,
        recipient_user_id=recipient_user_id,
        card_type="assignee_confirm",
        title="Confirm assigned task",
        summary=f"{contract.initiator_user_id} asks you to confirm this task.",
        task_fields={
            "title": contract.title,
            "description": contract.description,
            "project_name": contract.project_name,
            "initiator_user_id": contract.initiator_user_id,
            "assignee_user_id": contract.assignee_user_id,
            "deadline": _date(contract.deadline),
            "status": contract.status,
        },
        actions=actions,
        primary_action_key=ACTION_ASSIGNEE_ACCEPT,
    )


def build_progress_confirm_card(
    contract: TaskContract,
    recipient_user_id: str,
    query_text: str,
    progress_query: ProgressQuery | None = None,
    requester_user_id: str | None = None,
    chat_id: str | None = None,
) -> dict:
    actions = [
        _action(
            "Completed",
            ACTION_PROGRESS_MARK_COMPLETED,
            contract,
            recipient_user_id,
            progress_query_id=progress_query.id if progress_query else None,
            query_text=query_text,
        ),
        _action(
            "In progress",
            ACTION_PROGRESS_MARK_IN_PROGRESS,
            contract,
            recipient_user_id,
            progress_query_id=progress_query.id if progress_query else None,
            query_text=query_text,
        ),
        _action(
            "Delayed",
            ACTION_PROGRESS_MARK_DELAYED,
            contract,
            recipient_user_id,
            progress_query_id=progress_query.id if progress_query else None,
            query_text=query_text,
        ),
        _action(
            "Blocked",
            ACTION_PROGRESS_MARK_BLOCKED,
            contract,
            recipient_user_id,
            progress_query_id=progress_query.id if progress_query else None,
            query_text=query_text,
        ),
        _action(
            "No such task",
            ACTION_PROGRESS_NO_SUCH_TASK,
            contract,
            recipient_user_id,
            progress_query_id=progress_query.id if progress_query else None,
            query_text=query_text,
        ),
    ]
    return _card(
        contract=contract,
        recipient_user_id=recipient_user_id,
        card_type="progress_confirm",
        title="Confirm current progress",
        summary=f"Progress query: {query_text}",
        task_fields={
            "title": contract.title,
            "initiator_user_id": contract.initiator_user_id,
            "assignee_user_id": contract.assignee_user_id,
            "current_status": contract.completion_status,
            "deadline": _date(contract.deadline),
            "last_progress_text": contract.progress_text or contract.progress_summary,
            "requester_user_id": requester_user_id or (progress_query.requester_user_id if progress_query else None),
            "chat_id": chat_id,
            "related_resources_summary": _resource_summary(contract),
        },
        actions=actions,
        primary_action_key=ACTION_PROGRESS_MARK_IN_PROGRESS,
    )


def build_progress_task_select_card(
    progress_query: ProgressQuery,
    contracts: list[TaskContract],
    recipient_user_id: str,
) -> dict:
    actions = [
        {
            "text": contract.title,
            "action_key": ACTION_PROGRESS_SELECT_TASK,
            "contract_id": contract.id,
            "recipient_user_id": recipient_user_id,
            "source_event_id": contract.source_event_id,
            "payload": {
                "action_key": ACTION_PROGRESS_SELECT_TASK,
                "contract_id": contract.id,
                "recipient_user_id": recipient_user_id,
                "source_event_id": contract.source_event_id,
                "progress_query_id": progress_query.id,
            },
        }
        for contract in contracts
    ]
    return {
        "card_type": "progress_task_select",
        "title": "Select task for progress query",
        "summary": progress_query.query_text,
        "task_fields": {
            "requester_user_id": progress_query.requester_user_id,
            "assignee_user_id": progress_query.assignee_user_id,
            "matched_count": len(contracts),
            "candidates": [
                {
                    "contract_id": contract.id,
                    "title": contract.title,
                    "deadline": _date(contract.deadline),
                    "completion_status": contract.completion_status,
                }
                for contract in contracts
            ],
        },
        "actions": actions,
        "buttons": actions,
        "action_key": ACTION_PROGRESS_SELECT_TASK,
        "contract_id": contracts[0].id if contracts else None,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contracts[0].source_event_id if contracts else None,
        "progress_query_id": progress_query.id,
    }


def build_progress_reply_payload(progress_query: ProgressQuery, contract: TaskContract | None) -> dict:
    if contract is None:
        title = "Progress query result"
        summary = progress_query.response_summary or "The assignee did not confirm this task."
        task_fields = {
            "requester_user_id": progress_query.requester_user_id,
            "assignee_user_id": progress_query.assignee_user_id,
            "query_status": progress_query.query_status,
        }
    else:
        title = f"Progress update: {contract.title}"
        summary = progress_query.response_summary or contract.progress_text or "Progress confirmed."
        task_fields = {
            "contract_id": contract.id,
            "title": contract.title,
            "initiator_user_id": contract.initiator_user_id,
            "assignee_user_id": contract.assignee_user_id,
            "completion_status": contract.completion_status,
            "progress_text": contract.progress_text,
            "deadline": _date(contract.deadline),
        }
    return {
        "card_type": "progress_reply",
        "title": title,
        "summary": summary,
        "task_fields": task_fields,
        "actions": [],
        "buttons": [],
        "action_key": "progress_reply",
        "contract_id": contract.id if contract else None,
        "recipient_user_id": progress_query.requester_user_id,
        "source_event_id": contract.source_event_id if contract else None,
        "progress_query_id": progress_query.id,
    }


def build_reconciliation_review_card(
    item: ReconciliationItem,
    contract: TaskContract,
    recipient_user_id: str,
) -> dict:
    diffs = item.field_diffs_json or {}
    actions = [
        _reconciliation_action("Approve change", ACTION_RECONCILIATION_APPROVE_CHANGE, item, contract, recipient_user_id),
        _reconciliation_action("Reject change", ACTION_RECONCILIATION_REJECT_CHANGE, item, contract, recipient_user_id),
        _reconciliation_action(
            "Sync progress",
            ACTION_RECONCILIATION_SYNC_PROGRESS,
            item,
            contract,
            recipient_user_id,
        ),
        _reconciliation_action(
            "Merge resources",
            ACTION_RECONCILIATION_MERGE_RESOURCES,
            item,
            contract,
            recipient_user_id,
        ),
        _reconciliation_action("Ignore diff", ACTION_RECONCILIATION_IGNORE_DIFF, item, contract, recipient_user_id),
        _reconciliation_action(
            "Request more info",
            ACTION_RECONCILIATION_REQUEST_MORE_INFO,
            item,
            contract,
            recipient_user_id,
        ),
    ]
    return {
        "card_type": "reconciliation_review",
        "title": "Review Todo projection differences",
        "summary": f"{len(diffs)} field difference(s) found for {contract.title}.",
        "task_fields": {
            "contract_id": contract.id,
            "title": contract.title,
            "initiator_user_id": contract.initiator_user_id,
            "assignee_user_id": contract.assignee_user_id,
            "diff_status": item.diff_status,
            "field_diffs": diffs,
            "related_resources": _related_resources(contract),
            "evidence": contract.evidence,
        },
        "actions": actions,
        "buttons": actions,
        "action_key": ACTION_RECONCILIATION_IGNORE_DIFF,
        "contract_id": contract.id,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contract.source_event_id,
        "reconciliation_item_id": item.id,
        "related_resources": _related_resources(contract),
    }


def build_reconciliation_summary_card(run: ReconciliationRun) -> dict:
    items = run.items or []
    counts: dict[str, int] = {}
    for item in items:
        counts[item.diff_status] = counts.get(item.diff_status, 0) + 1
    need_review = sum(1 for item in items if item.diff_status == "has_diff")
    return {
        "card_type": "reconciliation_summary",
        "title": "Daily reconciliation summary",
        "summary": run.summary or "Reconciliation run completed.",
        "task_fields": {
            "run_id": run.id,
            "scope": run.scope,
            "run_type": run.run_type,
            "status": run.status,
            "task_count": len(items),
            "consistent_count": counts.get("consistent", 0),
            "has_diff_count": counts.get("has_diff", 0),
            "permission_denied_count": counts.get("permission_denied", 0),
            "missing_projection_count": counts.get("missing_initiator_projection", 0)
            + counts.get("missing_assignee_projection", 0),
            "need_review_count": need_review,
        },
        "actions": [],
        "buttons": [],
        "action_key": "reconciliation_summary",
        "contract_id": run.contract_id,
        "recipient_user_id": run.requester_user_id,
        "source_event_id": None,
        "reconciliation_run_id": run.id,
    }


def build_change_proposal_card(
    contract: TaskContract,
    proposal: ChangeProposal,
    recipient_user_id: str,
) -> dict:
    actions = [
        _action(
            "Approve",
            ACTION_CHANGE_PROPOSAL_APPROVE,
            contract,
            recipient_user_id,
            proposal_id=proposal.id,
        ),
        _action(
            "Reject",
            ACTION_CHANGE_PROPOSAL_REJECT,
            contract,
            recipient_user_id,
            proposal_id=proposal.id,
        ),
    ]
    return _card(
        contract=contract,
        recipient_user_id=recipient_user_id,
        card_type="change_proposal",
        title="Review task change proposal",
        summary=f"{proposal.proposer_user_id} proposed a task contract change.",
        task_fields={
            "current": {
                "title": contract.title,
                "description": contract.description,
                "deadline": _date(contract.deadline),
            },
            "proposed": {
                "proposal_id": proposal.id,
                "title": proposal.proposed_title,
                "description": proposal.proposed_description,
                "deadline": _date(proposal.proposed_deadline),
                "reason": proposal.reason,
                "status": proposal.status,
            },
        },
        actions=actions,
        primary_action_key=ACTION_CHANGE_PROPOSAL_APPROVE,
    )


def _card(
    contract: TaskContract,
    recipient_user_id: str,
    card_type: str,
    title: str,
    summary: str,
    task_fields: dict,
    actions: list[dict],
    primary_action_key: str,
) -> dict:
    return {
        "card_type": card_type,
        "title": title,
        "summary": summary,
        "task_fields": task_fields,
        "actions": actions,
        "buttons": actions,
        "action_key": primary_action_key,
        "contract_id": contract.id,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contract.source_event_id,
        "related_resources": _related_resources(contract),
    }


def _action(
    text: str,
    action_key: str,
    contract: TaskContract,
    recipient_user_id: str,
    **extra: object,
) -> dict:
    return {
        "text": text,
        "action_key": action_key,
        "contract_id": contract.id,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contract.source_event_id,
        "payload": {
            "action_key": action_key,
            "contract_id": contract.id,
            "recipient_user_id": recipient_user_id,
            "source_event_id": contract.source_event_id,
            **extra,
        },
    }


def _reconciliation_action(
    text: str,
    action_key: str,
    item: ReconciliationItem,
    contract: TaskContract,
    recipient_user_id: str,
) -> dict:
    return {
        "text": text,
        "action_key": action_key,
        "contract_id": contract.id,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contract.source_event_id,
        "payload": {
            "action_key": action_key,
            "contract_id": contract.id,
            "recipient_user_id": recipient_user_id,
            "source_event_id": contract.source_event_id,
            "reconciliation_item_id": item.id,
        },
    }


def _date(value) -> str | None:
    return value.isoformat() if value else None


def _related_resources(contract: TaskContract) -> dict:
    resources = contract.related_resources_json or {"high_confidence": [], "low_confidence": []}
    return {
        "status": contract.resource_search_status,
        "error": contract.resource_search_error,
        "high_confidence": resources.get("high_confidence") or [],
        "low_confidence": resources.get("low_confidence") or [],
    }


def _resource_summary(contract: TaskContract) -> str:
    resources = _related_resources(contract)
    high = resources["high_confidence"]
    low = resources["low_confidence"]
    parts = []
    if high:
        parts.append(f"{len(high)} high-confidence")
    if low:
        parts.append(f"{len(low)} low-confidence")
    return ", ".join(parts) if parts else "No related resources"
