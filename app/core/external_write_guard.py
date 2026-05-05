from __future__ import annotations

import os

from app.config import Settings, get_settings, validate_bitable_config


def should_allow_external_write(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if os.getenv("TEAMTASK_SKIP_DB_INIT") == "1":
        return False
    if settings.feishu_mock:
        return False
    if settings.lark_dry_run:
        return False
    if settings.todo_backend != "bitable":
        return False
    try:
        validate_bitable_config(settings)
    except ValueError:
        return False
    return True


def assert_external_write_allowed(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    validate_bitable_config(settings)
    if not should_allow_external_write(settings):
        raise PermissionError(
            "External Bitable writes are disabled. Require FEISHU_MOCK=false, "
            "LARK_DRY_RUN=false, TODO_BACKEND=bitable, valid Bitable config, and non-test runtime."
        )
