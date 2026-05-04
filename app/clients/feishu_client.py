from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from app.models import TaskContract

logger = logging.getLogger(__name__)


class FeishuClient(ABC):
    @abstractmethod
    def send_message(self, user_id: str, text: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def send_card(self, user_id: str, card_json: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def send_group_message(self, chat_id: str, text: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_minutes_transcript(self, minutes_token: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def search_docs(self, user_id: str, query: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def create_todo_projection(self, user_id: str, task_contract: TaskContract) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_todo_projection(
        self,
        user_id: str,
        contract_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def create_bitable_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class MockFeishuClient(FeishuClient):
    sent_messages: list[dict[str, Any]] = field(default_factory=list)
    sent_cards: list[dict[str, Any]] = field(default_factory=list)
    sent_group_messages: list[dict[str, Any]] = field(default_factory=list)
    todo_operations: list[dict[str, Any]] = field(default_factory=list)

    def send_message(self, user_id: str, text: str) -> dict[str, Any]:
        delivery = {
            "delivery_id": f"mock-message-{uuid4()}",
            "recipient_user_id": user_id,
            "text": text,
        }
        self.sent_messages.append(delivery)
        logger.info("FEISHU_MOCK send_message user_id=%s text=%s", user_id, text)
        return delivery

    def send_card(self, user_id: str, card_json: dict[str, Any]) -> dict[str, Any]:
        delivery = {
            "delivery_id": f"mock-card-{uuid4()}",
            "recipient_user_id": user_id,
            "card": card_json,
        }
        self.sent_cards.append(delivery)
        logger.info(
            "FEISHU_MOCK send_card user_id=%s card_json=%s",
            user_id,
            json.dumps(card_json, ensure_ascii=False, default=str),
        )
        return delivery

    def send_group_message(self, chat_id: str, text: str) -> dict[str, Any]:
        delivery = {
            "delivery_id": f"mock-group-message-{uuid4()}",
            "chat_id": chat_id,
            "text": text,
        }
        self.sent_group_messages.append(delivery)
        logger.info("FEISHU_MOCK send_group_message chat_id=%s text=%s", chat_id, text)
        return delivery

    def get_minutes_transcript(self, minutes_token: str) -> dict[str, Any]:
        logger.info("FEISHU_MOCK get_minutes_transcript minutes_token=<redacted>")
        return {
            "minutes_token": "<redacted>",
            "transcript": "Mock transcript. Replace MockFeishuClient with LarkCliClient for real data.",
        }

    def search_docs(self, user_id: str, query: str) -> list[dict[str, Any]]:
        logger.info("FEISHU_MOCK search_docs user_id=%s query=%s", user_id, query)
        return [
            {
                "title": f"Mock doc for {query}",
                "url": f"https://mock.feishu.local/docs/search?q={query}",
            }
        ]

    def create_todo_projection(self, user_id: str, task_contract: TaskContract) -> dict[str, Any]:
        operation = {
            "operation_id": f"mock-todo-create-{uuid4()}",
            "user_id": user_id,
            "contract_id": task_contract.id,
            "title": task_contract.title,
        }
        self.todo_operations.append(operation)
        logger.info("FEISHU_MOCK create_todo_projection user_id=%s contract_id=%s", user_id, task_contract.id)
        return operation

    def update_todo_projection(
        self,
        user_id: str,
        contract_id: int,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        operation = {
            "operation_id": f"mock-todo-update-{uuid4()}",
            "user_id": user_id,
            "contract_id": contract_id,
            "patch": patch,
        }
        self.todo_operations.append(operation)
        logger.info(
            "FEISHU_MOCK update_todo_projection user_id=%s contract_id=%s patch=%s",
            user_id,
            contract_id,
            json.dumps(patch, ensure_ascii=False, default=str),
        )
        return operation

    def create_bitable_record(self, app_token: str, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        operation = {
            "record_id": f"mock_record_{uuid4()}",
            "app_token": "<mock>",
            "table_id": table_id,
            "fields": fields,
        }
        self.todo_operations.append({"operation": "create_bitable_record", **operation})
        logger.info(
            "FEISHU_MOCK create_bitable_record table_id=%s fields=%s",
            table_id,
            json.dumps(fields, ensure_ascii=False, default=str),
        )
        return operation

    def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        operation = {
            "record_id": record_id,
            "app_token": "<mock>",
            "table_id": table_id,
            "fields": fields,
        }
        self.todo_operations.append({"operation": "update_bitable_record", **operation})
        logger.info(
            "FEISHU_MOCK update_bitable_record table_id=%s record_id=%s fields=%s",
            table_id,
            record_id,
            json.dumps(fields, ensure_ascii=False, default=str),
        )
        return operation

    def get_bitable_record(self, app_token: str, table_id: str, record_id: str) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "app_token": "<mock>",
            "table_id": table_id,
            "fields": {},
        }


def create_feishu_client() -> FeishuClient:
    if _env_bool("FEISHU_MOCK", default=True):
        return MockFeishuClient()

    from app.clients.lark_cli_client import LarkCliClient

    return LarkCliClient(
        cli_path=os.getenv("LARK_CLI_PATH", "lark-cli"),
        dry_run=_env_bool("LARK_DRY_RUN", default=True),
        actor_mode=os.getenv("LARK_ACTOR_MODE", "as_bot"),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
