from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from demo.demo_smoke_test import run_smoke_test


ROOT = Path(__file__).resolve().parents[1]


def test_demo_smoke_dependencies_exist() -> None:
    for relative in [
        "demo/sample_minutes.txt",
        "demo/sample_group_messages.json",
        "demo/sample_users.json",
        "demo/sample_bitable_schema.md",
        "demo/demo_script.md",
        "demo/demo_smoke_test.py",
        "openclaw/skill_manifest.json",
    ]:
        assert (ROOT / relative).exists(), relative


def test_demo_script_contains_full_eight_step_storyline() -> None:
    content = (ROOT / "demo/demo_script.md").read_text(encoding="utf-8")

    for phrase in [
        "会议纪要产生任务",
        "发起者确认",
        "执行者确认",
        "推荐参考资源",
        "群聊查询进度",
        "执行者确认进度",
        "对账发现 DDL 不一致",
        "发起者审核变更",
    ]:
        assert phrase in content


def test_architecture_doc_contains_core_concepts() -> None:
    content = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")

    assert "Task Contract Ledger" in content
    assert "Todo Projection" in content
    assert "Reconciliation" in content


def test_api_demo_collection_contains_key_endpoints() -> None:
    content = (ROOT / "docs/api_demo_collection.md").read_text(encoding="utf-8")

    for endpoint in [
        "/health",
        "/readiness",
        "/feishu/events",
        "/feishu/card-callback",
        "/debug/resources/search",
        "/debug/progress/query",
        "/debug/progress/confirm",
        "/debug/reconciliation/run",
        "/debug/reconciliation/apply-action",
    ]:
        assert endpoint in content


def test_troubleshooting_covers_demo_risks() -> None:
    content = (ROOT / "docs/troubleshooting.md").read_text(encoding="utf-8")

    for phrase in ["卡片点击", "Bitable", "scope", "白名单", "LARK_DRY_RUN", "pytest"]:
        assert phrase in content


def test_health_and_readiness_are_available_in_local_mock(client: TestClient) -> None:
    health = client.get("/health")
    readiness = client.get("/readiness")

    assert health.status_code == 200
    assert health.json()["env_profile"] == "local_mock"
    assert readiness.status_code == 200
    assert readiness.json()["database_ok"] is True


def test_sensitive_fields_do_not_appear_in_demo_output(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_APP_SECRET", "demo_super_secret")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "demo_app_token")
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "demo_verification_token")

    summary = run_smoke_test(emit_logs=False)
    output = json.dumps(summary, ensure_ascii=False)

    assert "demo_super_secret" not in output
    assert "demo_app_token" not in output
    assert "demo_verification_token" not in output
    assert summary["result"]["review_applied"] is True
