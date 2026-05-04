from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./teamtask_agent.db"
    teamtask_confidence_threshold: float = 0.6
    feishu_mock: bool = True
    lark_dry_run: bool = True
    lark_cli_path: str = "lark-cli"
    todo_backend: str = "mock"
    feishu_bitable_app_token: str | None = None
    feishu_bitable_table_id: str | None = None
    feishu_bitable_view_id: str | None = None
    feishu_todo_owner_field: str = "负责人"
    feishu_todo_contract_id_field: str = "contract_id"
    feishu_todo_title_field: str = "任务标题"
    feishu_todo_description_field: str = "任务描述"
    feishu_todo_initiator_field: str = "发起者"
    feishu_todo_assignee_field: str = "执行者"
    feishu_todo_status_field: str = "状态"
    feishu_todo_deadline_field: str = "截止时间"
    feishu_todo_source_field: str = "来源"
    feishu_todo_evidence_field: str = "证据片段"
    feishu_todo_resource_field: str = "相关资源"
    feishu_todo_role_field: str = "个人角色"
    minutes_backend: str = "mock"
    minutes_dry_run: bool = True
    minutes_text_max_chars: int = 30000
    minutes_task_section_hints: tuple[str, ...] = ("已做完", "未做完", "待办", "行动项", "TODO", "下一步")
    minutes_link_patterns: tuple[str, ...] = ()
    resource_search_backend: str = "mock"
    resource_search_dry_run: bool = True
    resource_search_top_k: int = 5
    resource_search_high_confidence_threshold: float = 0.8
    resource_search_low_confidence_threshold: float = 0.5
    resource_search_enable_for_initiator: bool = True
    resource_search_enable_for_assignee: bool = True
    resource_search_max_query_terms: int = 8
    resource_search_sources: tuple[str, ...] = ("docs", "minutes", "base")


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./teamtask_agent.db"),
        teamtask_confidence_threshold=_env_float("TEAMTASK_CONFIDENCE_THRESHOLD", 0.6),
        feishu_mock=_env_bool("FEISHU_MOCK", True),
        lark_dry_run=_env_bool("LARK_DRY_RUN", True),
        lark_cli_path=os.getenv("LARK_CLI_PATH", "lark-cli"),
        todo_backend=os.getenv("TODO_BACKEND", "mock").strip().lower(),
        feishu_bitable_app_token=os.getenv("FEISHU_BITABLE_APP_TOKEN") or None,
        feishu_bitable_table_id=os.getenv("FEISHU_BITABLE_TABLE_ID") or None,
        feishu_bitable_view_id=os.getenv("FEISHU_BITABLE_VIEW_ID") or None,
        feishu_todo_owner_field=os.getenv("FEISHU_TODO_OWNER_FIELD", "负责人"),
        feishu_todo_contract_id_field=os.getenv("FEISHU_TODO_CONTRACT_ID_FIELD", "contract_id"),
        feishu_todo_title_field=os.getenv("FEISHU_TODO_TITLE_FIELD", "任务标题"),
        feishu_todo_description_field=os.getenv("FEISHU_TODO_DESCRIPTION_FIELD", "任务描述"),
        feishu_todo_initiator_field=os.getenv("FEISHU_TODO_INITIATOR_FIELD", "发起者"),
        feishu_todo_assignee_field=os.getenv("FEISHU_TODO_ASSIGNEE_FIELD", "执行者"),
        feishu_todo_status_field=os.getenv("FEISHU_TODO_STATUS_FIELD", "状态"),
        feishu_todo_deadline_field=os.getenv("FEISHU_TODO_DEADLINE_FIELD", "截止时间"),
        feishu_todo_source_field=os.getenv("FEISHU_TODO_SOURCE_FIELD", "来源"),
        feishu_todo_evidence_field=os.getenv("FEISHU_TODO_EVIDENCE_FIELD", "证据片段"),
        feishu_todo_resource_field=os.getenv("FEISHU_TODO_RESOURCE_FIELD", "相关资源"),
        feishu_todo_role_field=os.getenv("FEISHU_TODO_ROLE_FIELD", "个人角色"),
        minutes_backend=os.getenv("MINUTES_BACKEND", "mock").strip().lower(),
        minutes_dry_run=_env_bool("MINUTES_DRY_RUN", True),
        minutes_text_max_chars=_env_int("MINUTES_TEXT_MAX_CHARS", 30000),
        minutes_task_section_hints=_env_csv(
            "MINUTES_TASK_SECTION_HINTS",
            ("已做完", "未做完", "待办", "行动项", "TODO", "下一步"),
        ),
        minutes_link_patterns=_env_csv("MINUTES_LINK_PATTERNS", ()),
        resource_search_backend=os.getenv("RESOURCE_SEARCH_BACKEND", "mock").strip().lower(),
        resource_search_dry_run=_env_bool("RESOURCE_SEARCH_DRY_RUN", True),
        resource_search_top_k=_env_int("RESOURCE_SEARCH_TOP_K", 5),
        resource_search_high_confidence_threshold=_env_float("RESOURCE_SEARCH_HIGH_CONFIDENCE_THRESHOLD", 0.8),
        resource_search_low_confidence_threshold=_env_float("RESOURCE_SEARCH_LOW_CONFIDENCE_THRESHOLD", 0.5),
        resource_search_enable_for_initiator=_env_bool("RESOURCE_SEARCH_ENABLE_FOR_INITIATOR", True),
        resource_search_enable_for_assignee=_env_bool("RESOURCE_SEARCH_ENABLE_FOR_ASSIGNEE", True),
        resource_search_max_query_terms=_env_int("RESOURCE_SEARCH_MAX_QUERY_TERMS", 8),
        resource_search_sources=_env_csv("RESOURCE_SEARCH_SOURCES", ("docs", "minutes", "base")),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())
