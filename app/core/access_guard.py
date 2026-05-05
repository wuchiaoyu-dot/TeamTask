from __future__ import annotations

from fastapi import HTTPException, status

from app.config import Settings, get_settings


def is_allowed_user(user_id: str | None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not user_id:
        return False
    if not settings.allowed_user_ids:
        return settings.env_profile != "production_trial"
    return user_id in set(settings.allowed_user_ids)


def is_allowed_chat(chat_id: str | None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not chat_id:
        return True
    if not settings.allowed_chat_ids:
        return settings.env_profile != "production_trial"
    return chat_id in set(settings.allowed_chat_ids)


def assert_user_allowed(user_id: str | None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not is_allowed_user(user_id, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not allowed for this TeamTask environment",
        )


def assert_chat_allowed(chat_id: str | None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not is_allowed_chat(chat_id, settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat is not allowed for this TeamTask environment",
        )


def should_enforce_event_access(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.env_profile == "production_trial" or (
        not settings.feishu_mock and not settings.lark_dry_run and bool(settings.allowed_user_ids)
    )


def should_enforce_real_read_access(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.enable_real_read_for_allowed_users_only and (
        settings.env_profile == "production_trial"
        or (bool(settings.allowed_user_ids) and not settings.feishu_mock and not settings.lark_dry_run)
    )


def should_enforce_real_write_access(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return settings.enable_real_write_for_allowed_users_only and (
        settings.env_profile == "production_trial"
        or (
            bool(settings.allowed_user_ids)
            and not settings.feishu_mock
            and not settings.lark_dry_run
            and settings.todo_backend == "bitable"
        )
    )
