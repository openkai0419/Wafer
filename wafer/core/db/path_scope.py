from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable, Sequence

from ..common.paths import list_setting_db_names, normalize_path, setting_db_path
from .setting_db import SettingDB


def compile_ignore_patterns(patterns: Sequence[str]) -> re.Pattern[str] | None:
    if not patterns:
        return None
    return re.compile("|".join(fnmatch.translate(pattern) for pattern in patterns))


def comparable_path(path: str) -> str:
    normalized = normalize_path(path)
    return normalized.casefold() if os.name == "nt" else normalized


def is_under(path: str, root: str) -> bool:
    target = comparable_path(path)
    base = comparable_path(root)
    if target == base:
        return True
    return target.startswith(base if base.endswith("/") else f"{base}/")


def path_in_scope(path: str, roots: Iterable[str], ignore_folders: Iterable[str], ignore_pattern_re: re.Pattern[str] | None) -> bool:
    if not any(is_under(path, root) for root in roots):
        return False
    if any(is_under(path, folder) for folder in ignore_folders):
        return False
    return ignore_pattern_re is None or ignore_pattern_re.match(normalize_path(path)) is None


def databases_containing(path: str) -> list[str]:
    names = []
    for name in list_setting_db_names():
        roots, ignore_folders, ignore_patterns = SettingDB(str(setting_db_path(name))).get_all_folder_settings()
        if path_in_scope(path, roots, ignore_folders, compile_ignore_patterns(ignore_patterns)):
            names.append(name)
    return names
