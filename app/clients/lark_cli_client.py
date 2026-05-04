from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

from app.cards.feishu_renderer import render_feishu_card
from app.clients.feishu_client import FeishuClient

if TYPE_CHECKING:
    from app.models import TaskContract

ActorMode = Literal["as_user", "as_bot"]

logger = logging.getLogger(__name__)
SENSITIVE_MARKERS = ("token", "secret", "authorization", "access-token", "app-secret")
WRITE_OPERATIONS = {
    "send_message",
    "send_card",
    "send_group_message",
    "create_todo_projection",
    "update_todo_projection",
    "create_bitable_record",
    "update_bitable_record",
}


@dataclass(frozen=True)
class LarkCliClient(FeishuClient):
    cli_path: str = "lark-cli"
    dry_run: bool = True
    actor_mode: ActorMode = "as_bot"
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if self.actor_mode not in {"as_user", "as_bot"}:
            raise ValueError("actor_mode must be 'as_user' or 'as_bot'")

    @classmethod
    def from_env(cls) -> LarkCliClient:
        return cls(
            cli_path=os.getenv("LARK_CLI_PATH", "lark-cli"),
            dry_run=_env_bool("LARK_DRY_RUN", default=True),
            actor_mode=os.getenv("LARK_ACTOR_MODE", "as_bot"),
        )

    def as_user(self) -> LarkCliClient:
        return replace(self, actor_mode="as_user")

    def as_bot(self) -> LarkCliClient:
        return replace(self, actor_mode="as_bot")

    def send_message(self, user_id: str, text: str) -> dict[str, Any]:
        data = {
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        args = [
            "api",
            "POST",
            "/open-apis/im/v1/messages",
            "--params",
            json.dumps({"receive_id_type": "user_id"}, ensure_ascii=False),
            "--data",
            json.dumps(data, ensure_ascii=False),
        ]
        return self._run("send_message", args, write=True)

    def send_card(self, user_id: str, card_json: dict[str, Any]) -> dict[str, Any]:
        rendered_card = render_feishu_card(card_json) if _is_internal_card(card_json) else card_json
        data = {
            "receive_id": user_id,
            "msg_type": "interactive",
            "content": json.dumps(rendered_card, ensure_ascii=False, default=str),
        }
        args = [
            "api",
            "POST",
            "/open-apis/im/v1/messages",
            "--params",
            json.dumps({"receive_id_type": "user_id"}, ensure_ascii=False),
            "--data",
            json.dumps(data, ensure_ascii=False, default=str),
        ]
        return self._run("send_card", args, write=True)

    def send_group_message(self, chat_id: str, text: str) -> dict[str, Any]:
        args = [
            "im",
            "+messages-send",
            "--chat-id",
            chat_id,
            "--text",
            text,
        ]
        return self._run("send_group_message", args, write=True)

    def get_minutes_transcript(self, minutes_token: str) -> dict[str, Any]:
        args = [
            "vc",
            "+minutes",
            "--minutes-token",
            minutes_token,
        ]
        return self._run("get_minutes_transcript", args, write=False)

    def search_docs(self, user_id: str, query: str) -> list[dict[str, Any]]:
        args = [
            "docs",
            "+search",
            "--query",
            query,
        ]
        result = self._run("search_docs", args, write=False)
        if isinstance(result.get("data"), list):
            return result["data"]
        return [result]

    def create_todo_projection(self, user_id: str, task_contract: TaskContract) -> dict[str, Any]:
        contract_payload = {
            "contract_id": task_contract.id,
            "title": task_contract.title,
            "description": task_contract.description,
            "deadline": task_contract.deadline.isoformat() if task_contract.deadline else None,
            "status": task_contract.status,
            "initiator_user_id": task_contract.initiator_user_id,
            "assignee_user_id": task_contract.assignee_user_id,
        }
        args = [
            "task",
            "+create",
            "--title",
            task_contract.title,
            "--description",
            task_contract.description or "",
            "--assignee-id",
            user_id,
            "--external-id",
            f"teamtask:{task_contract.id}",
            "--metadata",
            json.dumps(contract_payload, ensure_ascii=False, default=str),
        ]
        if task_contract.deadline:
            args.extend(["--due-date", task_contract.deadline.isoformat()])
        return self._run("create_todo_projection", args, write=True)

    def update_todo_projection(
        self,
        user_id: str,
        contract_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        args = [
            "task",
            "+update",
            "--external-id",
            f"teamtask:{contract_id}",
            "--assignee-id",
            user_id,
            "--patch-json",
            json.dumps(patch, ensure_ascii=False, default=str),
        ]
        return self._run("update_todo_projection", args, write=True)

    def create_bitable_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        args = [
            "api",
            "POST",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            "--data",
            json.dumps({"fields": fields}, ensure_ascii=False, default=str),
        ]
        return self._run("create_bitable_record", args, write=True)

    def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        args = [
            "api",
            "PUT",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
            "--data",
            json.dumps({"fields": fields}, ensure_ascii=False, default=str),
        ]
        return self._run("update_bitable_record", args, write=True)

    def get_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        args = [
            "api",
            "GET",
            f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        ]
        return self._run("get_bitable_record", args, write=False)

    def _run(self, operation: str, args: list[str], write: bool) -> dict[str, Any]:
        if write and operation not in WRITE_OPERATIONS:
            raise ValueError(f"Unknown write operation: {operation}")

        command = [self.cli_path, *args, "--as", _cli_actor(self.actor_mode)]
        if write and self.dry_run:
            command.append("--dry-run")
        redacted_command = _redact_args(command)
        logger.info("lark-cli operation=%s dry_run=%s command=%s", operation, self.dry_run, redacted_command)

        if write and self.dry_run:
            return {
                "dry_run": True,
                "operation": operation,
                "actor_mode": self.actor_mode,
                "command": redacted_command,
            }

        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        logger.info(
            "lark-cli operation=%s returncode=%s stderr=%s",
            operation,
            completed.returncode,
            _redact_text(completed.stderr),
        )

        if completed.returncode != 0:
            raise RuntimeError(
                f"lark-cli failed for {operation}: returncode={completed.returncode} "
                f"stderr={_redact_text(completed.stderr)}"
            )

        return _parse_cli_stdout(operation, completed.stdout, self.actor_mode, redacted_command)


def _parse_cli_stdout(
    operation: str,
    stdout: str,
    actor_mode: ActorMode,
    redacted_command: list[str],
) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {
            "operation": operation,
            "actor_mode": actor_mode,
            "command": redacted_command,
            "stdout": "",
        }

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {
            "operation": operation,
            "actor_mode": actor_mode,
            "command": redacted_command,
            "stdout": _redact_text(text),
        }

    if isinstance(parsed, dict):
        parsed.setdefault("operation", operation)
        parsed.setdefault("actor_mode", actor_mode)
        return parsed

    return {
        "operation": operation,
        "actor_mode": actor_mode,
        "command": redacted_command,
        "data": parsed,
    }


def _is_internal_card(card_json: dict[str, Any]) -> bool:
    return "card_type" in card_json and "actions" in card_json and "task_fields" in card_json


def _cli_actor(actor_mode: ActorMode) -> str:
    return "user" if actor_mode == "as_user" else "bot"


def _redact_args(args: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for arg in args:
        lowered = arg.lower()
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        redacted.append(_redact_text(arg))
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            redact_next = True
    return redacted


def _redact_text(text: str) -> str:
    json_redacted = _redact_json_text(text)
    if json_redacted is not None:
        return json_redacted

    redacted = text
    for env_name in (
        "FEISHU_APP_SECRET",
        "FEISHU_APP_ID",
        "FEISHU_ACCESS_TOKEN",
        "LARK_ACCESS_TOKEN",
        "FEISHU_BITABLE_APP_TOKEN",
    ):
        value = os.getenv(env_name)
        if value:
            redacted = redacted.replace(value, "<redacted>")
    for marker in SENSITIVE_MARKERS:
        redacted = re.sub(
            rf"({re.escape(marker)}\s*[=:]\s*)[^\s,;&]+",
            rf"\1<redacted>",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            rf'("{re.escape(marker)}"\s*:\s*")[^"]+(")',
            rf'\1<redacted>\2',
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def _redact_json_text(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    return json.dumps(_redact_json_value(parsed), ensure_ascii=False, default=str)


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(marker in key.lower() for marker in SENSITIVE_MARKERS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_json_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
