from __future__ import annotations

import json
import subprocess

import pytest

from app.clients.lark_cli_client import LarkCliClient


def test_send_card_uses_open_id_receive_type_for_ou_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="{\"message_id\":\"om_1\"}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)

    client.send_card("ou_986cf7190a92a0e1fb25774822e56422", {"type": "card"})

    params = json.loads(calls[0][calls[0].index("--params") + 1])
    assert params["receive_id_type"] == "open_id"


def test_send_message_keeps_user_id_receive_type_for_non_open_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        calls.append(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="{\"message_id\":\"om_1\"}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = LarkCliClient(cli_path="lark-cli", dry_run=True, send_dry_run=False)

    client.send_message("98effdc2", "hello")

    params = json.loads(calls[0][calls[0].index("--params") + 1])
    assert params["receive_id_type"] == "user_id"
