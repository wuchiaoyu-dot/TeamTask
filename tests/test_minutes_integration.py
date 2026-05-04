from __future__ import annotations

import subprocess

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import PersonalTodoProjection, SourceEvent, TaskContract
from app.services.minutes_backend import MockMinutesBackend
from app.services.minutes_link_parser import extract_minutes_token, extract_minutes_url, is_minutes_link
from app.services.minutes_preprocessor import normalize_minutes_content


def test_can_recognize_feishu_minutes_link() -> None:
    text = "Please check https://example.feishu.cn/minutes/min_mock_123 for action items."

    assert is_minutes_link(text) is True
    assert extract_minutes_token(text) == "min_mock_123"
    assert extract_minutes_url(text) == "https://example.feishu.cn/minutes/min_mock_123"


def test_unparseable_token_keeps_original_url() -> None:
    text = "会议纪要 https://example.feishu.cn/docx/doc_unknown_token"

    assert is_minutes_link(text) is True
    assert extract_minutes_token(text) is None
    assert extract_minutes_url(text) == "https://example.feishu.cn/docx/doc_unknown_token"


def test_mock_minutes_backend_returns_content() -> None:
    content = MockMinutesBackend().get_minutes_content("min_mock_123")

    assert content.minutes_token == "min_mock_123"
    assert content.title == "TeamTask Weekly Planning"
    assert "行动项" in content.todos_text
    assert "u_alice" in content.participants


def test_minutes_preprocessor_extracts_action_sections() -> None:
    content = MockMinutesBackend().get_minutes_content("min_mock_123")
    normalized = normalize_minutes_content(content)

    assert normalized.action_sections
    assert any("u_alice" in section for section in normalized.action_sections)
    assert normalized.evidence_blocks


def test_long_transcript_is_truncated() -> None:
    content = MockMinutesBackend().get_minutes_content("min_mock_123")
    long_content = content.__class__(
        minutes_token=content.minutes_token,
        title=content.title,
        meeting_start_time=content.meeting_start_time,
        participants=content.participants,
        transcript_text="x" * 200,
        speaker_segments=[],
        summary_text=content.summary_text,
        todos_text=content.todos_text,
        source_url=content.source_url,
        raw_payload=content.raw_payload,
    )

    normalized = normalize_minutes_content(long_content, Settings(minutes_text_max_chars=80))

    assert normalized.truncated is True
    assert len(normalized.full_text) == 80


def test_meeting_minutes_event_creates_source_event(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post("/feishu/events", json=_real_minutes_message("evt-minutes-source"))

    assert response.status_code == 200
    with session_factory() as db:
        source_event = db.scalar(
            select(SourceEvent).where(SourceEvent.external_event_id == "evt-minutes-source")
        )

    assert source_event is not None
    assert source_event.event_type == "meeting"
    assert source_event.parsed_context_json is not None
    assert source_event.parsed_context_json["source_type"] == "meeting_minutes"


def test_meeting_minutes_event_generates_pending_initiator_contract(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post("/feishu/events", json=_real_minutes_message("evt-minutes-contract"))

    assert response.status_code == 200
    assert response.json()["contract_ids"]
    with session_factory() as db:
        contracts = db.scalars(
            select(TaskContract).join(SourceEvent).where(SourceEvent.external_event_id == "evt-minutes-contract")
        ).all()

    assert contracts
    assert any(contract.status == "pending_initiator_confirm" for contract in contracts)


def test_minutes_low_confidence_candidate_does_not_auto_write_todo(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post("/feishu/events", json=_real_minutes_message("evt-minutes-low-confidence"))

    assert response.status_code == 200
    body = response.json()
    assert any(
        candidate["confidence"] < 0.6 and "assignee" in candidate["missing_fields"]
        for candidate in body["task_candidates"]
    )
    with session_factory() as db:
        todos = db.scalars(select(PersonalTodoProjection)).all()

    assert todos == []


def test_multi_assignee_minutes_task_expands_candidates() -> None:
    response = TestClientPlaceholder.extract_tasks()

    multi = [
        candidate
        for candidate in response["task_candidates"]
        if candidate["parent_task_title"] and candidate["assignee"] in {"u_bob", "u_cara"}
    ]
    assert len(multi) == 2


def test_feishu_mock_true_minutes_does_not_call_lark_cli(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("MINUTES_BACKEND", "lark_cli")
    monkeypatch.setenv("FEISHU_MOCK", "true")

    def fail_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("subprocess.run should not be called in FEISHU_MOCK=true minutes mode")

    monkeypatch.setattr(subprocess, "run", fail_run)
    response = client.post("/debug/minutes/extract-tasks", json={"minutes_token_or_url": "min_mock_123"})

    assert response.status_code == 200
    assert response.json()["task_candidates"]


class TestClientPlaceholder:
    @staticmethod
    def extract_tasks() -> dict:
        content = MockMinutesBackend().get_minutes_content("min_mock_123")
        normalized = normalize_minutes_content(content)
        from app.models import SourceEvent
        from app.schemas.api import EventIn
        from app.services.task_extractor import extract_task_candidates

        payload = EventIn(
            source_id="min_mock_123",
            external_event_id="debug",
            text=normalized.full_text,
            sender_user_id="u_initiator",
            participant_user_ids=normalized.participants,
            initiator_user_id="u_initiator",
            source_link="https://example.feishu.cn/minutes/min_mock_123",
            parsed_context_json={
                "source_type": "meeting_minutes",
                "action_sections": normalized.action_sections,
                "evidence_blocks": normalized.evidence_blocks,
            },
        )
        source_event = SourceEvent(
            id=0,
            event_type="meeting",
            source_id="min_mock_123",
            sender_user_id="u_initiator",
            raw_text=normalized.full_text,
            participant_user_ids=normalized.participants,
            parsed_context_json=payload.parsed_context_json,
        )
        candidates = extract_task_candidates(source_event, payload)
        return {"task_candidates": [candidate.model_dump(mode="json") for candidate in candidates]}


def _real_minutes_message(event_id: str) -> dict:
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
                "message_id": f"om_{event_id}",
                "chat_id": "oc_minutes",
                "message_type": "text",
                "content": (
                    "{\"text\":\"Here are the meeting minutes: "
                    "https://example.feishu.cn/minutes/min_mock_123\"}"
                ),
                "mentions": [],
            },
        },
    }
