from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.cards.builders import ALLOWED_CARD_ACTION_KEYS


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
    action = event.get("action") or payload.get("action") or {}
    value = _as_dict(action.get("value") or event.get("value") or payload.get("value"))
    form_value = _as_dict(action.get("form_value") or event.get("form_value") or payload.get("form_value"))

    action_key = value.get("action_key")
    if action_key not in ALLOWED_CARD_ACTION_KEYS:
        raise ValueError("Unknown card action_key")

    if "contract_id" not in value or "recipient_user_id" not in value:
        raise ValueError("contract_id and recipient_user_id are required in card action value")

    extra_value = {
        key: item
        for key, item in value.items()
        if key not in {"action_key", "contract_id", "recipient_user_id", "source_event_id"}
    }

    return CardAction(
        action_key=str(action_key),
        contract_id=int(value["contract_id"]),
        recipient_user_id=str(value["recipient_user_id"]),
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
