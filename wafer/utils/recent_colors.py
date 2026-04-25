from __future__ import annotations

from ..core.app_settings import app_settings

MAX_RECENT = 16
SETTINGS_PREFIX = "color_picker/recent/"


def _key(scope: str) -> str:
    return f"{SETTINGS_PREFIX}{scope or 'general'}"


def load(scope: str = "general") -> list[str]:
    raw = app_settings.get(_key(scope), default=[], value_type=list)
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, str) and c]


def add(color: str, scope: str = "general") -> list[str]:
    if not color:
        return load(scope)
    color = color.lower()
    items = [c for c in load(scope) if c.lower() != color]
    items.insert(0, color)
    items = items[:MAX_RECENT]
    app_settings.save_immediate(_key(scope), items)
    return items
