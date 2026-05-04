from __future__ import annotations

from typing import Any


def render_feishu_card(internal_card: dict[str, Any]) -> dict[str, Any]:
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": internal_card.get("summary") or internal_card.get("title") or "",
            },
        }
    ]

    task_fields = internal_card.get("task_fields") or {}
    if task_fields:
        elements.append(
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{key}:** {value}",
                        },
                    }
                    for key, value in _flat_fields(task_fields).items()
                    if value is not None
                ][:10],
            }
        )

    related_resources = internal_card.get("related_resources") or {}
    resource_text = _resource_markdown(related_resources)
    if resource_text:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": resource_text,
                },
            }
        )

    for action in internal_card.get("actions") or []:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": action.get("text") or action.get("action_key")},
                        "type": "primary",
                        "value": {
                            "action_key": action["action_key"],
                            "contract_id": action["contract_id"],
                            "recipient_user_id": action["recipient_user_id"],
                            "source_event_id": action.get("source_event_id"),
                            **{
                                key: value
                                for key, value in (action.get("payload") or {}).items()
                                if key not in {"action_key", "contract_id", "recipient_user_id", "source_event_id"}
                            },
                        },
                    }
                ],
            }
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": internal_card.get("title") or "TeamTask"},
            "template": "blue",
        },
        "elements": elements,
    }


def _flat_fields(fields: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in fields.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(_flat_fields(value, name))
        elif isinstance(value, list):
            flat[name] = ", ".join(str(item) for item in value)
        else:
            flat[name] = value
    return flat


def _resource_markdown(resources: dict[str, Any]) -> str:
    lines: list[str] = []
    high = resources.get("high_confidence") or []
    low = resources.get("low_confidence") or []
    if high:
        lines.append("**High-confidence resources**")
        lines.extend(_resource_lines(high))
    if low:
        lines.append("**Low-confidence resources**")
        lines.extend(_resource_lines(low))
    return "\n".join(lines)


def _resource_lines(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items[:5]:
        title = item.get("title") or "Untitled"
        url = item.get("url") or ""
        confidence = item.get("confidence")
        reason = item.get("reason") or ""
        if url:
            lines.append(f"- [{title}]({url}) ({confidence}): {reason}")
        else:
            lines.append(f"- {title} ({confidence}): {reason}")
    return lines
