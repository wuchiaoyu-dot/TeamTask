from __future__ import annotations

import re
from typing import Any

from app.config import get_settings, is_todo_projection_dry_run_enabled
from app.models import ChangeProposal, ProgressQuery, ReconciliationItem, ReconciliationRun, TaskContract

ACTION_INITIATOR_CONFIRM = "initiator_confirm"
ACTION_INITIATOR_IGNORE = "initiator_ignore"
ACTION_INITIATOR_EDIT_TASK = "initiator_edit_task"
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
    ACTION_INITIATOR_EDIT_TASK,
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
    dry_run = _confirmation_dry_run_enabled()
    actions = [
        _action(
            "确认并发送",
            ACTION_INITIATOR_CONFIRM,
            contract,
            recipient_user_id,
            button_type="primary",
            value={
                "action": "confirm_send",
                "task_id": str(contract.id),
                "dry_run": dry_run,
                "initiator_user_id": contract.initiator_user_id,
                "assignee_user_id": contract.assignee_user_id,
            },
        ),
        _action(
            "修改任务",
            ACTION_INITIATOR_EDIT_TASK,
            contract,
            recipient_user_id,
            button_type="default",
            value={
                "action": "edit_task",
                "task_id": str(contract.id),
                "dry_run": dry_run,
            },
        ),
        _action(
            "开始资源搜索",
            ACTION_INITIATOR_REQUEST_RESOURCE_SEARCH,
            contract,
            recipient_user_id,
            button_type="default",
            value={
                "action": "start_resource_search",
                "task_id": str(contract.id),
                "dry_run": dry_run,
                "initiator_user_id": contract.initiator_user_id,
                "assignee_user_id": contract.assignee_user_id,
            },
        ),
        _action(
            "取消",
            ACTION_INITIATOR_IGNORE,
            contract,
            recipient_user_id,
            button_type="danger",
            value={
                "action": "cancel_task",
                "task_id": str(contract.id),
                "dry_run": dry_run,
            },
        ),
    ]
    display_sections = _initiator_confirm_sections(contract)
    return _card(
        contract=contract,
        recipient_user_id=recipient_user_id,
        card_type="initiator_confirm",
        title="📌 任务分发确认",
        summary="我识别到你想分配一个任务，请确认是否发送给执行者。",
        task_fields={section["label"]: section["content"] for section in display_sections},
        actions=actions,
        primary_action_key=ACTION_INITIATOR_CONFIRM,
        display_sections=display_sections,
        footer_note=_dry_run_notice() if dry_run else None,
    )


