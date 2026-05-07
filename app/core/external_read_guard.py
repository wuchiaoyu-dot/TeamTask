from __future__ import annotations

import os
import re

from app.config import Settings, get_settings, validate_real_read_config


def should_allow_external_read(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if settings.feishu_mock:
        return False
    if not settings.feishu_enable_real_read:
        return False
    if os.getenv("TEAMTASK_SKIP_DB_INIT") == "1":
        return False
    try:
        validate_real_read_config(settings)
    except ValueError:
        return False
    return True


def assert_external_read_allowed(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    validate_real_read_config(settings)
    if not should_allow_external_read(settings):
        raise PermissionError(
            "External Feishu reads are disabled. Require FEISHU_MOCK=false, "
            "FEISHU_ENABLE_REAL_READ=true, valid read config, and non-test runtime."
        )


def mask_sensitive_resource_id(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 8:
        return "<redacted>"
    masked = f"{text[:4]}...{text[-4:]}"
    return re.sub(r"(token|secret|authorization)[^/\\\s]*", r"\1:<redacted>", masked, flags=re.IGNORECASE)
