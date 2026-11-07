from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from wafer._version import __version__
from wafer.core.common.json_io import read_json_file
from wafer.core.common.paths import resolve_cache_path
from wafer.core.logs import AppLogger

INDEX_SCHEMA = 1
SKIPPED_DIRS = frozenset({"__pycache__"})
TOP_LEVEL_SKIPPED_DIRS = frozenset({"lib"})


@dataclass(frozen=True, slots=True)
class PluginEntry:
    kind: str
    module: str
    class_name: str
    name: str


@dataclass(frozen=True, slots=True)
class ExtensionRecord:
    fingerprint: str
    plugins: tuple[PluginEntry, ...]


def index_path() -> str:
    return str(resolve_cache_path("plugin_index.json"))


def extension_fingerprint(folder: str) -> str:
    rows = []
    for root, dirs, files in os.walk(folder):
        skipped = SKIPPED_DIRS | TOP_LEVEL_SKIPPED_DIRS if root == folder else SKIPPED_DIRS
        dirs[:] = [d for d in dirs if d not in skipped]
        for file in files:
            if not file.endswith(".py"):
                continue
            full = os.path.join(root, file)
            stat = os.stat(full)
            relative = os.path.relpath(full, folder).replace(os.sep, "/")
            rows.append((relative, stat.st_size, stat.st_mtime_ns))
    rows.sort()
    digest = hashlib.sha1()
    for relative, size, mtime_ns in rows:
        digest.update(f"{relative}\0{size}\0{mtime_ns}\n".encode())
    return digest.hexdigest()


def serialize(records: dict[str, ExtensionRecord]) -> str:
    extensions = {
        name: {
            "fingerprint": record.fingerprint,
            "plugins": [{"kind": p.kind, "module": p.module, "class": p.class_name, "name": p.name} for p in record.plugins],
        }
        for name, record in sorted(records.items())
    }
    data = {"schema": INDEX_SCHEMA, "wafer_version": __version__, "extensions": extensions}
    return json.dumps(data, ensure_ascii=False, indent=1)


def parse_plugin(raw: object) -> PluginEntry:
    if not isinstance(raw, dict):
        raise ValueError(f"plugin entry is not an object: {raw!r}")
    values = [raw.get(key) for key in ("kind", "module", "class", "name")]
    if not all(isinstance(v, str) for v in values):
        raise ValueError(f"plugin entry has non-string fields: {raw!r}")
    return PluginEntry(*values)


def parse_record(raw: object) -> ExtensionRecord:
    if not isinstance(raw, dict):
        raise ValueError(f"extension record is not an object: {raw!r}")
    fingerprint = raw.get("fingerprint")
    plugins = raw.get("plugins")
    if not isinstance(fingerprint, str) or not isinstance(plugins, list):
        raise ValueError(f"extension record has a wrong shape: {raw!r}")
    return ExtensionRecord(fingerprint, tuple(parse_plugin(p) for p in plugins))


def read_index(path: str | None = None) -> dict[str, ExtensionRecord]:
    path = path or index_path()
    data = read_json_file(path, None)
    if data is None:
        return {}
    if not isinstance(data, dict) or data.get("schema") != INDEX_SCHEMA or data.get("wafer_version") != __version__:
        return {}
    extensions = data.get("extensions")
    if not isinstance(extensions, dict):
        AppLogger.warning(f"Plugin index ignored (bad shape): {path}")
        return {}
    try:
        return {name: parse_record(raw) for name, raw in extensions.items()}
    except ValueError as exc:
        AppLogger.warning(f"Plugin index ignored (bad shape): {path}", exc=exc)
        return {}


def write_index(records: dict[str, ExtensionRecord], path: str | None = None) -> bool:
    path = path or index_path()
    text = serialize(records)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError) as exc:
        AppLogger.warning(f"Plugin index unreadable, rewriting: {path}", exc=exc)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temp, path)
    except OSError as exc:
        AppLogger.warning(f"Plugin index write failed: {path}", exc=exc)
        if os.path.exists(temp):
            os.remove(temp)
        return False
    return True
