from __future__ import annotations

import json
from typing import Any, Callable

from .logs import AppLogger


def get_callable(obj: Any, name: str) -> Callable[..., Any] | None:
    m = getattr(obj, name, None)
    return m if callable(m) else None


def invoke(obj: Any, name: str) -> Any:
    m = get_callable(obj, name)
    return m() if m is not None else None


def invoke_int(obj: Any, name: str, default: int = 0) -> int:
    v = invoke(obj, name)
    if v is None:
        return int(default)
    if isinstance(v, int) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        return int(s) if s.isdigit() else int(default)
    try:
        return int(v)
    except Exception as e:
        AppLogger.warning(f"invoke_int failed: {type(obj).__name__}.{name}", exc=e)
        return int(default)


def to_int(v: Any, default: int = 0) -> int:
    if v is None:
        return int(default)
    if isinstance(v, int) and not isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        return int(s) if s.isdigit() else int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def try_cast(func: Callable[[Any], Any], value: Any, default: Any = None) -> Any:
    try:
        return func(value)
    except (TypeError, ValueError):
        return default


def try_json_loads(value: Any, default: Any = None, on_error: Callable[[Exception], None] | None = None) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        if on_error is not None:
            on_error(e)
        return default


def try_invoke(obj: Any, name: str, default: Any = None, warn_text: str | None = None) -> Any:
    m = get_callable(obj, name)
    if m is None:
        return default
    try:
        return m()
    except Exception as e:
        if warn_text:
            AppLogger.warning(warn_text, exc=e)
        return default


def widget_prop_bool(w: Any, name: str) -> bool:
    if w is None:
        return False
    try:
        return bool(w.property(str(name)))
    except Exception as e:
        AppLogger.warning(f"widget_prop_bool failed: {type(w).__name__}.{name}", exc=e)
        return False
