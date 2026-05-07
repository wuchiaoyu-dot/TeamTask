from __future__ import annotations

import subprocess

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.clients.lark_cli_client import LarkCliClient
from app.models import PersonalTodoProjection, SourceEvent, TaskContract
from app.services.feishu_card_adapter import adapt_feishu_card_action
from app.services.feishu_event_adapter import adapt_feishu_event


def test_challenge_request_does_not_create_task_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify-token")

    response = client.post(
        "/feishu/events",
        json={
            "type": "url_verification",
            "token": "verify-token",
            "challenge": "challenge-code",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-code"}
    with session_factory() as db:
        assert db.scalars(select(TaskContract)).all() == []


def test_real_feishu_message_payload_converts_to_internal_source_event() -> None:
    adapted = adapt_feishu_event(_real_message_payload("evt-real-adapter"))

    assert adapted.external_event_id == "evt-real-adapter"
    assert adapted.source_type == "group_message"
    assert adapted.chat_id == "oc_demo"
    assert adapted.message_id == "om_demo"
    assert adapted.trigger_user_id == "u_initiator"
    assert "TeamTask real callback" in adapted.text
    assert "u_assignee" in adapted.participant_user_ids


def test_real_feishu_event_duplicate_id_does_not_create_duplicate_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify-token")
    payload = _real_message_payload("evt-real-dedup", token="verify-token")

    first = client.post("/feishu/events", json=payload)
    second = client.post("/feishu/events", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deduplicated"] is True
    assert second.json()["contract_id"] == first.json()["contract_id"]

    with session_factory() as db:
        source_events = db.scalars(
            select(SourceEvent).where(SourceEvent.external_event_id == "evt-real-dedup")
        ).all()
        contracts = db.scalars(
            select(TaskContract).where(TaskContract.source_event_id == source_events[0].id)
        ).all()

    assert len(source_events) == 1
    assert len(contracts) == 1


def test_real_feishu_card_payload_converts_to_internal_card_action() -> None:
    adapted = adapt_feishu_card_action(_real_card_payload("initiator_confirm", 123, "u_initiator"))

    assert adapted.action_key == "initiator_confirm"
    assert adapted.contract_id == 123
    assert adapted.recipient_user_id == "u_initiator"
    assert adapted.source_event_id == 99


def test_new_initiator_card_button_values_convert_to_legacy_handlers() -> None:
    confirm = adapt_feishu_card_action(
        _new_card_value_payload(
            {
                "action": "confirm_send",
                "task_id": "123",
                "dry_run": True,
                "initiator_user_id": "u_initiator",
                "assignee_user_id": "u_assignee",
            }
        )
    )
    edit = adapt_feishu_card_action(
        _new_card_value_payload({"action": "edit_task", "task_id": "123", "dry_run": True})
    )
    resource_search = adapt_feishu_card_action(
        _new_card_value_payload(
            {
                "action": "start_resource_search",
                "task_id": "123",
                "dry_run": True,
                "initiator_user_id": "u_initiator",
                "assignee_user_id": "u_assignee",
            }
        )
    )
    cancel = adapt_feishu_card_action(
        _new_card_value_payload({"action": "cancel_task", "task_id": "123", "dry_run": True})
    )

    assert confirm.action_key == "initiator_confirm"
    assert confirm.contract_id == 123
    assert confirm.recipient_user_id == "u_initiator"
    assert edit.action_key == "initiator_edit_task"
    assert edit.recipient_user_id == "u_initiator"
    assert resource_search.action_key == "initiator_request_resource_search"
    assert resource_search.recipient_user_id == "u_initiator"
    assert cancel.action_key == "initiator_ignore"
    assert cancel.recipient_user_id == "u_initiator"


def test_illegal_action_key_returns_400(client: TestClient) -> None:
    response = client.post(
        "/feishu/card-callback",
        json=_real_card_payload("llm_generated_surprise", 1, "u_initiator"),
    )

    assert response.status_code == 400


def test_real_card_callback_wrong_recipient_returns_403(client: TestClient) -> None:
    event_response = client.post("/feishu/events", json=_real_message_payload("evt-real-permission"))
    assert event_response.status_code == 200
    contract_id = event_response.json()["contract_id"]

    response = client.post(
        "/feishu/card-callback",
        json=_real_card_payload("initiator_confirm", contract_id, "u_assignee"),
    )

    assert response.status_code == 403


def test_feishu_mock_true_does_not_call_lark_cli(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    def fail_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("subprocess.run should not be called in FEISHU_MOCK=true mode")

    monkeypatch.setattr(subprocess, "run", fail_run)
    event_response = client.post("/feishu/events", json=_real_message_payload("evt-real-mock-safe"))
    contract_id = event_response.json()["contract_id"]

    response = client.post(
        "/feishu/card-callback",
        json=_real_card_payload("initiator_confirm", contract_id, "u_initiator"),
    )

    assert response.status_code == 200
    with session_factory() as db:
        todo = db.scalar(
            select(PersonalTodoProjection).where(
                PersonalTodoProjection.contract_id == contract_id,
                PersonalTodoProjection.owner_user_id == "u_initiator",
            )
        )
    assert todo is not None


def test_lark_dry_run_true_does_not_execute_real_write(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True)

    result = client.send_card(
        "u_assignee",
        {
            "card_type": "assignee_confirm",
            "title": "Dry-run card",
            "summary": "No real write",
            "task_fields": {"title": "Task"},
            "actions": [
                {
                    "text": "Accept",
                    "action_key": "assignee_accept",
                    "contract_id": 1,
                    "recipient_user_id": "u_assignee",
                    "source_event_id": 1,
                    "payload": {
                        "action_key": "assignee_accept",
                        "contract_id": 1,
                        "recipient_user_id": "u_assignee",
                        "source_event_id": 1,
                    },
                }
            ],
            "action_key": "assignee_accept",
            "contract_id": 1,
            "recipient_user_id": "u_assignee",
            "source_event_id": 1,
        },
    )

    assert result["dry_run"] is True
    assert "--dry-run" in result["command"]
    assert calls == []


def _real_message_payload(event_id: str, token: str | None = None) -> dict:
    header = {
        "event_id": event_id,
        "event_type": "im.message.receive_v1",
    }
    if token:
        header["token"] = token
    return {
        "schema": "2.0",
        "header": header,
        "event": {
            "sender": {
                "sender_id": {
                    "user_id": "u_initiator",
                    "open_id": "ou_initiator",
                }
            },
            "message": {
                "message_id": "om_demo",
                "chat_id": "oc_demo",
                "message_type": "text",
                "content": (
                    "{\"text\":\"Please assign u_assignee to finish the TeamTask real callback "
                    "task by 2026-06-01.\"}"
                ),
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


def _real_card_payload(action_key: str, contract_id: int, recipient_user_id: str) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "card-event-1",
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
                    "source_event_id": 99,
                },
                "form_value": {
                    "progress_summary": "Dry-run progress",
                },
            },
        },
    }


def _new_card_value_payload(value: dict) -> dict:
    return {
        "schema": "2.0",
        "header": {
            "event_id": "card-event-1",
            "event_type": "card.action.trigger",
        },
        "event": {
            "operator": {
                "user_id": {
                    "user_id": "u_initiator",
                    "open_id": "ou_initiator",
                }
            },
            "action": {
                "tag": "button",
                "value": value,
                "form_value": {},
            },
        },
    }
