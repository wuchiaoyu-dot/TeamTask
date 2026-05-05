from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_staging_dry_run_guide_exists() -> None:
    assert (ROOT / "docs/staging_dry_run_guide.md").exists()


def test_staging_manual_test_exists() -> None:
    assert (ROOT / "demo/staging_manual_test.md").exists()


def test_submission_brief_exists() -> None:
    assert (ROOT / "docs/submission_brief.md").exists()


def test_submission_brief_contains_core_concepts() -> None:
    content = (ROOT / "docs/submission_brief.md").read_text(encoding="utf-8")

    for phrase in ["Task Contract Ledger", "Todo Projection", "Reconciliation", "Change Proposal"]:
        assert phrase in content


def test_architecture_contains_mermaid_diagram() -> None:
    content = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")

    assert "```mermaid" in content
    assert "Feishu Group / Minutes / Docs" in content
    assert "Task Contract Ledger" in content
    assert "Todo Projection" in content
    assert "Reconciliation" in content


def test_staging_guide_contains_feishu_callback_paths() -> None:
    content = (ROOT / "docs/staging_dry_run_guide.md").read_text(encoding="utf-8")

    assert "/feishu/events" in content
    assert "/feishu/card-callback" in content
    assert "LARK_DRY_RUN=true" in content


def test_staging_manual_test_contains_five_scenarios() -> None:
    content = (ROOT / "demo/staging_manual_test.md").read_text(encoding="utf-8")

    for heading in ["Test 1", "Test 2", "Test 3", "Test 4", "Test 5"]:
        assert heading in content
    for phrase in [
        "Group Task Assignment",
        "Meeting Minutes Link",
        "Resource Recommendation",
        "Progress Query",
        "Reconciliation",
    ]:
        assert phrase in content
