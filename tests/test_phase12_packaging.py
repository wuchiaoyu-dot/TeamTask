from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core.external_read_guard import should_allow_external_read
from app.core.external_write_guard import should_allow_external_write


ROOT = Path(__file__).resolve().parents[1]


def test_local_mock_profile_defaults_to_no_real_read_or_write(monkeypatch) -> None:
    monkeypatch.delenv("ENV_PROFILE", raising=False)
    monkeypatch.setenv("FEISHU_MOCK", "true")
    monkeypatch.setenv("LARK_DRY_RUN", "true")
    monkeypatch.setenv("FEISHU_ENABLE_REAL_READ", "false")
    monkeypatch.setenv("TODO_BACKEND", "mock")
    settings = get_settings()

    assert settings.env_profile == "local_mock"
    assert settings.feishu_mock is True
    assert settings.lark_dry_run is True
    assert settings.lark_cli_dry_run is True
    assert settings.feishu_send_dry_run is True
    assert settings.bitable_dry_run is True
    assert settings.todo_projection_dry_run is True
    assert should_allow_external_read(settings) is False
    assert should_allow_external_write(settings) is False


def test_staging_dry_run_profile_receives_events_but_does_not_write(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENV_PROFILE", "staging_dry_run")
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("LARK_DRY_RUN", "true")
    monkeypatch.setenv("LARK_CLI_DRY_RUN", "false")
    monkeypatch.setenv("FEISHU_SEND_DRY_RUN", "false")
    monkeypatch.setenv("BITABLE_DRY_RUN", "true")
    monkeypatch.setenv("TODO_PROJECTION_DRY_RUN", "true")
    monkeypatch.setenv("TODO_BACKEND", "bitable")
    monkeypatch.setenv("FEISHU_ENABLE_REAL_READ", "false")

    response = client.post(
        "/feishu/events",
        json={
            "event_id": "evt-phase12-staging",
            "event_type": "group_message",
            "chat_id": "stage_chat",
            "text": "Please assign u_assignee to finish staging smoke task by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask",
        },
    )

    assert response.status_code == 200
    assert response.json()["contract_status"] == "pending_initiator_confirm"
    settings = get_settings()
    assert settings.lark_cli_dry_run is False
    assert settings.feishu_send_dry_run is False
    assert settings.bitable_dry_run is True
    assert settings.todo_projection_dry_run is True
    assert should_allow_external_write(settings) is False


def test_production_trial_missing_allowed_users_readiness_warns(
    client: TestClient,
    monkeypatch,
) -> None:
    _set_production_trial_env(monkeypatch)
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)

    response = client.get("/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["allowed_users_configured"] is False
    assert any("ALLOWED_USER_IDS" in warning for warning in body["warnings"])


def test_non_allowlisted_user_cannot_trigger_real_write(
    client: TestClient,
    monkeypatch,
) -> None:
    contract_id = _submit_assignment(client, "evt-phase12-write-guard")
    _set_production_trial_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_USER_IDS", "u_allowed")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "oc_demo_chat")

    response = client.post(
        "/debug/bitable/create-real",
        json={"contract_id": contract_id, "owner_user_id": "u_initiator", "role": "initiator"},
    )

    assert response.status_code == 403


def test_non_allowlisted_chat_cannot_trigger_real_group_processing(
    client: TestClient,
    monkeypatch,
) -> None:
    _set_production_trial_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_USER_IDS", "u_initiator")
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "oc_allowed_chat")

    response = client.post(
        "/feishu/events",
        json={
            "event_id": "evt-phase12-chat-guard",
            "event_type": "group_message",
            "chat_id": "oc_blocked_chat",
            "text": "Please assign u_assignee to finish blocked chat task by 2026-06-01.",
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
        },
    )

    assert response.status_code == 403


