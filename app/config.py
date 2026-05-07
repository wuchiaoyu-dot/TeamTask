from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


ENV_PROFILE_DEFAULTS: dict[str, dict[str, str]] = {
    "local_mock": {
        "FEISHU_MOCK": "true",
        "LARK_DRY_RUN": "true",
        "LARK_CLI_DRY_RUN": "true",
        "FEISHU_SEND_DRY_RUN": "true",
        "BITABLE_DRY_RUN": "true",
        "TODO_PROJECTION_DRY_RUN": "true",
        "FEISHU_ENABLE_REAL_READ": "false",
        "RESOURCE_SEARCH_REAL_READ": "false",
        "TODO_BACKEND": "mock",
        "MINUTES_BACKEND": "mock",
        "RESOURCE_SEARCH_BACKEND": "mock",
        "RESOURCE_SEARCH_DRY_RUN": "true",
        "TASK_EXTRACTOR_BACKEND": "rule",
    },
    "staging_dry_run": {
        "FEISHU_MOCK": "false",
        "LARK_DRY_RUN": "true",
        "LARK_CLI_DRY_RUN": "false",
        "FEISHU_SEND_DRY_RUN": "false",
        "BITABLE_DRY_RUN": "true",
        "TODO_PROJECTION_DRY_RUN": "true",
        "FEISHU_ENABLE_REAL_READ": "false",
        "RESOURCE_SEARCH_REAL_READ": "false",
        "TODO_BACKEND": "bitable",
        "MINUTES_BACKEND": "lark_cli",
        "RESOURCE_SEARCH_BACKEND": "lark_cli",
        "RESOURCE_SEARCH_DRY_RUN": "true",
        "TASK_EXTRACTOR_BACKEND": "rule",
    },
    "production_trial": {
        "FEISHU_MOCK": "false",
        "LARK_DRY_RUN": "false",
        "LARK_CLI_DRY_RUN": "false",
        "FEISHU_SEND_DRY_RUN": "false",
        "BITABLE_DRY_RUN": "false",
        "TODO_PROJECTION_DRY_RUN": "false",
        "FEISHU_ENABLE_REAL_READ": "true",
        "RESOURCE_SEARCH_REAL_READ": "true",
        "TODO_BACKEND": "bitable",
        "MINUTES_BACKEND": "lark_cli",
        "RESOURCE_SEARCH_BACKEND": "lark_cli",
        "RESOURCE_SEARCH_DRY_RUN": "false",
        "TASK_EXTRACTOR_BACKEND": "rule",
    },
}


@dataclass(frozen=True)
class Settings:
    env_profile: str = "local_mock"
    database_url: str = "sqlite:///./teamtask_agent.db"
    teamtask_confidence_threshold: float = 0.6
    task_extractor_backend: str = "rule"
    task_extractor_llm_fallback: bool = True
    llm_task_api_base: str = "https://api.openai.com/v1"
    llm_task_api_key: str | None = None
    llm_task_model: str | None = None
    llm_task_prompt_path: str = "prompts/extract_tasks.md"
    llm_task_response_format: str = "json_object"
    llm_task_timeout_seconds: int = 30
    llm_task_max_input_chars: int = 20000
    llm_task_temperature: float = 0.0
    feishu_mock: bool = True
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    lark_dry_run: bool = True
    lark_cli_dry_run: bool = True
    feishu_send_dry_run: bool = True
    lark_cli_path: str = "lark-cli"
    todo_backend: str = "mock"
    bitable_dry_run: bool | None = None
    todo_projection_dry_run: bool | None = None
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
    feishu_enable_real_read: bool = False
    feishu_read_as_user: bool = True
    feishu_read_timeout_seconds: int = 20
    feishu_doc_search_top_k: int = 5
    feishu_minutes_scope_required: tuple[str, ...] = ("minutes:read",)
    feishu_docs_scope_required: tuple[str, ...] = ("docs:read",)
    feishu_drive_scope_required: tuple[str, ...] = ("drive:read",)
    feishu_base_scope_required: tuple[str, ...] = ("base:read",)
    allowed_user_ids: tuple[str, ...] = ()
    allowed_chat_ids: tuple[str, ...] = ()
    enable_real_write_for_allowed_users_only: bool = True
    enable_real_read_for_allowed_users_only: bool = True
    resource_search_backend: str = "mock"
    resource_search_dry_run: bool = True
    resource_search_real_read: bool = False
    resource_search_top_k: int = 5
    resource_search_high_confidence_threshold: float = 0.8
    resource_search_low_confidence_threshold: float = 0.5
    resource_search_enable_for_initiator: bool = True
    resource_search_enable_for_assignee: bool = True
    resource_search_max_query_terms: int = 8
    resource_search_sources: tuple[str, ...] = ("docs", "minutes", "base")


