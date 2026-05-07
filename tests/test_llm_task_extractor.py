from __future__ import annotations

import json

import httpx

from app.models import SourceEvent
from app.schemas.api import EventIn
from app.services.task_extractor import extract_task_candidates


def test_llm_task_extractor_splits_semantic_tasks(monkeypatch) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "llm")
    monkeypatch.setenv("LLM_TASK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TASK_MODEL", "test-model")
    monkeypatch.setenv("LLM_TASK_API_BASE", "https://llm.example/v1")

    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "task_candidates": [
                                        {
                                            "task_title": "Prepare competitor matrix",
                                            "task_description": "u_alice prepares the competitor matrix by 2026-06-01.",
                                            "project_name": "TeamTask Demo",
                                            "parent_task_title": None,
                                            "initiator": "u_pm",
                                            "assignee": "u_alice",
                                            "task_type": "follow_up",
                                            "workload_level": "medium",
                                            "deadline": "2026-06-01",
                                            "resource_keywords": ["competitor matrix"],
                                            "mentioned_resources": [],
                                            "evidence": ["Alice, please prepare the competitor matrix by 2026-06-01"],
                                            "missing_fields": [],
                                            "confidence": 0.91,
                                        },
                                        {
                                            "task_title": "Draft launch FAQ",
                                            "task_description": "u_bob drafts the launch FAQ by 2026-06-03.",
                                            "project_name": "TeamTask Demo",
                                            "parent_task_title": None,
                                            "initiator": "u_pm",
                                            "assignee": "u_bob",
                                            "task_type": "follow_up",
                                            "workload_level": "medium",
                                            "deadline": "2026-06-03",
                                            "resource_keywords": ["launch FAQ"],
                                            "mentioned_resources": [],
                                            "evidence": ["Bob owns the launch FAQ by 2026-06-03"],
                                            "missing_fields": [],
                                            "confidence": 0.9,
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: int):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    candidates = extract_task_candidates(_source_event(), _payload())

    assert [candidate.assignee for candidate in candidates] == ["u_alice", "u_bob"]
    assert [candidate.task_title for candidate in candidates] == [
        "Prepare competitor matrix",
        "Draft launch FAQ",
    ]
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert "task_candidates" in captured["body"]["messages"][0]["content"]


def test_auto_task_extractor_without_llm_config_uses_rule_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "auto")
    monkeypatch.setenv("LLM_TASK_API_KEY", "")
    monkeypatch.setenv("LLM_TASK_MODEL", "")

    candidates = extract_task_candidates(_source_event(), _payload())

    assert len(candidates) == 1
    assert candidates[0].assignee == "u_alice"
    assert candidates[0].deadline.isoformat() == "2026-06-01"


def test_llm_task_extractor_failure_uses_rule_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "llm")
    monkeypatch.setenv("TASK_EXTRACTOR_LLM_FALLBACK", "true")
    monkeypatch.setenv("LLM_TASK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TASK_MODEL", "test-model")

    class FailingClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def post(self, url: str, headers: dict, json: dict) -> object:
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "Client", FailingClient)

    candidates = extract_task_candidates(_source_event(), _payload())

    assert len(candidates) == 1
    assert candidates[0].assignee == "u_alice"


def test_llm_task_extractor_downgrades_unknown_assignee(monkeypatch) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "llm")
    monkeypatch.setenv("LLM_TASK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TASK_MODEL", "test-model")

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "task_candidates": [
                                        {
                                            "task_title": "Prepare competitor matrix",
                                            "task_description": "Alice prepares the competitor matrix.",
                                            "project_name": None,
                                            "parent_task_title": None,
                                            "initiator": "u_pm",
                                            "assignee": "Alice",
                                            "task_type": "follow_up",
                                            "workload_level": "medium",
                                            "deadline": None,
                                            "resource_keywords": [],
                                            "mentioned_resources": [],
                                            "evidence": ["Alice prepares the competitor matrix"],
                                            "missing_fields": [],
                                            "confidence": 0.9,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    candidates = extract_task_candidates(_source_event(), _payload())

    assert candidates[0].assignee == "u_alice"
    assert candidates[0].confidence == 0.45
    assert "assignee" in candidates[0].missing_fields


def test_llm_task_http_error_logs_response_without_api_key(monkeypatch, capsys) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "llm")
    monkeypatch.setenv("TASK_EXTRACTOR_LLM_FALLBACK", "true")
    monkeypatch.setenv("LLM_TASK_API_KEY", "test-secret-key")
    monkeypatch.setenv("LLM_TASK_MODEL", "test-model")
    monkeypatch.setenv("LLM_TASK_API_BASE", "https://llm.example/v1")

    class FakeResponse:
        status_code = 400
        text = "Ark rejected the request. key=test-secret-key"

        def raise_for_status(self) -> None:
            request = httpx.Request(
                "POST",
                "https://llm.example/v1/chat/completions?api_key=test-secret-key",
            )
            response = httpx.Response(self.status_code, text=self.text, request=request)
            raise httpx.HTTPStatusError("Bad request", request=request, response=response)

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    candidates = extract_task_candidates(_source_event(), _payload())
    captured = capsys.readouterr()

    assert candidates[0].assignee == "u_alice"
    assert "LLM_TASK_HTTP_ERROR status=400 url=" in captured.out
    assert "Ark rejected the request." in captured.out
    assert "[REDACTED]" in captured.out
    assert "test-secret-key" not in captured.out
    assert "Authorization" not in captured.out
    assert "Bearer" not in captured.out


def test_llm_task_response_format_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "llm")
    monkeypatch.setenv("LLM_TASK_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TASK_MODEL", "test-model")
    monkeypatch.setenv("LLM_TASK_RESPONSE_FORMAT", "none")

    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return _llm_success_response()

    class FakeClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            captured["body"] = json
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    candidates = extract_task_candidates(_source_event(), _payload())

    assert candidates[0].assignee == "u_alice"
    assert "response_format" not in captured["body"]


