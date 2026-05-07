from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from app.clients.lark_cli_client import LarkCliClient


def test_from_env_uses_lark_cli_dry_run_for_send_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_PROFILE", "staging_dry_run")
    monkeypatch.setenv("LARK_DRY_RUN", "true")
    monkeypatch.setenv("LARK_CLI_DRY_RUN", "false")
    monkeypatch.setenv("FEISHU_SEND_DRY_RUN", "false")
    monkeypatch.setenv("BITABLE_DRY_RUN", "true")
    monkeypatch.setenv("TODO_PROJECTION_DRY_RUN", "true")

    client = LarkCliClient.from_env()

    assert client.send_dry_run is False
    assert client.dry_run is True


def test_lark_cli_write_operations_are_dry_run_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli")

    result = client.send_message("u_1", "hello")

    assert result["dry_run"] is True
    assert result["actor_mode"] == "as_bot"
    assert calls == []


def test_lark_cli_can_switch_actor_mode() -> None:
    client = LarkCliClient(cli_path="lark-cli", dry_run=True).as_user()

    result = client.send_card("u_1", {"type": "card"})

    assert result["actor_mode"] == "as_user"
    assert "--as" in result["command"]
    assert "user" in result["command"]
    assert "--dry-run" in result["command"]


def test_lark_cli_redacts_tokens_from_logged_commands() -> None:
    client = LarkCliClient(cli_path="lark-cli", dry_run=True)

    result = client.send_card("u_1", {"header": {"token": "secret-token"}, "body": "ok"})

    command_text = " ".join(result["command"])
    assert "secret-token" not in command_text
    assert "<redacted>" in command_text


def test_send_dry_run_false_allows_real_card_send_while_lark_dry_run_is_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="{\"message_id\":\"om_1\"}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)

    result = client.send_card("u_1", {"type": "card"})

    assert result["message_id"] == "om_1"
    assert calls
    assert "--dry-run" not in calls[0]


def test_real_lark_cli_send_uses_utf8_subprocess_env(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        assert kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["env"]["PYTHONUTF8"] == "1"
        assert kwargs["env"]["LC_ALL"] == "C.UTF-8"
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout='{"message":"确认卡片已发送","data":{"note":"中文输出"}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)

    result = client.send_card("u_1", {"type": "card"})

    assert result["message"] == "确认卡片已发送"
    assert result["data"]["note"] == "中文输出"


@pytest.mark.parametrize("stdout", [None, ""])
def test_real_lark_cli_empty_stdout_raises_readable_error(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str | None,
) -> None:
    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=stdout, stderr="auth required")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)

    with pytest.raises(RuntimeError) as exc:
        client.send_card("u_1", {"type": "card"})

    message = str(exc.value)
    assert "empty stdout" in message
    assert "send_card" in message
    assert "returncode=0" in message
    assert "auth required" in message
    assert "lark-cli" in message


def test_real_lark_cli_non_json_stdout_is_preserved_for_debugging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="登录已过期，请重新认证",
            stderr="scope missing",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)

    result = client.send_card("u_1", {"type": "card"})

    assert result["stdout"] == "登录已过期，请重新认证"
    assert result["stderr"] == "scope missing"
    assert "parse_error" in result


def test_send_dry_run_false_does_not_disable_todo_write_dry_run() -> None:
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)
    contract = SimpleNamespace(
        id=1,
        title="Protected Todo",
        description="Still dry-run",
        deadline=None,
        status="active",
        initiator_user_id="u_initiator",
        assignee_user_id="u_assignee",
    )

    result = client.create_todo_projection("u_assignee", contract)

    assert result["dry_run"] is True
    assert result["operation"] == "create_todo_projection"
    assert "--dry-run" in result["command"]
