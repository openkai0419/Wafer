from __future__ import annotations

import bisect
import fnmatch
import re
from collections.abc import Iterable, Sequence

from ....core.common.paths import normalize_path


def normalize_prefixes(paths: Iterable[str]) -> list[str]:
    return sorted({normalize_path(path) for path in paths})


def contains_path_prefix(prefixes: Sequence[str], path: str) -> bool:
    if not prefixes:
        return False
    normalized = normalize_path(path)
    idx = bisect.bisect_right(prefixes, normalized)
    if idx <= 0:
        return False
    prefix = prefixes[idx - 1]
    return normalized == prefix or normalized.startswith(_child_prefix(prefix))


def _child_prefix(prefix: str) -> str:
    return prefix if prefix.endswith("/") else f"{prefix}/"


def compile_ignore_patterns(patterns: Sequence[str]) -> re.Pattern[str] | None:
    if not patterns:
        return None
    return re.compile("|".join(fnmatch.translate(pattern) for pattern in patterns))