def get_settings() -> Settings:
    env_profile = os.getenv("ENV_PROFILE", "local_mock").strip().lower()
    lark_cli_dry_run = _send_dry_run(env_profile)
    resource_search_real_read = _resource_search_real_read(env_profile)
    return Settings(
        env_profile=env_profile,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./teamtask_agent.db"),
        teamtask_confidence_threshold=_env_float("TEAMTASK_CONFIDENCE_THRESHOLD", 0.6),
        task_extractor_backend=os.getenv(
            "TASK_EXTRACTOR_BACKEND",
            _profile_value(env_profile, "TASK_EXTRACTOR_BACKEND", "rule"),
        ).strip().lower(),
        task_extractor_llm_fallback=_env_bool("TASK_EXTRACTOR_LLM_FALLBACK", True),
        llm_task_api_base=os.getenv("LLM_TASK_API_BASE", "https://api.openai.com/v1").rstrip("/"),
        llm_task_api_key=os.getenv("LLM_TASK_API_KEY") or None,
        llm_task_model=os.getenv("LLM_TASK_MODEL") or None,
        llm_task_prompt_path=os.getenv("LLM_TASK_PROMPT_PATH", "prompts/extract_tasks.md"),
        llm_task_response_format=os.getenv("LLM_TASK_RESPONSE_FORMAT", "json_object").strip().lower(),
        llm_task_timeout_seconds=_env_int("LLM_TASK_TIMEOUT_SECONDS", 30),
        llm_task_max_input_chars=_env_int("LLM_TASK_MAX_INPUT_CHARS", 20000),
        llm_task_temperature=_env_float("LLM_TASK_TEMPERATURE", 0.0),
        feishu_mock=_env_bool("FEISHU_MOCK", _profile_bool(env_profile, "FEISHU_MOCK", True)),
        feishu_app_id=os.getenv("FEISHU_APP_ID") or None,
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET") or None,
        lark_dry_run=_env_bool("LARK_DRY_RUN", _profile_bool(env_profile, "LARK_DRY_RUN", True)),
        lark_cli_dry_run=lark_cli_dry_run,
        feishu_send_dry_run=lark_cli_dry_run,
        lark_cli_path=os.getenv("LARK_CLI_PATH", "lark-cli"),
        todo_backend=os.getenv("TODO_BACKEND", _profile_value(env_profile, "TODO_BACKEND", "mock")).strip().lower(),
        bitable_dry_run=_bitable_dry_run(env_profile),
        todo_projection_dry_run=_todo_projection_dry_run(env_profile),
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
        minutes_backend=os.getenv("MINUTES_BACKEND", _profile_value(env_profile, "MINUTES_BACKEND", "mock")).strip().lower(),
        minutes_dry_run=_env_bool("MINUTES_DRY_RUN", True),
        minutes_text_max_chars=_env_int("MINUTES_TEXT_MAX_CHARS", 30000),
        minutes_task_section_hints=_env_csv(
            "MINUTES_TASK_SECTION_HINTS",
            ("已做完", "未做完", "待办", "行动项", "TODO", "下一步"),
        ),
        minutes_link_patterns=_env_csv("MINUTES_LINK_PATTERNS", ()),
        feishu_enable_real_read=_env_bool(
            "FEISHU_ENABLE_REAL_READ",
            _profile_bool(env_profile, "FEISHU_ENABLE_REAL_READ", False),
        ),
        feishu_read_as_user=_env_bool("FEISHU_READ_AS_USER", True),
        feishu_read_timeout_seconds=_env_int("FEISHU_READ_TIMEOUT_SECONDS", 20),
        feishu_doc_search_top_k=_env_int("FEISHU_DOC_SEARCH_TOP_K", 5),
        feishu_minutes_scope_required=_env_csv("FEISHU_MINUTES_SCOPE_REQUIRED", ("minutes:read",)),
        feishu_docs_scope_required=_env_csv("FEISHU_DOCS_SCOPE_REQUIRED", ("docs:read",)),
        feishu_drive_scope_required=_env_csv("FEISHU_DRIVE_SCOPE_REQUIRED", ("drive:read",)),
        feishu_base_scope_required=_env_csv("FEISHU_BASE_SCOPE_REQUIRED", ("base:read",)),
        allowed_user_ids=_env_csv("ALLOWED_USER_IDS", ()),
        allowed_chat_ids=_env_csv("ALLOWED_CHAT_IDS", ()),
        enable_real_write_for_allowed_users_only=_env_bool("ENABLE_REAL_WRITE_FOR_ALLOWED_USERS_ONLY", True),
        enable_real_read_for_allowed_users_only=_env_bool("ENABLE_REAL_READ_FOR_ALLOWED_USERS_ONLY", True),
        resource_search_backend=os.getenv(
            "RESOURCE_SEARCH_BACKEND",
            _profile_value(env_profile, "RESOURCE_SEARCH_BACKEND", "mock"),
        ).strip().lower(),
        resource_search_dry_run=_resource_search_dry_run(env_profile, resource_search_real_read),
        resource_search_real_read=resource_search_real_read,
        resource_search_top_k=_env_int("RESOURCE_SEARCH_TOP_K", 5),
        resource_search_high_confidence_threshold=_env_float("RESOURCE_SEARCH_HIGH_CONFIDENCE_THRESHOLD", 0.8),
        resource_search_low_confidence_threshold=_env_float("RESOURCE_SEARCH_LOW_CONFIDENCE_THRESHOLD", 0.5),
        resource_search_enable_for_initiator=_env_bool("RESOURCE_SEARCH_ENABLE_FOR_INITIATOR", True),
        resource_search_enable_for_assignee=_env_bool("RESOURCE_SEARCH_ENABLE_FOR_ASSIGNEE", True),
        resource_search_max_query_terms=_env_int("RESOURCE_SEARCH_MAX_QUERY_TERMS", 8),
        resource_search_sources=_env_csv("RESOURCE_SEARCH_SOURCES", ("docs", "minutes", "base")),
    )


