from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any

from fastapi import HTTPException

from app.db import SessionLocal, init_db

logger = logging.getLogger(__name__)


def sdk_data_to_dict(data: Any, lark_module: Any | None = None) -> dict[str, Any]:
    if isinstance(data, dict):
        return copy.deepcopy(data)

    lark = lark_module or _load_lark_oapi()
    marshaled = lark.JSON.marshal(data)
    if isinstance(marshaled, dict):
        return copy.deepcopy(marshaled)
    if isinstance(marshaled, bytes):
        marshaled = marshaled.decode("utf-8")
    if isinstance(marshaled, str):
        parsed = json.loads(marshaled)
        if isinstance(parsed, dict):
            return parsed
    raise TypeError("lark.JSON.marshal(data) must produce a JSON object")


def event_payload_from_sdk_data(
    data: Any,
    *,
    verification_token: str | None = None,
    lark_module: Any | None = None,
) -> dict[str, Any]:
    return _inject_header_token(
        sdk_data_to_dict(data, lark_module),
        verification_token if verification_token is not None else os.getenv("FEISHU_VERIFICATION_TOKEN"),
    )


def card_payload_from_sdk_data(
    data: Any,
    *,
    verification_token: str | None = None,
    lark_module: Any | None = None,
) -> dict[str, Any]:
    return _inject_header_token(
        sdk_data_to_dict(data, lark_module),
        verification_token if verification_token is not None else os.getenv("FEISHU_CARD_VERIFICATION_TOKEN"),
    )


def dispatch_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from app.main import feishu_events

    with SessionLocal() as db:
        return feishu_events(payload, db)


def dispatch_card_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from app.main import feishu_card_callback

    with SessionLocal() as db:
        return feishu_card_callback(payload, db)


def build_event_handler(lark_module: Any | None = None) -> Any:
    lark = lark_module or _load_lark_oapi()
    _, card_response_class = _load_card_action_models()

    def on_im_message_receive_v1(data: Any) -> None:
        payload = event_payload_from_sdk_data(data, lark_module=lark)
        logger.info(
            "Feishu WS event received event_type=%s event_id=%s",
            (payload.get("header") or {}).get("event_type"),
            (payload.get("header") or {}).get("event_id"),
        )
        dispatch_event_payload(payload)

    def on_card_action_trigger(data: Any) -> Any:
        payload = card_payload_from_sdk_data(data, lark_module=lark)
        logger.info(
            "Feishu WS card action received event_id=%s",
            (payload.get("header") or {}).get("event_id"),
        )
        try:
            dispatch_card_payload(payload)
            return card_response_class({"toast": {"type": "info", "content": "TeamTask action received"}})
        except HTTPException as exc:
            logger.warning("Feishu WS card action rejected: %s", exc.detail)
            return card_response_class({"toast": {"type": "warning", "content": str(exc.detail)}})

    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_im_message_receive_v1)
        .register_p2_card_action_trigger(on_card_action_trigger)
        .build()
    )


def run() -> None:
    logging.basicConfig(level=_log_level())
    init_db()
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET are required for Feishu WebSocket runner")

    lark = _load_lark_oapi()
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=build_event_handler(lark),
        log_level=_lark_log_level(lark),
    )
    logger.info("Starting Feishu WebSocket runner")
    client.start()


def _inject_header_token(payload: dict[str, Any], token: str | None) -> dict[str, Any]:
    injected = copy.deepcopy(payload)
    header = injected.get("header")
    if not isinstance(header, dict):
        header = {}
        injected["header"] = header
    if token:
        header["token"] = token
    return injected


def _load_lark_oapi() -> Any:
    try:
        import lark_oapi as lark
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise RuntimeError("Install lark-oapi to run Feishu WebSocket mode: python -m pip install -r requirements.txt") from exc
    return lark


def _load_card_action_models() -> tuple[Any, Any]:
    try:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
    except ImportError as exc:  # pragma: no cover - depends on runtime environment
        raise RuntimeError("Install lark-oapi to run Feishu WebSocket mode: python -m pip install -r requirements.txt") from exc
    return P2CardActionTrigger, P2CardActionTriggerResponse


def _log_level() -> int:
    level_name = os.getenv("FEISHU_WS_LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _lark_log_level(lark: Any) -> Any:
    level_name = os.getenv("FEISHU_WS_LOG_LEVEL", "INFO").upper()
    return getattr(lark.LogLevel, level_name, lark.LogLevel.INFO)


if __name__ == "__main__":
    run()