def test_llm_task_retries_without_response_format_when_provider_rejects_it(monkeypatch, capsys) -> None:
    monkeypatch.setenv("TASK_EXTRACTOR_BACKEND", "llm")
    monkeypatch.setenv("TASK_EXTRACTOR_LLM_FALLBACK", "false")
    monkeypatch.setenv("LLM_TASK_API_KEY", "test-secret-key")
    monkeypatch.setenv("LLM_TASK_MODEL", "test-model")
    monkeypatch.setenv("LLM_TASK_API_BASE", "https://ark.cn-beijing.volces.com/api/v3")

    captured_bodies: list[dict] = []

    class FakeResponse:
        def __init__(self, status_code: int, text: str):
            self.status_code = status_code
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                request = httpx.Request("POST", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
                response = httpx.Response(self.status_code, text=self.text, request=request)
                raise httpx.HTTPStatusError("Bad request", request=request, response=response)

        def json(self) -> dict:
            return _llm_success_response()

    class FakeClient:
        def __init__(self, timeout: int):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
            self.calls += 1
            captured_bodies.append(json)
            if self.calls == 1:
                return FakeResponse(
                    400,
                    "The parameter `response_format.type` specified in the request are not valid: "
                    "`json_object` is not supported by this model. key=test-secret-key",
                )
            return FakeResponse(200, "")

    monkeypatch.setattr(httpx, "Client", FakeClient)

    candidates = extract_task_candidates(_source_event(), _payload())
    captured = capsys.readouterr()

    assert candidates[0].assignee == "u_alice"
    assert "response_format" in captured_bodies[0]
    assert "response_format" not in captured_bodies[1]
    assert "LLM_TASK_HTTP_ERROR status=400 url=https://ark.cn-beijing.volces.com/api/v3/chat/completions" in captured.out
    assert "test-secret-key" not in captured.out


def _payload() -> EventIn:
    return EventIn(
        source_id="msg-llm",
        text=(
            "Alice, please prepare the competitor matrix by 2026-06-01. "
            "Bob owns the launch FAQ by 2026-06-03."
        ),
        sender_user_id="u_pm",
        participant_user_ids=["u_pm", "u_alice", "u_bob"],
        initiator_user_id="u_pm",
        assignee_user_id="u_alice",
        project_name="TeamTask Demo",
    )


def _source_event() -> SourceEvent:
    return SourceEvent(
        id=0,
        event_type="group_message",
        source_id="msg-llm",
        sender_user_id="u_pm",
        raw_text=_payload().text,
        participant_user_ids=["u_pm", "u_alice", "u_bob"],
    )


def _llm_success_response() -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "task_candidates": [
                                {
                                    "task_title": "Prepare competitor matrix",
                                    "task_description": "u_alice prepares the competitor matrix by 2026-06-01.",
                                    "project_name": "TeamTask Demo",
                                    "parent_task_title": None,
                                    "initiator": "u_pm",
                                    "assignee": "u_alice",
                                    "task_type": "follow_up",
                                    "workload_level": "medium",
                                    "deadline": "2026-06-01",
                                    "resource_keywords": ["competitor matrix"],
                                    "mentioned_resources": [],
                                    "evidence": ["Alice, please prepare the competitor matrix by 2026-06-01"],
                                    "missing_fields": [],
                                    "confidence": 0.91,
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
