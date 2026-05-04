from __future__ import annotations

import subprocess

import pytest

from app.clients.lark_cli_client import LarkCliClient


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
