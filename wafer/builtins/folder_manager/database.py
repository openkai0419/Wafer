import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

from wafer.core.common.paths import normalize_path, setting_db_path
from wafer.core.db.path_scope import compile_ignore_patterns
from wafer.core.db.setting_db import SettingDB


@dataclass(frozen=True)
class FolderSettings:
    roots: list[str]
    excluded: set[str]
    ignore_pattern_re: re.Pattern[str] | None


def read_folder_settings(name: str) -> FolderSettings:
    path = setting_db_path(name)
    if not os.path.exists(path):
        return FolderSettings([], set(), None)
    parents, ignores, patterns = SettingDB(path).get_all_folder_settings()
    return FolderSettings(
        roots=[normalize_path(p) for p in parents],
        excluded={normalize_path(p) for p in ignores},
        ignore_pattern_re=compile_ignore_patterns(patterns),
    )


def initial_database(host_name: str | None, last_name: str, names: Sequence[str]) -> str:
    for candidate in (host_name, last_name):
        if candidate and candidate in names:
            return candidate
    return names[0] if names else ""