def test_health_returns_key_config_state(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "env_profile" in body
    assert "feishu_mock" in body
    assert "lark_dry_run" in body
    assert "lark_cli_dry_run" in body
    assert "feishu_send_dry_run" in body
    assert "bitable_dry_run" in body
    assert "todo_projection_dry_run" in body
    assert "todo_backend" in body
    assert "minutes_backend" in body
    assert "resource_search_backend" in body


def test_readiness_reports_missing_callback_config(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ENV_PROFILE", "staging_dry_run")
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_CARD_VERIFICATION_TOKEN", raising=False)

    response = client.get("/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["feishu_callback_config_ok"] is False
    assert any("verification tokens" in warning for warning in body["warnings"])


def test_demo_smoke_test_api_chain_runs_with_test_client(
    client: TestClient,
) -> None:
    contract_id = _submit_assignment(client, "evt-phase12-demo-chain")
    _grant(client, "u_initiator", "progress_reconcile", "user", "u_assignee")
    _grant(client, "u_assignee", "progress_reconcile", "user", "u_initiator")

    initiator = client.post(
        "/feishu/card-callback",
        json={"action_key": "initiator_confirm", "contract_id": contract_id, "recipient_user_id": "u_initiator"},
    )
    assert initiator.status_code == 200
    assignee = client.post(
        "/feishu/card-callback",
        json={"action_key": "assignee_accept", "contract_id": contract_id, "recipient_user_id": "u_assignee"},
    )
    assert assignee.status_code == 200

    resources = client.post(
        "/debug/resources/search",
        json={"contract_id": contract_id, "user_id": "u_initiator", "write_back": True},
    )
    assert resources.status_code == 200

    query = client.post(
        "/debug/progress/query",
        json={
            "requester_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "query_text": "Is u_assignee done with the competitive analysis?",
        },
    )
    assert query.status_code == 200
    progress_query_id = query.json()["progress_query_id"]

    confirm = client.post(
        "/debug/progress/confirm",
        json={
            "progress_query_id": progress_query_id,
            "assignee_user_id": "u_assignee",
            "action_key": "progress_mark_completed",
            "progress_text": "Completed in demo smoke.",
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["updated_task_contract"]["completion_status"] == "completed"

    reconciliation = client.post(
        "/debug/reconciliation/run",
        json={"requester_user_id": "u_initiator", "scope": "single_task", "contract_id": contract_id},
    )
    assert reconciliation.status_code == 200
    assert "run_id" in reconciliation.json()


def test_openclaw_manifest_exists_with_five_capabilities() -> None:
    manifest = json.loads((ROOT / "openclaw" / "skill_manifest.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "teamtask-agent"
    assert len(manifest["capabilities"]) == 5
    assert {item["name"] for item in manifest["capabilities"]} == {
        "parse_meeting_minutes_tasks",
        "assign_task_from_group_message",
        "query_task_progress",
        "run_task_reconciliation",
        "search_related_resources",
    }


def test_debug_system_status_does_not_expose_sensitive_config(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FEISHU_APP_SECRET", "super_secret_value")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "bitable_token_value")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verification_token_value")

    response = client.get("/debug/system/status")

    assert response.status_code == 200
    body_text = json.dumps(response.json())
    assert "super_secret_value" not in body_text
    assert "bitable_token_value" not in body_text
    assert "verification_token_value" not in body_text


def _set_production_trial_env(monkeypatch) -> None:
    monkeypatch.setenv("ENV_PROFILE", "production_trial")
    monkeypatch.setenv("FEISHU_MOCK", "false")
    monkeypatch.setenv("LARK_DRY_RUN", "false")
    monkeypatch.setenv("LARK_CLI_DRY_RUN", "false")
    monkeypatch.setenv("FEISHU_ENABLE_REAL_READ", "true")
    monkeypatch.setenv("BITABLE_DRY_RUN", "false")
    monkeypatch.setenv("TODO_PROJECTION_DRY_RUN", "false")
    monkeypatch.setenv("RESOURCE_SEARCH_REAL_READ", "true")
    monkeypatch.setenv("RESOURCE_SEARCH_DRY_RUN", "false")
    monkeypatch.setenv("TODO_BACKEND", "bitable")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "app_token_for_test")
    monkeypatch.setenv("FEISHU_BITABLE_TABLE_ID", "table_for_test")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "event_token_for_test")
    monkeypatch.setenv("FEISHU_CARD_VERIFICATION_TOKEN", "card_token_for_test")


def _submit_assignment(client: TestClient, event_id: str) -> int:
    response = client.post(
        "/feishu/events",
        json={
            "event_id": event_id,
            "event_type": "group_message",
            "chat_id": "oc_demo_chat",
            "text": (
                "Please assign u_assignee to finish the competitive analysis by 2026-06-01. "
                "Refer to LaunchPlan document."
            ),
            "sender_user_id": "u_initiator",
            "participant_user_ids": ["u_initiator", "u_assignee"],
            "initiator_user_id": "u_initiator",
            "assignee_user_id": "u_assignee",
            "project_name": "TeamTask Demo",
        },
    )
    assert response.status_code == 200
    return response.json()["contract_id"]


def _grant(
    client: TestClient,
    user_id: str,
    scope: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
) -> None:
    response = client.post(
        "/dev/auth-grants",
        json={"user_id": user_id, "scope": scope, "subject_type": subject_type, "subject_id": subject_id},
    )
    assert response.status_code == 200
