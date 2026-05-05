from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import httpx

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


class DemoApi(Protocol):
    def get(self, path: str) -> dict[str, Any]:
        ...

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def inject_deadline_diff(self, contract_id: int, new_deadline: str) -> bool:
        ...


def run_smoke_test(base_url: str | None = None, emit_logs: bool = True) -> dict[str, Any]:
    event_suffix = time.time_ns()
    summary: dict[str, Any] = {
        "mode": "http" if base_url else "in_process_local_mock",
        "base_url": base_url or "in-process FastAPI TestClient",
        "final_summary": "",
        "steps": [],
    }

    with _api_client(base_url) as api:
        health = api.get("/health")
        _record(summary, emit_logs, 1, "创建 mock 用户", f"profile={health['env_profile']}")
        for user_id in ("u_initiator", "u_assignee"):
            for scope in ("minutes:read", "docs:read", "drive:read", "base:read", "progress_reconcile"):
                _post(api, "/dev/auth-grants", {"user_id": user_id, "scope": scope})

        event = _post(
            api,
            "/feishu/events",
            {
                "event_id": f"demo-minutes-{event_suffix}",
                "event_type": "meeting_minutes",
                "chat_id": "oc_demo_chat",
                "text": (
                    "Action items: Please assign u_assignee to finish the competitive analysis "
                    "brief by 2026-06-01. Refer to LaunchPlan document."
                ),
                "sender_user_id": "u_initiator",
                "participant_user_ids": ["u_initiator", "u_assignee"],
                "initiator_user_id": "u_initiator",
                "assignee_user_id": "u_assignee",
                "project_name": "TeamTask Demo",
            },
        )
        contract_id = event["contract_id"]
        _record(summary, emit_logs, 2, "提交会议纪要事件", f"contract_id={contract_id}")
        _record(
            summary,
            emit_logs,
            3,
            "生成任务候选",
            f"status={event['contract_status']} candidates={len(event.get('task_candidates', []))}",
        )

        initiator = _post(
            api,
            "/feishu/card-callback",
            {"action_key": "initiator_confirm", "contract_id": contract_id, "recipient_user_id": "u_initiator"},
        )
        _record(summary, emit_logs, 4, "发起者确认", f"status={initiator['status']}")

        assignee = _post(
            api,
            "/feishu/card-callback",
            {"action_key": "assignee_accept", "contract_id": contract_id, "recipient_user_id": "u_assignee"},
        )
        _record(summary, emit_logs, 5, "执行者接受", f"status={assignee['status']}")

        resources = _post(
            api,
            "/debug/resources/search",
            {"contract_id": contract_id, "user_id": "u_initiator", "write_back": True},
        )
        _record(
            summary,
            emit_logs,
            6,
            "资源推荐",
            f"high={len(resources['high_confidence'])} low={len(resources['low_confidence'])}",
        )

        progress_query = _post(
            api,
            "/debug/progress/query",
            {
                "requester_user_id": "u_initiator",
                "assignee_user_id": "u_assignee",
                "query_text": "Is u_assignee done with the competitive analysis?",
            },
        )
        progress_query_id = progress_query["progress_query_id"]
        _record(summary, emit_logs, 7, "进度查询", f"progress_query_id={progress_query_id}")

        progress_confirm = _post(
            api,
            "/debug/progress/confirm",
            {
                "progress_query_id": progress_query_id,
                "assignee_user_id": "u_assignee",
                "action_key": "progress_mark_completed",
                "progress_text": "Completed for the demo.",
            },
        )
        completion_status = progress_confirm["updated_task_contract"]["completion_status"]
        _record(summary, emit_logs, 8, "执行者确认进度", f"completion_status={completion_status}")

        injected = api.inject_deadline_diff(contract_id, "2026-06-08")
        reconciliation = _post(
            api,
            "/debug/reconciliation/run",
            {"requester_user_id": "u_initiator", "scope": "single_task", "contract_id": contract_id},
        )
        item = _first_diff_item(reconciliation)
        diff_fields = sorted((item.get("field_diffs_json") or {}).keys()) if item else []
        _record(
            summary,
            emit_logs,
            9,
            "对账发现差异",
            f"run_id={reconciliation['run_id']} diff_fields={diff_fields} demo_diff_injected={injected}",
        )

        review_result: dict[str, Any] | None = None
        if item and "deadline" in (item.get("field_diffs_json") or {}):
            review_result = _post(
                api,
                "/debug/reconciliation/apply-action",
                {
                    "reconciliation_item_id": item["id"],
                    "action_key": "reconciliation_approve_change",
                    "actor_user_id": "u_initiator",
                    "field_name": "deadline",
                    "resolution_value": "2026-06-08",
                },
            )
        final = {
            "contract_id": contract_id,
            "progress_query_id": progress_query_id,
            "reconciliation_run_id": reconciliation["run_id"],
            "diff_fields": diff_fields,
            "review_applied": review_result is not None,
            "completion_status": completion_status,
        }
        summary["final_summary"] = (
            "TeamTask demo completed: task assigned, accepted, resource-ranked, progress-confirmed, "
            f"reconciled fields={diff_fields}, review_applied={review_result is not None}."
        )
        _record(summary, emit_logs, 10, "审核并输出最终 summary", summary["final_summary"])
        summary["result"] = final

    return summary


