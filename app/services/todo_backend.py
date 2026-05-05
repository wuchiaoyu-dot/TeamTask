from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.clients.bitable_client import BitableClient, LegacyFeishuBitableClient, create_bitable_client
from app.config import Settings, get_settings, validate_bitable_config
from app.core.external_write_guard import should_allow_external_write
from app.models import TaskContract
from app.services.todo_field_mapper import (
    map_bitable_record_to_snapshot,
    map_contract_to_bitable_fields,
    map_patch_to_bitable_fields,
)

logger = logging.getLogger(__name__)


class TodoBackend(ABC):
    provider: str

    @abstractmethod
    def create_personal_todo_projection(self, owner_user_id: str, contract: TaskContract, role: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def update_personal_todo_projection(
        self,
        owner_user_id: str,
        external_record_id: str,
        patch: dict[str, Any],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def find_existing_projection(self, owner_user_id: str, contract_id: int) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def get_personal_todo(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_projection_snapshot(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        raise NotImplementedError


class MockTodoBackend(TodoBackend):
    provider = "mock"

    def __init__(self) -> None:
        self.records: dict[tuple[str, int], dict[str, Any]] = {}

    def create_personal_todo_projection(self, owner_user_id: str, contract: TaskContract, role: str) -> str:
        record_id = f"mock_record_{owner_user_id}_{contract.id}_{role}"
        self.records[(owner_user_id, contract.id)] = {
            "record_id": record_id,
            "owner_user_id": owner_user_id,
            "contract_id": contract.id,
            "role": role,
        }
        logger.info("MockTodoBackend create owner_user_id=%s contract_id=%s role=%s", owner_user_id, contract.id, role)
        return record_id

    def update_personal_todo_projection(
        self,
        owner_user_id: str,
        external_record_id: str,
        patch: dict[str, Any],
    ) -> None:
        logger.info(
            "MockTodoBackend update owner_user_id=%s external_record_id=%s patch=%s",
            owner_user_id,
            external_record_id,
            patch,
        )

    def find_existing_projection(self, owner_user_id: str, contract_id: int) -> str | None:
        record = self.records.get((owner_user_id, contract_id))
        return str(record["record_id"]) if record else None

    def get_personal_todo(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        for record in self.records.values():
            if record["owner_user_id"] == owner_user_id and record["record_id"] == external_record_id:
                return record
        return {"record_id": external_record_id, "owner_user_id": owner_user_id}

    def get_projection_snapshot(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        return self.get_personal_todo(owner_user_id, external_record_id)


class BitableTodoBackend(TodoBackend):
    provider = "bitable"

    def __init__(self, bitable_client: BitableClient | object | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bitable_client = _coerce_bitable_client(bitable_client, self.settings)

    def create_personal_todo_projection(self, owner_user_id: str, contract: TaskContract, role: str) -> str:
        if not self.settings.lark_dry_run:
            validate_bitable_config(self.settings)
        fields = map_contract_to_bitable_fields(owner_user_id, contract, role, self.settings)
        logger.info(
            "BitableTodoBackend create owner_user_id=%s contract_id=%s dry_run=%s fields=%s",
            owner_user_id,
            contract.id,
            self.settings.lark_dry_run,
            fields,
        )
        if not should_allow_external_write(self.settings):
            return f"dry_run_record_{owner_user_id}_{contract.id}_{role}"
        return self.bitable_client.create_record(self._app_token(), self._table_id(), fields)

    def update_personal_todo_projection(
        self,
        owner_user_id: str,
        external_record_id: str,
        patch: dict[str, Any],
    ) -> None:
        if not self.settings.lark_dry_run:
            validate_bitable_config(self.settings)
        fields = map_patch_to_bitable_fields(patch, self.settings)
        logger.info(
            "BitableTodoBackend update owner_user_id=%s external_record_id=%s dry_run=%s patch=%s",
            owner_user_id,
            external_record_id,
            self.settings.lark_dry_run,
            fields,
        )
        if not should_allow_external_write(self.settings):
            return
        self.bitable_client.update_record(self._app_token(), self._table_id(), external_record_id, fields)

    def find_existing_projection(self, owner_user_id: str, contract_id: int) -> str | None:
        if not self.settings.lark_dry_run:
            validate_bitable_config(self.settings)
        if not should_allow_external_write(self.settings):
            return None
        logger.info(
            "BitableTodoBackend find_existing_projection owner_user_id=%s contract_id=%s",
            owner_user_id,
            contract_id,
        )
        filter_expr = f'{self.settings.feishu_todo_contract_id_field}="{contract_id}"'
        records = self.bitable_client.search_records(self._app_token(), self._table_id(), filter_expr)
        for record in records:
            fields = record.get("fields", {})
            if str(fields.get(self.settings.feishu_todo_owner_field)) == owner_user_id:
                record_id = record.get("record_id") or record.get("id")
                return str(record_id) if record_id else None
        return None

    def get_personal_todo(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        if self.settings.lark_dry_run:
            return {
                "dry_run": True,
                "owner_user_id": owner_user_id,
                "record_id": external_record_id,
            }
        validate_bitable_config(self.settings)
        return self.bitable_client.get_record(self._app_token(), self._table_id(), external_record_id)

    def get_projection_snapshot(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        logger.info(
            "BitableTodoBackend get_projection_snapshot owner_user_id=%s external_record_id=%s dry_run=%s",
            owner_user_id,
            external_record_id,
            self.settings.lark_dry_run,
        )
        if self.settings.lark_dry_run:
            return {
                "dry_run": True,
                "owner_user_id": owner_user_id,
                "record_id": external_record_id,
            }
        record = self.get_personal_todo(owner_user_id, external_record_id)
        return map_bitable_record_to_snapshot(record, self.settings)

    def _app_token(self) -> str:
        if not self.settings.feishu_bitable_app_token:
            raise ValueError("FEISHU_BITABLE_APP_TOKEN is required for bitable todo backend")
        return self.settings.feishu_bitable_app_token

    def _table_id(self) -> str:
        if not self.settings.feishu_bitable_table_id:
            raise ValueError("FEISHU_BITABLE_TABLE_ID is required for bitable todo backend")
        return self.settings.feishu_bitable_table_id


def create_todo_backend(feishu_client: object, settings: Settings | None = None) -> TodoBackend:
    settings = settings or get_settings()
    if settings.feishu_mock or settings.todo_backend != "bitable":
        return MockTodoBackend()
    return BitableTodoBackend(create_bitable_client(settings), settings)


def _record_id_from_result(result: dict[str, Any]) -> str:
    for path in (
        ("record_id",),
        ("data", "record", "record_id"),
        ("data", "record_id"),
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


def _coerce_bitable_client(client: object | None, settings: Settings) -> BitableClient:
    if client is None:
        return create_bitable_client(settings)
    if isinstance(client, BitableClient):
        return client
    if all(hasattr(client, name) for name in ("create_bitable_record", "update_bitable_record", "get_bitable_record")):
        return LegacyFeishuBitableClient(client)
    raise TypeError("BitableTodoBackend requires a BitableClient-compatible client")
