from __future__ import annotations

from datetime import datetime
from pathlib import PurePath

from ....constants import APP_NAME
from ....core.lang.manager import t
from ....core.logs import AppLogger
from ....core.store.workspace import WindowSlot


def format_iso(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        AppLogger.warning(f"Invalid ISO datetime in workspace store: {value!r}")
        return value


def slot_summary(slot: WindowSlot) -> str:
    path = slot.path if isinstance(slot.path, dict) else {}
    database = str(path.get("database_name") or t("No database"))
    selected = [str(p) for p in (path.get("selected") or []) if p]
    if not selected:
        return database
    first = PurePath(selected[0]).name or selected[0]
    if len(selected) == 1:
        return f"{database} / {first}"
    return f"{database} / {first} +{len(selected) - 1}"


def slot_title(slot: WindowSlot) -> str:
    return str(getattr(slot, "name", "") or "").strip() or slot_summary(slot)


def slot_subtitle(slot: WindowSlot) -> str:
    updated = format_iso(slot.updated_at)
    if str(getattr(slot, "name", "") or "").strip():
        summary = slot_summary(slot)
        return f"{summary} / {updated}" if updated else summary
    return updated


def slot_tooltip(slot: WindowSlot) -> str:
    parts = [slot_title(slot)]
    summary = slot_summary(slot)
    if summary != parts[0]:
        parts.append(summary)
    updated = format_iso(slot.updated_at)
    if updated:
        parts.append(f"{t('Last updated')}: {updated}")
    parts.append(f"slot_id: {slot.slot_id}")
    return "\n".join(parts)


def window_title(name: str, selected_dirs: list[str], database_name: str) -> str:
    name = (name or "").strip()
    if name:
        return name
    if selected_dirs:
        return ", ".join(d.rsplit("/", 1)[-1] or d for d in selected_dirs)
    return database_name or APP_NAME