def build_assignee_confirm_card(contract: TaskContract, recipient_user_id: str) -> dict:
    actions = [
        _action("确认接收", ACTION_ASSIGNEE_ACCEPT, contract, recipient_user_id, button_type="primary"),
        _action("提出修改", ACTION_ASSIGNEE_PROPOSE_CHANGE, contract, recipient_user_id, button_type="default"),
        _action("补充资源", ACTION_ASSIGNEE_REQUEST_RESOURCE_SEARCH, contract, recipient_user_id, button_type="default"),
        _action("不是我的任务", ACTION_ASSIGNEE_IGNORE, contract, recipient_user_id, button_type="danger"),
    ]
    display_sections = _assignee_confirm_sections(contract)
    return _card(
        contract=contract,
        recipient_user_id=recipient_user_id,
        card_type="assignee_confirm",
        title="📌 待确认任务",
        summary=f"{_readable_initiator(contract)} 分配给你一个任务，请确认是否接收。",
        task_fields={section["label"]: section["content"] for section in display_sections},
        actions=actions,
        primary_action_key=ACTION_ASSIGNEE_ACCEPT,
        display_sections=display_sections,
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
    display_sections: list[dict[str, str]] | None = None,
    footer_note: str | None = None,
) -> dict:
    card = {
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
    if display_sections is not None:
        card["display_sections"] = display_sections
    if footer_note:
        card["footer_note"] = footer_note
    return card


def _action(
    text: str,
    action_key: str,
    contract: TaskContract,
    recipient_user_id: str,
    button_type: str = "primary",
    value: dict[str, object] | None = None,
    **extra: object,
) -> dict:
    payload = {
        "action_key": action_key,
        "contract_id": contract.id,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contract.source_event_id,
        **extra,
    }
    action = {
        "text": text,
        "action_key": action_key,
        "button_type": button_type,
        "contract_id": contract.id,
        "recipient_user_id": recipient_user_id,
        "source_event_id": contract.source_event_id,
        "payload": payload,
    }
    if value is not None:
        action["value"] = value
    return action


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


def _initiator_confirm_sections(contract: TaskContract) -> list[dict[str, str]]:
    sections = [
        {"label": "任务内容", "content": _task_content(contract)},
        {"label": "执行者", "content": _readable_assignee(contract)},
        {"label": "截止时间", "content": _date(contract.deadline) or "待确认"},
    ]
    initiator_note = _initiator_note(contract)
    if initiator_note:
        sections.append({"label": "发起者补充", "content": initiator_note})
    sections.append({"label": "参考资源", "content": _resource_display(contract)})
    return sections


def _assignee_confirm_sections(contract: TaskContract) -> list[dict[str, str]]:
    return [
        {"label": "任务", "content": _task_title(contract)},
        {"label": "说明", "content": _task_description(contract)},
        {"label": "截止时间", "content": _date(contract.deadline) or "待补充"},
        {"label": "来源", "content": _source_label(contract)},
        {"label": "相关资源", "content": _assignee_resource_display(contract)},
        {"label": "提示", "content": "确认后，该任务将进入你的 Todo；如内容有误，可以提出修改。"},
    ]


def _task_content(contract: TaskContract) -> str:
    title = _sanitize_visible_text(contract.title, contract).strip()
    description = _sanitize_visible_text(contract.description or "", contract).strip()
    if description and description != title:
        return description
    return title or description or "待确认"


def _task_title(contract: TaskContract) -> str:
    return _sanitize_visible_text(contract.title or "", contract).strip() or "待补充"


def _task_description(contract: TaskContract) -> str:
    description = _sanitize_visible_text(contract.description or "", contract).strip()
    title = _task_title(contract)
    if description:
        return description
    return title


def _readable_initiator(contract: TaskContract) -> str:
    user = getattr(contract, "initiator", None)
    for value in (
        getattr(user, "display_name", None),
        getattr(user, "name", None),
    ):
        if value and not _looks_like_raw_user_id(str(value)):
            return f"@{value}"
    return "@发起人"


def _readable_assignee(contract: TaskContract) -> str:
    user = getattr(contract, "assignee", None)
    for value in (
        getattr(user, "display_name", None),
        getattr(user, "name", None),
    ):
        if value and not _looks_like_raw_user_id(str(value)):
            return str(value)
    return "已识别执行者，等待确认"


def _initiator_note(contract: TaskContract) -> str | None:
    raw_text = getattr(getattr(contract, "source_event", None), "raw_text", "") or ""
    match = re.search(r"(我负责[^，。；;,\n]*)", raw_text)
    if not match:
        return None
    return _sanitize_visible_text(match.group(1).strip(), contract)


def _resource_display(contract: TaskContract) -> str:
    resources = _related_resources(contract)
    all_resources = (resources["high_confidence"] or []) + (resources["low_confidence"] or [])
    high_resources = [item for item in all_resources if _resource_score(item) >= 0.75]
    high_resources.sort(key=_resource_score, reverse=True)
    if high_resources:
        return "\n".join(_format_resource_line(item, contract) for item in high_resources[:3])

    low_resources = [item for item in all_resources if _resource_score(item) < 0.75]
    low_resources.sort(key=_resource_score, reverse=True)
    if not low_resources:
        return "未找到高置信参考资料，可在修改任务时补充。"

    best = low_resources[0]
    return (
        "未找到高置信参考资料，可在修改任务时补充。\n"
        f"可选线索：{_sanitize_visible_text(str(best.get('title') or '未命名资源'), contract)}，"
        f"匹配度 {_score_percent(_resource_score(best))}"
    )


def _format_resource_line(item: dict[str, Any], contract: TaskContract) -> str:
    title = _sanitize_visible_text(str(item.get("title") or "未命名资源"), contract)
    url = item.get("url")
    score_text = _score_percent(_resource_score(item))
    if url:
        return f"[{title}]({url})，匹配度 {score_text}"
    return f"{title}，匹配度 {score_text}"


def _resource_score(item: dict[str, Any]) -> float:
    raw_score = item.get("score", item.get("confidence", 0))
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return 0.0
    return score / 100 if score > 1 else score


def _score_percent(score: float) -> str:
    return f"{round(score * 100)}%"


def _sanitize_visible_text(value: str, contract: TaskContract) -> str:
    text = value or ""
    replacements = {
        contract.initiator_user_id: "发起者",
        contract.assignee_user_id: "执行者",
    }
    for raw, label in sorted(replacements.items(), key=lambda item: len(item[0] or ""), reverse=True):
        if raw:
            text = re.sub(rf"\b{re.escape(raw)}\b", label, text)
    text = re.sub(r"\bou_[A-Za-z0-9_]+\b", "相关人员", text)
    text = re.sub(r"\bu_[A-Za-z0-9_]+\b", "相关人员", text)
    return text


def _source_label(contract: TaskContract) -> str:
    source_event = getattr(contract, "source_event", None)
    event_type = getattr(source_event, "event_type", None)
    if event_type == "meeting":
        return "会议纪要"
    if event_type == "group_message":
        return "群聊消息"
    return "群聊消息"


def _assignee_resource_display(contract: TaskContract) -> str:
    resources = _related_resources(contract)
    high = sorted(resources["high_confidence"] or [], key=_resource_score, reverse=True)
    low = sorted(resources["low_confidence"] or [], key=_resource_score, reverse=True)
    lines = ["✅ 明确提到"]
    lines.extend(_resource_group_lines(high, contract))
    lines.append("")
    lines.append("🔎 可能相关")
    lines.extend(_resource_group_lines(low, contract))
    return "\n".join(lines)


def _resource_group_lines(items: list[dict[str, Any]], contract: TaskContract) -> list[str]:
    if not items:
        return ["- 暂无"]
    return [f"- {_format_resource_line(item, contract)}" for item in items[:5]]


def _looks_like_raw_user_id(value: str) -> bool:
    return bool(re.fullmatch(r"(ou|u)_[A-Za-z0-9_]+", value))


def _confirmation_dry_run_enabled() -> bool:
    settings = get_settings()
    return (
        settings.env_profile == "staging_dry_run"
        or settings.feishu_mock
        or settings.lark_dry_run
        or settings.feishu_send_dry_run
        or is_todo_projection_dry_run_enabled(settings)
    )


def _dry_run_notice() -> str:
    return "当前为 staging dry-run：确认后只流转状态，不会写入多维表格。"


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
