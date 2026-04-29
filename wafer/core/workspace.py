from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from typing import Any
from collections.abc import Callable

from ..utils.json_io import read_json_file, write_json_file
from ..utils.paths import resolve_data_path
from ..utils.process_lock import file_lock

_STORE_FILENAME = "workspace.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class BarSpec:
    filter: str = "text"
    params: dict[str, Any] = field(default_factory=dict)
    op: str | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BarSpec:
        if not isinstance(data, dict):
            return cls()
        return cls(
            filter=data.get("filter", "text"),
            params=dict(data.get("params") or {}),
            op=data.get("op"),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class UIPreset:
    preset_id: str = field(default_factory=_new_id)
    name: str = ""
    window_state: dict[str, Any] = field(default_factory=dict)
    component_states: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UIPreset:
        if not isinstance(data, dict):
            return cls()
        return cls(
            preset_id=data.get("preset_id", _new_id()),
            name=data.get("name", ""),
            window_state=dict(data.get("window_state") or {}),
            component_states=dict(data.get("component_states") or {}),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )


@dataclass
class PathPreset:
    preset_id: str = field(default_factory=_new_id)
    name: str = ""
    database_name: str = ""
    expanded: list[str] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PathPreset:
        if not isinstance(data, dict):
            return cls()
        return cls(
            preset_id=data.get("preset_id", _new_id()),
            name=data.get("name", ""),
            database_name=data.get("database_name", ""),
            expanded=list(data.get("expanded") or []),
            selected=list(data.get("selected") or []),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )


@dataclass
class QueryPreset:
    preset_id: str = field(default_factory=_new_id)
    name: str = ""
    bars: list[BarSpec] = field(default_factory=list)
    sort_by: str = "path"
    ascending: bool = False
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "name": self.name,
            "bars": [b.to_dict() for b in self.bars],
            "sort_by": self.sort_by,
            "ascending": self.ascending,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryPreset:
        if not isinstance(data, dict):
            return cls()
        return cls(
            preset_id=data.get("preset_id", _new_id()),
            name=data.get("name", ""),
            bars=[BarSpec.from_dict(b) for b in (data.get("bars") or [])],
            sort_by=data.get("sort_by", "path"),
            ascending=bool(data.get("ascending", False)),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )


@dataclass
class WindowSlot:
    slot_id: str = field(default_factory=_new_id)
    name: str = ""
    ui: dict[str, Any] = field(default_factory=dict)
    path: dict[str, Any] = field(default_factory=dict)
    query: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WindowSlot:
        if not isinstance(data, dict):
            return cls()
        return cls(
            slot_id=data.get("slot_id", _new_id()),
            name=data.get("name", ""),
            ui=dict(data.get("ui") or {}),
            path=dict(data.get("path") or {}),
            query=dict(data.get("query") or {}),
            updated_at=data.get("updated_at", _now_iso()),
        )


_EMPTY_RAW = {
    "ui_presets": {},
    "path_presets": {},
    "query_presets": {},
    "slots": {},
    "active_slot_ids": [],
    "restore_slot_ids": [],
}


class WorkspaceStore:
    _instance: WorkspaceStore | None = None

    @classmethod
    def instance(cls) -> WorkspaceStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, path: str | None = None):
        self._path = path or resolve_data_path(_STORE_FILENAME)
        self._lock_path = self._path + ".lock"

    def get_store_mtime(self) -> float:
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return 0.0

    def _load_raw(self) -> dict[str, Any]:
        data = read_json_file(self._path, default=None)
        if not isinstance(data, dict):
            return {k: (list(v) if isinstance(v, list) else dict(v)) for k, v in _EMPTY_RAW.items()}
        for k, v in _EMPTY_RAW.items():
            data.setdefault(k, list(v) if isinstance(v, list) else dict(v))
        return data

    def _save_raw(self, data: dict[str, Any]) -> None:
        write_json_file(self._path, data)

    def _locked_update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with file_lock(self._lock_path):
            raw = self._load_raw()
            result = fn(raw)
            self._save_raw(raw)
            return result

    # --- Preset helpers (shared CRUD across UI/Path/Query buckets) ---
    def _list_presets(self, bucket: str, cls):
        return [cls.from_dict(v) for v in self._load_raw().get(bucket, {}).values()]

    def _get_preset(self, bucket: str, preset_id: str, cls):
        v = self._load_raw().get(bucket, {}).get(preset_id)
        return cls.from_dict(v) if v else None

    def _save_preset(self, bucket: str, preset) -> None:
        preset.updated_at = _now_iso()

        def _u(raw):
            raw.setdefault(bucket, {})[preset.preset_id] = preset.to_dict()

        self._locked_update(_u)

    def _delete_preset(self, bucket: str, preset_id: str) -> bool:
        def _u(raw):
            d = raw.get(bucket, {})
            if preset_id not in d:
                return False
            del d[preset_id]
            return True

        return self._locked_update(_u)

    def _rename_preset(self, bucket: str, preset_id: str, new_name: str, cls) -> bool:
        def _u(raw):
            d = raw.get(bucket, {}).get(preset_id)
            if d is None:
                return False
            for pid, v in raw.get(bucket, {}).items():
                if pid != preset_id and v.get("name") == new_name:
                    return False
            entry = cls.from_dict(d)
            entry.name = new_name
            entry.updated_at = _now_iso()
            raw[bucket][preset_id] = entry.to_dict()
            return True

        return self._locked_update(_u)

    def _update_preset(self, bucket: str, preset_id: str, cls, apply: Callable[[Any], None]) -> bool:
        def _u(raw):
            d = raw.get(bucket, {}).get(preset_id)
            if d is None:
                return False
            entry = cls.from_dict(d)
            apply(entry)
            entry.updated_at = _now_iso()
            raw[bucket][preset_id] = entry.to_dict()
            return True

        return self._locked_update(_u)

    # --- UI presets ---
    def list_ui_presets(self) -> list[UIPreset]:
        return self._list_presets("ui_presets", UIPreset)

    def get_ui_preset(self, preset_id: str) -> UIPreset | None:
        return self._get_preset("ui_presets", preset_id, UIPreset)

    def save_ui_preset(self, preset: UIPreset) -> None:
        self._save_preset("ui_presets", preset)

    def delete_ui_preset(self, preset_id: str) -> bool:
        return self._delete_preset("ui_presets", preset_id)

    def rename_ui_preset(self, preset_id: str, new_name: str) -> bool:
        return self._rename_preset("ui_presets", preset_id, new_name, UIPreset)

    def update_ui_preset(self, preset_id: str, window_state: dict[str, Any], component_states: dict[str, Any]) -> bool:
        def apply(p: UIPreset) -> None:
            p.window_state = dict(window_state or {})
            p.component_states = dict(component_states or {})

        return self._update_preset(
            "ui_presets",
            preset_id,
            UIPreset,
            apply,
        )

    # --- Path presets ---
    def list_path_presets(self) -> list[PathPreset]:
        return self._list_presets("path_presets", PathPreset)

    def get_path_preset(self, preset_id: str) -> PathPreset | None:
        return self._get_preset("path_presets", preset_id, PathPreset)

    def save_path_preset(self, preset: PathPreset) -> None:
        self._save_preset("path_presets", preset)

    def delete_path_preset(self, preset_id: str) -> bool:
        return self._delete_preset("path_presets", preset_id)

    def rename_path_preset(self, preset_id: str, new_name: str) -> bool:
        return self._rename_preset("path_presets", preset_id, new_name, PathPreset)

    def update_path_preset(self, preset_id: str, database_name: str, expanded: list[str], selected: list[str]) -> bool:
        def apply(p: PathPreset) -> None:
            p.database_name = database_name or ""
            p.expanded = list(expanded or [])
            p.selected = list(selected or [])

        return self._update_preset(
            "path_presets",
            preset_id,
            PathPreset,
            apply,
        )

    # --- Query presets ---
    def list_query_presets(self) -> list[QueryPreset]:
        return self._list_presets("query_presets", QueryPreset)

    def get_query_preset(self, preset_id: str) -> QueryPreset | None:
        return self._get_preset("query_presets", preset_id, QueryPreset)

    def save_query_preset(self, preset: QueryPreset) -> None:
        self._save_preset("query_presets", preset)

    def delete_query_preset(self, preset_id: str) -> bool:
        return self._delete_preset("query_presets", preset_id)

    def rename_query_preset(self, preset_id: str, new_name: str) -> bool:
        return self._rename_preset("query_presets", preset_id, new_name, QueryPreset)

    def update_query_preset(self, preset_id: str, bars: list[BarSpec | dict[str, Any]], sort_by: str, ascending: bool) -> bool:
        def apply(p: QueryPreset) -> None:
            p.bars = [b if isinstance(b, BarSpec) else BarSpec.from_dict(b) for b in (bars or [])]
            p.sort_by = sort_by or "path"
            p.ascending = bool(ascending)

        return self._update_preset(
            "query_presets",
            preset_id,
            QueryPreset,
            apply,
        )

    def snapshot(self) -> tuple[list[UIPreset], list[PathPreset], list[QueryPreset]]:
        """Single-read snapshot of all presets. Avoids 3 separate file loads."""
        raw = self._load_raw()
        return (
            [UIPreset.from_dict(v) for v in raw.get("ui_presets", {}).values()],
            [PathPreset.from_dict(v) for v in raw.get("path_presets", {}).values()],
            [QueryPreset.from_dict(v) for v in raw.get("query_presets", {}).values()],
        )

    # --- Window slots ---
    def get_slot(self, slot_id: str) -> WindowSlot | None:
        v = self._load_raw().get("slots", {}).get(slot_id)
        return WindowSlot.from_dict(v) if v else None

    def list_recent_slots(self, limit: int = 10, include_active: bool = False) -> list[WindowSlot]:
        raw = self._load_raw()
        active = set(raw.get("active_slot_ids", []))
        slots = []
        for sid, data in raw.get("slots", {}).items():
            if not include_active and sid in active:
                continue
            slots.append(WindowSlot.from_dict(data))
        slots.sort(key=lambda s: s.updated_at, reverse=True)
        return slots[: max(0, int(limit))]

    def get_last_used_database_name(self) -> str:
        slots = self._load_raw().get("slots", {})
        if not slots:
            return ""
        latest = max(slots.values(), key=lambda v: v.get("updated_at", ""), default=None)
        if not latest:
            return ""
        path = latest.get("path") or {}
        return str(path.get("database_name") or "")

    def save_slot(self, slot: WindowSlot) -> None:
        slot.updated_at = _now_iso()

        def _u(raw):
            slots = raw.setdefault("slots", {})
            data = slot.to_dict()
            existing = slots.get(slot.slot_id)
            existing_name = str(existing.get("name") or "") if isinstance(existing, dict) else ""
            if existing_name:
                data["name"] = existing_name
            slots[slot.slot_id] = data

        self._locked_update(_u)

    def rename_slot(self, slot_id: str, name: str) -> bool:
        def _u(raw):
            slots = raw.get("slots", {})
            data = slots.get(slot_id)
            if data is None:
                return False
            slot = WindowSlot.from_dict(data)
            slot.name = str(name or "").strip()
            slot.updated_at = _now_iso()
            slots[slot_id] = slot.to_dict()
            return True

        return self._locked_update(_u)

    def delete_slot(self, slot_id: str) -> bool:
        def _u(raw):
            slots = raw.get("slots", {})
            if slot_id not in slots:
                return False
            del slots[slot_id]
            for key in ("active_slot_ids", "restore_slot_ids"):
                ids = raw.get(key, [])
                if slot_id in ids:
                    ids.remove(slot_id)
            return True

        return self._locked_update(_u)

    def forget_slot_snapshot(self, slot_id: str) -> bool:
        def _u(raw):
            slots = raw.get("slots", {})
            if slot_id not in slots:
                return False
            del slots[slot_id]
            return True

        return self._locked_update(_u)

    def get_active_slot_ids(self) -> list[str]:
        return list(self._load_raw().get("active_slot_ids", []))

    def set_active_slot_ids(self, ids: list[str]) -> None:
        def _u(raw):
            raw["active_slot_ids"] = list(ids)

        self._locked_update(_u)

    def get_restore_slot_ids(self) -> list[str]:
        raw = self._load_raw()
        ids = raw.get("restore_slot_ids", [])
        slots = raw.get("slots", {})
        return [sid for sid in ids if sid in slots]

    def set_restore_slot_ids(self, ids: list[str]) -> None:
        def _u(raw):
            raw["restore_slot_ids"] = list(ids)

        self._locked_update(_u)

    def acquire_slot(self, slot_id: str | None = None, seed: dict[str, Any] | None = None) -> tuple[str, WindowSlot, bool]:
        """Acquire an existing slot or create a new one.

        Returns (slot_id, slot, is_existing). If slot_id matches an existing slot, returns it.
        Otherwise creates a new slot, optionally seeded with `seed` content, and registers it as active.
        """

        def _u(raw):
            slots = raw.setdefault("slots", {})
            active = raw.setdefault("active_slot_ids", [])
            active_set = set(active)
            existed = bool(slot_id and slot_id in slots)
            if existed:
                sid = slot_id
                entry = WindowSlot.from_dict(slots[sid])
            else:
                sid = slot_id or _new_id()
                base = seed or {}
                entry = WindowSlot(
                    slot_id=sid,
                    ui=dict(base.get("ui") or {}),
                    path=dict(base.get("path") or {}),
                    query=dict(base.get("query") or {}),
                )
                slots[sid] = entry.to_dict()
            if sid not in active_set:
                active.append(sid)
            return sid, entry, existed

        return self._locked_update(_u)

    def release_slot(self, slot_id: str) -> None:
        def _u(raw):
            active = raw.get("active_slot_ids", [])
            if slot_id in active:
                active.remove(slot_id)

        self._locked_update(_u)