@contextmanager
def _api_client(base_url: str | None) -> Iterator[DemoApi]:
    if base_url:
        with httpx.Client(base_url=base_url, timeout=20.0) as client:
            yield _HttpDemoApi(client)
        return

    local_mock_env = {
        "TEAMTASK_SKIP_DB_INIT": "1",
        "ENV_PROFILE": "local_mock",
        "FEISHU_MOCK": "true",
        "LARK_DRY_RUN": "true",
        "FEISHU_ENABLE_REAL_READ": "false",
        "TODO_BACKEND": "mock",
        "MINUTES_BACKEND": "mock",
        "RESOURCE_SEARCH_BACKEND": "mock",
        "ALLOWED_USER_IDS": "",
        "ALLOWED_CHAT_IDS": "",
        "FEISHU_VERIFICATION_TOKEN": "",
        "FEISHU_CARD_VERIFICATION_TOKEN": "",
    }
    previous_env = {name: os.environ.get(name) for name in local_mock_env}
    os.environ.update(local_mock_env)

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base, get_db
    from app.main import app, feishu_client
    from app.models import PersonalTodoProjection

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    feishu_client.sent_cards.clear()
    try:
        with TestClient(app) as client:
            yield _InProcessDemoApi(client, session_factory, PersonalTodoProjection, select)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class _HttpDemoApi:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def get(self, path: str) -> dict[str, Any]:
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def inject_deadline_diff(self, contract_id: int, new_deadline: str) -> bool:
        return False


class _InProcessDemoApi:
    def __init__(self, client: Any, session_factory: Any, projection_model: Any, select_func: Any) -> None:
        self.client = client
        self.session_factory = session_factory
        self.projection_model = projection_model
        self.select = select_func

    def get(self, path: str) -> dict[str, Any]:
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def inject_deadline_diff(self, contract_id: int, new_deadline: str) -> bool:
        with self.session_factory() as db:
            projection = db.scalar(
                self.select(self.projection_model).where(
                    self.projection_model.contract_id == contract_id,
                    self.projection_model.role == "assignee",
                )
            )
            if projection is None:
                return False
            projection.snapshot_json = {**(projection.snapshot_json or {}), "deadline": new_deadline}
            db.commit()
            return True


def _post(api: DemoApi, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return api.post(path, payload)


def _record(summary: dict[str, Any], emit_logs: bool, number: int, name: str, detail: str) -> None:
    item = {"number": number, "name": name, "detail": detail}
    summary["steps"].append(item)
    if emit_logs:
        print(f"[{number}/10] {name}: {detail}")


def _first_diff_item(reconciliation: dict[str, Any]) -> dict[str, Any] | None:
    for item in reconciliation.get("items", []):
        if item.get("diff_status") == "has_diff":
            return item
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TeamTask Agent local demo smoke test.")
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional running TeamTask base URL. Omit to run against an in-process local mock app.",
    )
    args = parser.parse_args()
    summary = run_smoke_test(args.base_url)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
