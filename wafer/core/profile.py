from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable

from ..constants import DEFAULT_PROFILE_NAME
from ..utils.json_io import read_json_file, write_json_file
from ..utils.paths import resolve_data_path
from ..utils.process_lock import file_lock

_STORE_FILENAME = "profiles.json"
_LEGACY_STORE_FILENAME = "sessions.json"
_BOOKMARK_DIR = "bookmarks"

PROFILE_COLORS = [
    "#4A90D9",
    "#D94A4A",
    "#4AD97A",
    "#D9A04A",
    "#9B59B6",
    "#1ABC9C",
    "#E67E22",
    "#E91E63",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _flat_from_dict(cls, data: dict[str, Any]):
    if not isinstance(data, dict):
        return cls()
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class QueryState:
    database_name: str = ""
    search_params: dict[str, Any] = field(default_factory=dict)
    folder_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryState:
        return _flat_from_dict(cls, data)


@dataclass
class UIState:
    window_state: dict[str, Any] = field(default_factory=dict)
    component_states: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UIState:
        if not isinstance(data, dict):
            return cls()
        ws = data.get("window_state", {})
        if not ws and "window_geometry" in data:
            ws = {"geometry": data["window_geometry"]}
        return cls(
            window_state=ws,
            component_states=data.get("component_states", {}),
        )


@dataclass
class BookmarkEntry:
    bookmark_id: str = field(default_factory=_new_id)
    name: str = ""
    query: QueryState = field(default_factory=QueryState)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bookmark_id": self.bookmark_id,
            "name": self.name,
            "query": self.query.to_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookmarkEntry:
        if not isinstance(data, dict):
            return cls()
        query = QueryState.from_dict(data.get("query", {}))
        return cls(
            bookmark_id=data.get("bookmark_id", _new_id()),
            name=data.get("name", ""),
            query=query,
            created_at=data.get("created_at", _now_iso()),
        )


@dataclass
class ProfileEntry:
    profile_id: str = field(default_factory=_new_id)
    name: str = ""
    color: str = ""
    ui: UIState = field(default_factory=UIState)
    bookmark_id: str = ""
    query_snapshot: QueryState | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "profile_id": self.profile_id,
            "name": self.name,
            "color": self.color,
            "ui": self.ui.to_dict(),
            "bookmark_id": self.bookmark_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.query_snapshot is not None:
            d["query_snapshot"] = self.query_snapshot.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileEntry:
        if not isinstance(data, dict):
            return cls()
        ui = UIState.from_dict(data.get("ui", {}))
        qs_raw = data.get("query_snapshot")
        qs = QueryState.from_dict(qs_raw) if isinstance(qs_raw, dict) else None
        pid = data.get("profile_id") or data.get("session_id", _new_id())
        return cls(
            profile_id=pid,
            name=data.get("name", ""),
            color=data.get("color", ""),
            ui=ui,
            bookmark_id=data.get("bookmark_id", ""),
            query_snapshot=qs,
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )


class ProfileStore:
    _instance: ProfileStore | None = None

    @classmethod
    def instance(cls) -> ProfileStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, path: str | None = None):
        if path:
            self._path = path
        else:
            self._path = resolve_data_path(_STORE_FILENAME)
            self._migrate_legacy()
        self._lock_path = self._path + ".lock"

    def _migrate_legacy(self):
        legacy = resolve_data_path(_LEGACY_STORE_FILENAME)
        if Path(legacy).is_file() and not Path(self._path).is_file():
            import shutil

            shutil.move(legacy, self._path)

    def _load_raw(self) -> dict[str, Any]:
        data = read_json_file(self._path, default=None)
        if isinstance(data, dict):
            if "sessions" in data and "profiles" not in data:
                data["profiles"] = data.pop("sessions")
            if "active_session_ids" in data and "active_profile_ids" not in data:
                data["active_profile_ids"] = data.pop("active_session_ids")
            if "restore_session_ids" in data and "restore_profile_ids" not in data:
                data["restore_profile_ids"] = data.pop("restore_session_ids")
            return data
        return {"profiles": {}, "active_profile_ids": [], "restore_profile_ids": []}

    def _save_raw(self, data: dict[str, Any]) -> None:
        write_json_file(self._path, data)

    def _locked_update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with file_lock(self._lock_path):
            raw = self._load_raw()
            result = fn(raw)
            self._save_raw(raw)
            return result

    def list_profiles(self) -> list[ProfileEntry]:
        raw = self._load_raw()
        profiles = raw.get("profiles", {})
        return [ProfileEntry.from_dict(v) for v in profiles.values()]

    def get_profile(self, profile_id: str) -> ProfileEntry | None:
        raw = self._load_raw()
        entry = raw.get("profiles", {}).get(profile_id)
        if entry is None:
            return None
        return ProfileEntry.from_dict(entry)

    def save_profile(self, entry: ProfileEntry) -> None:
        entry.updated_at = _now_iso()

        def _update(raw):
            raw.setdefault("profiles", {})[entry.profile_id] = entry.to_dict()

        self._locked_update(_update)

    def delete_profile(self, profile_id: str) -> bool:
        def _update(raw):
            profiles = raw.get("profiles", {})
            if profile_id not in profiles:
                return False
            del profiles[profile_id]
            active = raw.get("active_profile_ids", [])
            if profile_id in active:
                active.remove(profile_id)
            restore = raw.get("restore_profile_ids", [])
            if profile_id in restore:
                restore.remove(profile_id)
            return True

        return self._locked_update(_update)

    def get_active_profile_ids(self) -> list[str]:
        raw = self._load_raw()
        return list(raw.get("active_profile_ids", []))

    def set_active_profile_ids(self, ids: list[str]) -> None:
        def _update(raw):
            raw["active_profile_ids"] = list(ids)

        self._locked_update(_update)

    def get_restore_profile_ids(self) -> list[str]:
        raw = self._load_raw()
        ids = raw.get("restore_profile_ids", [])
        profiles = raw.get("profiles", {})
        return [pid for pid in ids if pid in profiles]

    def set_restore_profile_ids(self, ids: list[str]) -> None:
        def _update(raw):
            raw["restore_profile_ids"] = list(ids)

        self._locked_update(_update)

    def has_profile_name(self, name: str) -> bool:
        return any(e.name == name for e in self.list_profiles())

    def find_profile_by_name(self, name: str) -> ProfileEntry | None:
        for e in self.list_profiles():
            if e.name == name:
                return e
        return None

    def create_profile(self, name: str, color: str = "") -> str | None:
        def _update(raw):
            profiles = raw.setdefault("profiles", {})
            for v in profiles.values():
                if v.get("name") == name:
                    return None
            pid = _new_id()
            entry = ProfileEntry(profile_id=pid, name=name, color=color)
            entry.updated_at = _now_iso()
            profiles[pid] = entry.to_dict()
            return pid

        return self._locked_update(_update)

    def create_profile_with_unique_name(self, base_name: str = "", color: str = "") -> str:
        def _update(raw):
            profiles = raw.setdefault("profiles", {})
            existing = {v.get("name") for v in profiles.values()}
            name = base_name or f"{DEFAULT_PROFILE_NAME}1"
            if name in existing:
                n = 1
                while f"{name} ({n})" in existing:
                    n += 1
                name = f"{name} ({n})"
            pid = _new_id()
            entry = ProfileEntry(profile_id=pid, name=name, color=color)
            entry.updated_at = _now_iso()
            profiles[pid] = entry.to_dict()
            return pid

        return self._locked_update(_update)

    def next_default_name(self) -> str:
        existing_names = {e.name for e in self.list_profiles()}
        n = 1
        while f"{DEFAULT_PROFILE_NAME}{n}" in existing_names:
            n += 1
        return f"{DEFAULT_PROFILE_NAME}{n}"

    def find_inactive_profile_id(self) -> str | None:
        raw = self._load_raw()
        active = set(raw.get("active_profile_ids", []))
        for pid in raw.get("profiles", {}):
            if pid not in active:
                return pid
        return None

    def acquire_or_create(self, profile_id: str | None = None, default_name: str = DEFAULT_PROFILE_NAME) -> tuple[str, ProfileEntry]:
        def _update(raw):
            profiles = raw.setdefault("profiles", {})
            active = raw.setdefault("active_profile_ids", [])
            active_set = set(active)
            if profile_id and profile_id in profiles:
                pid = profile_id
            else:
                pid = None
                for p in profiles:
                    if p not in active_set:
                        pid = p
                        break
                if pid is None:
                    existing_names = {v.get("name") for v in profiles.values()}
                    if not profiles:
                        name = default_name
                    else:
                        n = 1
                        while f"{default_name}{n}" in existing_names:
                            n += 1
                        name = f"{default_name}{n}"
                    pid = _new_id()
                    entry = ProfileEntry(profile_id=pid, name=name)
                    entry.updated_at = _now_iso()
                    profiles[pid] = entry.to_dict()
            if pid not in active_set:
                active.append(pid)
            return pid, ProfileEntry.from_dict(profiles[pid])

        return self._locked_update(_update)

    def list_profile_names(self) -> list[str]:
        return [e.name for e in self.list_profiles()]

    def set_profile_color(self, profile_id: str, color: str) -> bool:
        def _update(raw):
            profiles = raw.get("profiles", {})
            data = profiles.get(profile_id)
            if data is None:
                return False
            entry = ProfileEntry.from_dict(data)
            entry.color = color
            entry.updated_at = _now_iso()
            profiles[profile_id] = entry.to_dict()
            return True

        return self._locked_update(_update)

    def rename_profile(self, profile_id: str, new_name: str) -> bool:
        def _update(raw):
            profiles = raw.get("profiles", {})
            data = profiles.get(profile_id)
            if data is None:
                return False
            for pid, v in profiles.items():
                if pid != profile_id and v.get("name") == new_name:
                    return False
            entry = ProfileEntry.from_dict(data)
            entry.name = new_name
            entry.updated_at = _now_iso()
            profiles[profile_id] = entry.to_dict()
            return True

        return self._locked_update(_update)


