from __future__ import annotations

import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from app.config import Settings, get_settings
from app.core.external_write_guard import assert_external_write_allowed, should_allow_external_write

logger = logging.getLogger(__name__)
SENSITIVE_MARKERS = ("token", "secret", "authorization", "access-token", "app-secret")


class BitableClient(ABC):
    @abstractmethod
    def create_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def update_record(self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_records(self, app_token: str, table_id: str, filter_expr: str) -> list[dict[str, Any]]:
        raise NotImplementedError


class MockBitableClient(BitableClient):
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def create_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> str:
        record_id = f"mock_bitable_record_{uuid4()}"
        self.records[record_id] = {"record_id": record_id, "fields": fields, "table_id": table_id}
        logger.info("MockBitableClient create table_id=%s fields=%s", table_id, fields)
        return record_id

    def update_record(self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        if record_id not in self.records:
            raise KeyError(f"Bitable record not found: {record_id}")
        self.records[record_id]["fields"] = {**self.records[record_id].get("fields", {}), **fields}
        logger.info("MockBitableClient update table_id=%s record_id=%s fields=%s", table_id, record_id, fields)

    def get_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        if record_id not in self.records:
            raise KeyError(f"Bitable record not found: {record_id}")
        return self.records[record_id]

    def search_records(self, app_token: str, table_id: str, filter_expr: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records.values()
            if filter_expr in json.dumps(record.get("fields", {}), ensure_ascii=False, default=str)
        ]


class LarkCliBitableClient(BitableClient):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def create_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> str:
        logger.info(
            "LarkCliBitableClient create dry_run=%s command=%s fields=%s",
            self.settings.lark_dry_run,
            _redact_args(_create_args(app_token, table_id, fields)),
            _redact_value(fields),
        )
        if not should_allow_external_write(self.settings):
            return f"dry_run_record_{uuid4()}"
        assert_external_write_allowed(self.settings)
        result = _run_lark_cli(self.settings, _create_args(app_token, table_id, fields), write=True)
        return _record_id_from_result(result)

    def update_record(self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        logger.info(
            "LarkCliBitableClient update dry_run=%s command=%s fields=%s",
            self.settings.lark_dry_run,
            _redact_args(_update_args(app_token, table_id, record_id, fields)),
            _redact_value(fields),
        )
        if not should_allow_external_write(self.settings):
            return
        assert_external_write_allowed(self.settings)
        _run_lark_cli(self.settings, _update_args(app_token, table_id, record_id, fields), write=True)

    def get_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        if self.settings.lark_dry_run:
            return {"record_id": record_id, "fields": {}, "dry_run": True}
        result = _run_lark_cli(self.settings, _get_args(app_token, table_id, record_id), write=False)
        return _record_from_result(result)

    def search_records(self, app_token: str, table_id: str, filter_expr: str) -> list[dict[str, Any]]:
        if self.settings.lark_dry_run:
            return []
        result = _run_lark_cli(self.settings, _search_args(app_token, table_id, filter_expr), write=False)
        records = result.get("items") or result.get("data", {}).get("items") or []
        return records if isinstance(records, list) else []


class FeishuOpenApiBitableClient(BitableClient):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def create_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> str:
        raise NotImplementedError("TODO: implement Feishu OpenAPI Bitable create_record over HTTPS")

    def update_record(self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        raise NotImplementedError("TODO: implement Feishu OpenAPI Bitable update_record over HTTPS")

    def get_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        raise NotImplementedError("TODO: implement Feishu OpenAPI Bitable get_record over HTTPS")

    def search_records(self, app_token: str, table_id: str, filter_expr: str) -> list[dict[str, Any]]:
        raise NotImplementedError("TODO: implement Feishu OpenAPI Bitable search_records over HTTPS")


class LegacyFeishuBitableClient(BitableClient):
    def __init__(self, feishu_client: Any) -> None:
        self.feishu_client = feishu_client

    def create_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> str:
        result = self.feishu_client.create_bitable_record(app_token, table_id, fields)
        return _record_id_from_result(result)

    def update_record(self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
        self.feishu_client.update_bitable_record(app_token, table_id, record_id, fields)

    def get_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        return self.feishu_client.get_bitable_record(app_token, table_id, record_id)

    def search_records(self, app_token: str, table_id: str, filter_expr: str) -> list[dict[str, Any]]:
        return []


def create_bitable_client(settings: Settings | None = None) -> BitableClient:
    settings = settings or get_settings()
    if settings.feishu_mock:
        return MockBitableClient()
    return LarkCliBitableClient(settings)


def _create_args(app_token: str, table_id: str, fields: dict[str, Any]) -> list[str]:
    return [
        "api",
        "POST",
        f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        "--data",
        json.dumps({"fields": fields}, ensure_ascii=False, default=str),
    ]


def _update_args(app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> list[str]:
    return [
        "api",
        "PUT",
        f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        "--data",
        json.dumps({"fields": fields}, ensure_ascii=False, default=str),
    ]


def _get_args(app_token: str, table_id: str, record_id: str) -> list[str]:
    return [
        "api",
        "GET",
        f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
    ]


def _search_args(app_token: str, table_id: str, filter_expr: str) -> list[str]:
    return [
        "api",
        "GET",
        f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        "--params",
        json.dumps({"filter": filter_expr}, ensure_ascii=False),
    ]


def _run_lark_cli(settings: Settings, args: list[str], write: bool) -> dict[str, Any]:
    command = [settings.lark_cli_path, *args, "--as", "bot"]
    if write and settings.lark_dry_run:
        command.append("--dry-run")
    logger.info("lark-cli bitable command=%s", _redact_args(command))
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"lark-cli bitable failed: {_redact_text(completed.stderr)}")
    try:
        parsed = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return {"stdout": _redact_text(completed.stdout)}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _record_id_from_result(result: dict[str, Any]) -> str:
    for path in (
        ("record_id",),
        ("data", "record", "record_id"),
        ("data", "record_id"),
        ("record", "record_id"),
    ):
        value: Any = result
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if value:
            return str(value)
    return "unknown_record_id"


def _record_from_result(result: dict[str, Any]) -> dict[str, Any]:
    for path in (("data", "record"), ("record",), ("data",)):
        value: Any = result
        for key in path:
            if not isinstance(value, dict) or key not in value:
                value = None
                break
            value = value[key]
        if isinstance(value, dict):
            return value
    return result


def _redact_args(args: list[str]) -> list[str]:
    return [_redact_text(arg) for arg in args]


def _redact_text(text: str) -> str:
    json_redacted = _redact_json_text(text)
    if json_redacted is not None:
        return json_redacted

    redacted = text
    for marker in SENSITIVE_MARKERS:
        redacted = re.sub(
            rf"({re.escape(marker)}[A-Za-z0-9_/-]*[/:=])[A-Za-z0-9._-]+",
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
    redacted = re.sub(r"/apps/[^/]+/tables/", "/apps/<redacted>/tables/", redacted)
    return redacted


def _redact_json_text(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return json.dumps(_redact_value(parsed), ensure_ascii=False, default=str)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(marker in key.lower() for marker in SENSITIVE_MARKERS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        redacted = value
        for marker in SENSITIVE_MARKERS:
            if marker in redacted.lower():
                return "<redacted>"
        return redacted
    return value
