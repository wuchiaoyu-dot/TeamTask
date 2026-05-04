from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException, status


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def decrypt_event_payload(payload: dict[str, Any], encrypt_key: str | None) -> dict[str, Any]:
    # TODO: implement Feishu/Lark AES-CBC decrypt for encrypted event payloads.
    # V1 dry-run integration supports unencrypted callbacks first, while keeping this
    # boundary explicit so production hardening can fill in real decryption.
    if "encrypt" not in payload:
        return payload
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Encrypted Feishu event payloads are not supported in V1 dry-run mode",
    )


def decrypt_card_payload(payload: dict[str, Any], encrypt_key: str | None) -> dict[str, Any]:
    # TODO: implement Feishu/Lark AES-CBC decrypt for encrypted card callbacks.
    if "encrypt" not in payload:
        return payload
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Encrypted Feishu card callbacks are not supported in V1 dry-run mode",
    )


def validate_event_token(payload: dict[str, Any]) -> None:
    expected = os.getenv("FEISHU_VERIFICATION_TOKEN")
    if not expected:
        return
    actual = _extract_token(payload)
    if actual != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Feishu event verification token")


def validate_card_token(payload: dict[str, Any]) -> None:
    expected = os.getenv("FEISHU_CARD_VERIFICATION_TOKEN") or os.getenv("FEISHU_VERIFICATION_TOKEN")
    if not expected:
        return
    actual = _extract_token(payload)
    if actual != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Feishu card verification token")


def is_url_verification(payload: dict[str, Any]) -> bool:
    header = payload.get("header") or {}
    return (
        payload.get("type") == "url_verification"
        or header.get("event_type") == "url_verification"
        or ("challenge" in payload and ("token" in payload or "header" in payload))
    )


def challenge_response(payload: dict[str, Any]) -> dict[str, str]:
    challenge = payload.get("challenge")
    if not challenge:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing challenge")
    return {"challenge": str(challenge)}


def _extract_token(payload: dict[str, Any]) -> str | None:
    header = payload.get("header") or {}
    event = payload.get("event") or {}
    return payload.get("token") or header.get("token") or event.get("token")
