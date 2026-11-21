from collections.abc import Sequence

from wafer.core.logs import AppLogger
from wafer.core.store.settings import app_settings

from .rules import METRICS, HighlightRule, default_rules

RULES_KEY = "folder_manager/rules"
COLUMNS_KEY = "folder_manager/columns"
DATABASE_KEY = "folder_manager/database"
AUTO_SELECT_KEY = "folder_manager/auto_select_foldertree"
DEFAULT_COLUMNS = {"files": True, "all_files": True, "folders": True, "all_folders": False}


def read(key: str, value_type: type):
    app_settings.settings.sync()
    return app_settings.get(key, None, value_type)


def write(key: str, value) -> None:
    app_settings.save_immediate(key, value)


def load_rules() -> list[HighlightRule]:
    saved = read(RULES_KEY, None)
    if saved is None:
        return default_rules()
    if not isinstance(saved, list) or (saved and not any(isinstance(data, dict) for data in saved)):
        AppLogger.warning(f"[FolderManager] saved rules are not readable, showing the default rules: {saved!r}")
        return default_rules()
    rules = []
    for data in saved:
        try:
            rules.append(HighlightRule.from_dict(data))
        except (KeyError, TypeError, AttributeError) as exc:
            AppLogger.warning(f"[FolderManager] skipped a saved rule that could not be read: {data!r} ({exc!r})")
    return rules


def save_rules(rules: Sequence[HighlightRule]) -> None:
    write(RULES_KEY, [rule.to_dict() for rule in rules])


def load_columns() -> dict[str, bool]:
    raw = read(COLUMNS_KEY, None)
    saved = raw if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        AppLogger.warning(f"[FolderManager] saved columns are not readable, showing the default columns: {raw!r}")
    return {metric: bool(saved.get(metric, DEFAULT_COLUMNS[metric])) for metric in METRICS}


def save_columns(columns: dict[str, bool]) -> None:
    write(COLUMNS_KEY, dict(columns))


def load_auto_select() -> bool:
    return read(AUTO_SELECT_KEY, None) is True


def save_auto_select(on: bool) -> None:
    write(AUTO_SELECT_KEY, on)


def load_last_database() -> str:
    return str(read(DATABASE_KEY, str) or "")


def save_last_database(name: str) -> None:
    write(DATABASE_KEY, name)