class BookmarkStore:
    _instance: BookmarkStore | None = None

    @classmethod
    def instance(cls) -> BookmarkStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, base_dir: str | None = None):
        self._base = Path(base_dir) if base_dir else Path(resolve_data_path(_BOOKMARK_DIR))

    def _entry_path(self, bookmark_id: str) -> Path:
        if not bookmark_id or not re.fullmatch(r"[\w-]+", bookmark_id):
            raise ValueError(f"invalid bookmark id: {bookmark_id!r}")
        return self._base / f"{bookmark_id}.json"

    def list_bookmarks(self) -> list[BookmarkEntry]:
        if not self._base.is_dir():
            return []
        entries = []
        for f in sorted(self._base.iterdir()):
            if f.suffix == ".json" and f.is_file():
                data = read_json_file(f)
                if isinstance(data, dict):
                    entries.append(BookmarkEntry.from_dict(data))
        return entries

    def get_bookmark(self, bookmark_id: str) -> BookmarkEntry | None:
        data = read_json_file(self._entry_path(bookmark_id))
        if not isinstance(data, dict):
            return None
        return BookmarkEntry.from_dict(data)

    def save_bookmark(self, entry: BookmarkEntry) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        write_json_file(self._entry_path(entry.bookmark_id), entry.to_dict())

    def delete_bookmark(self, bookmark_id: str) -> bool:
        p = self._entry_path(bookmark_id)
        if not p.is_file():
            return False
        p.unlink()
        return True