def validate_env_profile(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.env_profile not in ENV_PROFILE_DEFAULTS:
        raise ValueError(
            "Unknown ENV_PROFILE. Expected one of: " + ", ".join(sorted(ENV_PROFILE_DEFAULTS.keys()))
        )
    if settings.task_extractor_backend not in {"rule", "llm", "auto"}:
        raise ValueError("TASK_EXTRACTOR_BACKEND must be one of: rule, llm, auto")
    if settings.env_profile != "production_trial":
        return

    problems: list[str] = []
    if settings.feishu_mock:
        problems.append("FEISHU_MOCK must be false")
    if settings.lark_dry_run:
        problems.append("LARK_DRY_RUN must be false")
    if settings.feishu_send_dry_run:
        problems.append("LARK_CLI_DRY_RUN or FEISHU_SEND_DRY_RUN must be false")
    if is_todo_projection_dry_run_enabled(settings):
        problems.append("BITABLE_DRY_RUN and TODO_PROJECTION_DRY_RUN must be false")
    if not settings.feishu_enable_real_read:
        problems.append("FEISHU_ENABLE_REAL_READ must be true")
    if settings.todo_backend != "bitable":
        problems.append("TODO_BACKEND must be bitable")
    if not settings.allowed_user_ids:
        problems.append("ALLOWED_USER_IDS must be configured")
    if problems:
        raise ValueError("Invalid production_trial profile: " + "; ".join(problems))


def validate_bitable_config(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.todo_backend != "bitable" or settings.feishu_mock:
        return

    missing: list[str] = []
    if not settings.feishu_bitable_app_token:
        missing.append("FEISHU_BITABLE_APP_TOKEN")
    if not settings.feishu_bitable_table_id:
        missing.append("FEISHU_BITABLE_TABLE_ID")
    if not (settings.feishu_app_id or settings.lark_cli_path):
        missing.append("FEISHU_APP_ID or LARK_CLI_PATH")
    if not (settings.feishu_app_secret or settings.lark_cli_path):
        missing.append("FEISHU_APP_SECRET or lark-cli login")
    if missing:
        raise ValueError("Bitable backend configuration missing: " + ", ".join(missing))


def validate_real_read_config(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.feishu_mock or not settings.feishu_enable_real_read:
        return

    missing: list[str] = []
    if not (settings.lark_cli_path or (settings.feishu_app_id and settings.feishu_app_secret)):
        missing.append("LARK_CLI_PATH or Feishu OpenAPI app credentials")
    if not settings.feishu_minutes_scope_required:
        missing.append("FEISHU_MINUTES_SCOPE_REQUIRED")
    if not settings.feishu_docs_scope_required:
        missing.append("FEISHU_DOCS_SCOPE_REQUIRED")
    if not settings.feishu_drive_scope_required:
        missing.append("FEISHU_DRIVE_SCOPE_REQUIRED")
    if not settings.feishu_base_scope_required:
        missing.append("FEISHU_BASE_SCOPE_REQUIRED")
    if os.getenv("TEAMTASK_SKIP_DB_INIT") == "1":
        missing.append("non-test runtime")
    if missing:
        raise ValueError("Real Feishu read configuration missing or blocked: " + ", ".join(missing))


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _send_dry_run(profile: str) -> bool:
    if os.getenv("LARK_CLI_DRY_RUN") is not None:
        return _env_bool("LARK_CLI_DRY_RUN", True)
    if os.getenv("FEISHU_SEND_DRY_RUN") is not None:
        return _env_bool("FEISHU_SEND_DRY_RUN", True)
    if os.getenv("LARK_CARD_DRY_RUN") is not None:
        return _env_bool("LARK_CARD_DRY_RUN", True)
    return _profile_bool(profile, "LARK_CLI_DRY_RUN", _profile_bool(profile, "FEISHU_SEND_DRY_RUN", True))


def _bitable_dry_run(profile: str) -> bool:
    if os.getenv("BITABLE_DRY_RUN") is not None:
        return _env_bool("BITABLE_DRY_RUN", True)
    if os.getenv("LARK_DRY_RUN") is not None:
        return _env_bool("LARK_DRY_RUN", True)
    return _profile_bool(profile, "BITABLE_DRY_RUN", True)


def _todo_projection_dry_run(profile: str) -> bool:
    if os.getenv("TODO_PROJECTION_DRY_RUN") is not None:
        return _env_bool("TODO_PROJECTION_DRY_RUN", True)
    if os.getenv("BITABLE_DRY_RUN") is not None:
        return _env_bool("BITABLE_DRY_RUN", True)
    if os.getenv("LARK_DRY_RUN") is not None:
        return _env_bool("LARK_DRY_RUN", True)
    return _profile_bool(profile, "TODO_PROJECTION_DRY_RUN", True)


def _resource_search_real_read(profile: str) -> bool:
    if os.getenv("RESOURCE_SEARCH_REAL_READ") is not None:
        return _env_bool("RESOURCE_SEARCH_REAL_READ", False)
    return _profile_bool(profile, "RESOURCE_SEARCH_REAL_READ", False)


def _resource_search_dry_run(profile: str, resource_search_real_read: bool) -> bool:
    if os.getenv("RESOURCE_SEARCH_DRY_RUN") is not None:
        return _env_bool("RESOURCE_SEARCH_DRY_RUN", True)
    if os.getenv("RESOURCE_SEARCH_REAL_READ") is not None:
        return not resource_search_real_read
    return _profile_bool(profile, "RESOURCE_SEARCH_DRY_RUN", True)


def is_bitable_dry_run_enabled(settings: Settings) -> bool:
    if settings.bitable_dry_run is None:
        return settings.lark_dry_run
    return settings.bitable_dry_run


def is_todo_projection_dry_run_enabled(settings: Settings) -> bool:
    if settings.todo_projection_dry_run is None:
        todo_dry_run = settings.lark_dry_run
    else:
        todo_dry_run = settings.todo_projection_dry_run
    return todo_dry_run or is_bitable_dry_run_enabled(settings)


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


def _profile_value(profile: str, name: str, default: str) -> str:
    return ENV_PROFILE_DEFAULTS.get(profile, {}).get(name, default)


def _profile_bool(profile: str, name: str, default: bool) -> bool:
    return _profile_value(profile, name, "true" if default else "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
