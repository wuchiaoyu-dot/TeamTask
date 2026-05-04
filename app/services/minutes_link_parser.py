from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

DEFAULT_MINUTES_PATTERNS = (
    r"https?://[^\s)>\"]*?(?:minutes|minute|妙记|会议纪要)[^\s)>\"]*",
    r"https?://[^\s)>\"]*?(?:feishu|larksuite)[^\s)>\"]*",
)


def is_minutes_link(text: str) -> bool:
    url = extract_minutes_url(text)
    if not url:
        return False
    lowered = f"{text} {url}".lower()
    return any(marker in lowered for marker in ("minutes", "minute", "妙记", "会议纪要", "minutes_token"))


def extract_minutes_token(text: str) -> str | None:
    url = extract_minutes_url(text)
    if not url:
        return None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("minutes_token", "token", "share_token"):
        value = query.get(key)
        if value:
            return value[0]

    path_parts = [part for part in parsed.path.split("/") if part]
    for marker in ("minutes", "minute", "minutes_share", "share"):
        if marker in path_parts:
            index = path_parts.index(marker)
            if index + 1 < len(path_parts):
                return _clean_token(path_parts[index + 1])

    match = re.search(r"(?:minutes_token|token|minutes)[=/]([A-Za-z0-9_-]{6,})", url)
    return _clean_token(match.group(1)) if match else None


def extract_minutes_url(text: str) -> str | None:
    for pattern in _patterns():
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_url(match.group(0))

    match = re.search(r"https?://\S+", text)
    return _clean_url(match.group(0)) if match else None


def _patterns() -> tuple[str, ...]:
    raw = os.getenv("MINUTES_LINK_PATTERNS", "")
    custom = tuple(item.strip() for item in raw.split(",") if item.strip())
    return custom + DEFAULT_MINUTES_PATTERNS


def _clean_url(value: str) -> str:
    return value.rstrip(").,，。>\"'")


def _clean_token(value: str) -> str:
    return value.rstrip(").,，。>\"'")
