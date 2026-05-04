from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.clients.feishu_client import FeishuClient
from app.config import Settings, get_settings
from app.models import TaskContract
from app.services.todo_field_mapper import map_contract_to_bitable_fields

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


class BitableTodoBackend(TodoBackend):
    provider = "bitable"

    def __init__(self, feishu_client: FeishuClient, settings: Settings | None = None) -> None:
        self.feishu_client = feishu_client
        self.settings = settings or get_settings()

    def create_personal_todo_projection(self, owner_user_id: str, contract: TaskContract, role: str) -> str:
        fields = map_contract_to_bitable_fields(owner_user_id, contract, role, self.settings)
        logger.info(
            "BitableTodoBackend create owner_user_id=%s contract_id=%s dry_run=%s fields=%s",
            owner_user_id,
            contract.id,
            self.settings.lark_dry_run,
            fields,
        )
        if self.settings.lark_dry_run:
            return f"dry_run_record_{owner_user_id}_{contract.id}_{role}"

        result = self.feishu_client.create_bitable_record(
            self._app_token(),
            self._table_id(),
            fields,
        )
        return _record_id_from_result(result)

    def update_personal_todo_projection(
        self,
        owner_user_id: str,
        external_record_id: str,
        patch: dict[str, Any],
    ) -> None:
        logger.info(
            "BitableTodoBackend update owner_user_id=%s external_record_id=%s dry_run=%s patch=%s",
            owner_user_id,
            external_record_id,
            self.settings.lark_dry_run,
            patch,
        )
        if self.settings.lark_dry_run:
            return

        self.feishu_client.update_bitable_record(
            self._app_token(),
            self._table_id(),
            external_record_id,
            patch,
        )

    def find_existing_projection(self, owner_user_id: str, contract_id: int) -> str | None:
        if self.settings.lark_dry_run:
            return None
        logger.info(
            "BitableTodoBackend find_existing_projection owner_user_id=%s contract_id=%s",
            owner_user_id,
            contract_id,
        )
        return None

    def get_personal_todo(self, owner_user_id: str, external_record_id: str) -> dict[str, Any]:
        if self.settings.lark_dry_run:
            return {
                "dry_run": True,
                "owner_user_id": owner_user_id,
                "record_id": external_record_id,
            }
        return self.feishu_client.get_bitable_record(self._app_token(), self._table_id(), external_record_id)

    def _app_token(self) -> str:
        if not self.settings.feishu_bitable_app_token:
            raise ValueError("FEISHU_BITABLE_APP_TOKEN is required for bitable todo backend")
        return self.settings.feishu_bitable_app_token

    def _table_id(self) -> str:
        if not self.settings.feishu_bitable_table_id:
            raise ValueError("FEISHU_BITABLE_TABLE_ID is required for bitable todo backend")
        return self.settings.feishu_bitable_table_id


def create_todo_backend(feishu_client: FeishuClient, settings: Settings | None = None) -> TodoBackend:
    settings = settings or get_settings()
    if settings.feishu_mock or settings.todo_backend != "bitable":
        return MockTodoBackend()
    return BitableTodoBackend(feishu_client, settings)


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
