from __future__ import annotations

import os

from ..constants import VIRTUAL_PATH_SEPARATOR

_ESCAPE = "%"
_SEP_ESCAPED = "%3A%3A" if VIRTUAL_PATH_SEPARATOR == "::" else "".join(f"%{ord(c):02X}" for c in VIRTUAL_PATH_SEPARATOR)
_PERCENT_ESCAPED = "%25"


def is_virtual_path(path: str | None) -> bool:
    return split_virtual_path(path) is not None


def escape_member_path(member_path: str) -> str:
    result = str(member_path).replace("\\", "/")
    result = result.replace(_ESCAPE, _PERCENT_ESCAPED)
    result = result.replace(VIRTUAL_PATH_SEPARATOR, _SEP_ESCAPED)
    return result


def unescape_member_path(member_path: str) -> str:
    result = str(member_path)
    result = result.replace(_SEP_ESCAPED, VIRTUAL_PATH_SEPARATOR)
    result = result.replace(_PERCENT_ESCAPED, _ESCAPE)
    return result


def build_virtual_path(source: str, member_path: str) -> str:
    return f"{source}{VIRTUAL_PATH_SEPARATOR}{escape_member_path(member_path)}"


def split_virtual_path(path: str) -> tuple[str, str] | None:
    if not path or VIRTUAL_PATH_SEPARATOR not in str(path):
        return None
    source, member = str(path).split(VIRTUAL_PATH_SEPARATOR, 1)
    if not source or not member:
        return None
    return source, unescape_member_path(member)


def source_path(path: str) -> str:
    parts = split_virtual_path(path) if is_virtual_path(path) else None
    return parts[0] if parts else path


def child_path(path: str) -> str | None:
    parts = split_virtual_path(path) if is_virtual_path(path) else None
    return parts[1] if parts else None


def owner_extension(path: str) -> str:
    return os.path.splitext(source_path(path))[1].lower()


def leaf_extension(path: str) -> str:
    child = child_path(path)
    target = child if child is not None else path
    return os.path.splitext(target)[1].lower()


def display_name(path: str) -> str:
    child = child_path(path)
    if child is not None:
        clean = child.replace("\\", "/").rstrip("/")
        if clean:
            return clean.rsplit("/", 1)[-1]
    return os.path.basename(source_path(path))


def physical_path(path: str) -> str:
    return source_path(path)


def physical_paths(paths: list[str] | tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(physical_path(str(p)) for p in paths if p))
