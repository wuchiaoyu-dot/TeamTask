from __future__ import annotations

import json

from app.runners.feishu_ws_runner import card_payload_from_sdk_data, event_payload_from_sdk_data
from app.services.feishu_card_adapter import adapt_feishu_card_action
from app.services.feishu_event_adapter import adapt_feishu_event


class _FakeLarkJSON:
    @staticmethod
    def marshal(data):  # noqa: ANN001
        return json.dumps(data)


class _FakeLark:
    JSON = _FakeLarkJSON


def test_ws_message_payload_injects_event_token_and_matches_existing_event_adapter() -> None:
    payload = event_payload_from_sdk_data(
        _sdk_like_message_payload("evt-ws-message"),
        verification_token="event-token",
        lark_module=_FakeLark,
    )

    assert payload["header"]["token"] == "event-token"
    adapted = adapt_feishu_event(payload)
    assert adapted.external_event_id == "evt-ws-message"
    assert adapted.source_type == "group_message"
    assert adapted.chat_id == "oc_ws_demo"
    assert adapted.trigger_user_id == "u_initiator"
    assert "u_assignee" in adapted.participant_user_ids


def test_ws_message_payload_skips_leading_bot_trigger_mention() -> None:
    payload = event_payload_from_sdk_data(
        _sdk_like_message_payload_with_bot_trigger("evt-ws-bot-trigger"),
        verification_token="event-token",
        lark_module=_FakeLark,
    )

    adapted = adapt_feishu_event(payload)

    assert adapted.participant_user_ids == ["u_initiator", "ou_human_assignee"]


def test_ws_card_payload_injects_card_token_and_matches_existing_card_adapter() -> None:
    payload = card_payload_from_sdk_data(
        _sdk_like_card_payload("initiator_confirm", 42, "u_initiator"),
        verification_token="card-token",
        lark_module=_FakeLark,
    )

    assert payload["header"]["token"] == "card-token"
    adapted = adapt_feishu_card_action(payload)
    assert adapted.action_key == "initiator_confirm"
    assert adapted.contract_id == 42
    assert adapted.recipient_user_id == "u_initiator"
    assert adapted.source_event_id == 7


def _sdk_like_message_payload(event_id: str) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {
                "sender_id": {
                    "user_id": "u_initiator",
                    "open_id": "ou_initiator",
                }
            },
            "message": {
                "message_id": "om_ws_demo",
                "chat_id": "oc_ws_demo",
                "message_type": "text",
                "content": "{\"text\":\"Please assign u_assignee to finish WebSocket staging by 2026-06-01.\"}",
                "mentions": [
                    {
                        "id": {
                            "user_id": "u_assignee",
                            "open_id": "ou_assignee",
                        }
                    }
                ],
            },
        },
    }


def _sdk_like_message_payload_with_bot_trigger(event_id: str) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {
                "sender_id": {
                    "user_id": "u_initiator",
                    "open_id": "ou_initiator",
                }
            },
            "message": {
                "message_id": "om_ws_demo",
                "chat_id": "oc_ws_demo",
                "message_type": "text",
                "content": "{\"text\":\"@_user_1@_user_2 please finish WebSocket staging.\"}",
                "mentions": [
                    {
                        "key": "@_user_1",
                        "id": {
                            "open_id": "ou_teamtask_bot",
                        },
                    },
                    {
                        "key": "@_user_2",
                        "id": {
                            "open_id": "ou_human_assignee",
                        },
                    },
                ],
            },
        },
    }


def _sdk_like_card_payload(action_key: str, contract_id: int, recipient_user_id: str) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "card-ws-event-1",
            "event_type": "card.action.trigger",
        },
        "event": {
            "operator": {
                "user_id": {
                    "user_id": recipient_user_id,
                    "open_id": f"ou_{recipient_user_id}",
                }
            },
            "action": {
                "tag": "button",
                "value": {
                    "action_key": action_key,
                    "contract_id": contract_id,
                    "recipient_user_id": recipient_user_id,
                    "source_event_id": 7,
                },
                "form_value": {},
            },
        },
    }
