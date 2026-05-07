from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.cards.builders import ALLOWED_CARD_ACTION_KEYS

NEW_ACTION_KEY_MAP = {
    "confirm_send": "initiator_confirm",
    "edit_task": "initiator_edit_task",
    "start_resource_search": "initiator_request_resource_search",
    "cancel_task": "initiator_ignore",
}


@dataclass(frozen=True)
class CardAction:
    action_key: str
    contract_id: int
    recipient_user_id: str
    source_event_id: int | None
    form_value: dict[str, Any]
    raw_payload: dict[str, Any]


def adapt_feishu_card_action(payload: dict[str, Any]) -> CardAction:
    event = payload.get("event") or payload
    raw_action = event.get("action") or payload.get("action") or {}
    action = _as_dict(raw_action)
    value = _as_dict(action.get("value") or event.get("value") or payload.get("value"))
    if not value and isinstance(raw_action, str):
        value = event
    form_value = _as_dict(action.get("form_value") or event.get("form_value") or payload.get("form_value"))

    action_key = value.get("action_key") or NEW_ACTION_KEY_MAP.get(str(value.get("action") or ""))
    if action_key not in ALLOWED_CARD_ACTION_KEYS:
        raise ValueError("Unknown card action_key")

    contract_id = value.get("contract_id", value.get("task_id"))
    recipient_user_id = value.get("recipient_user_id") or value.get("initiator_user_id") or _operator_user_id(event)
    if contract_id is None or recipient_user_id is None:
        raise ValueError("contract_id/task_id and recipient_user_id/operator are required in card action value")

    extra_value = {
        key: item
        for key, item in value.items()
        if key
        not in {
            "action",
            "action_key",
            "contract_id",
            "task_id",
            "recipient_user_id",
            "source_event_id",
        }
    }

    return CardAction(
        action_key=str(action_key),
        contract_id=int(contract_id),
        recipient_user_id=str(recipient_user_id),
        source_event_id=int(value["source_event_id"]) if value.get("source_event_id") is not None else None,
        form_value={**extra_value, **form_value},
        raw_payload=payload,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _operator_user_id(event: dict[str, Any]) -> str | None:
    operator = _as_dict(event.get("operator"))
    user_id = _as_dict(operator.get("user_id"))
    return user_id.get("user_id") or operator.get("user_id")
