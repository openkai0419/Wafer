from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field, fields, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ...constants import DEFAULT_SESSION_NAME
from ...utils.json_io import read_json_file, write_json_file
from ...utils.paths import resolve_data_path
from ...utils.process_lock import file_lock

_STORE_FILENAME = 'sessions.json'
_BOOKMARK_DIR = 'bookmarks'

SESSION_COLORS = [
    '#4A90D9',
    '#D94A4A',
    '#4AD97A',
    '#D9A04A',
    '#9B59B6',
    '#1ABC9C',
    '#E67E22',
    '#E91E63',
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
    database_name: str = ''
    search_params: dict[str, Any] = field(default_factory=dict)
    folder_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryState:
        return _flat_from_dict(cls, data)


@dataclass
class UIState:
    window_geometry: str = ''
    component_states: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UIState:
        return _flat_from_dict(cls, data)


@dataclass
class BookmarkEntry:
    bookmark_id: str = field(default_factory=_new_id)
    name: str = ''
    query: QueryState = field(default_factory=QueryState)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            'bookmark_id': self.bookmark_id,
            'name': self.name,
            'query': self.query.to_dict(),
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BookmarkEntry:
        if not isinstance(data, dict):
            return cls()
        query = QueryState.from_dict(data.get('query', {}))
        return cls(
            bookmark_id=data.get('bookmark_id', _new_id()),
            name=data.get('name', ''),
            query=query,
            created_at=data.get('created_at', _now_iso()),
        )


@dataclass
class SessionEntry:
    session_id: str = field(default_factory=_new_id)
    name: str = ''
    color: str = ''
    ui: UIState = field(default_factory=UIState)
    bookmark_id: str = ''
    query_snapshot: QueryState | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            'session_id': self.session_id,
            'name': self.name,
            'color': self.color,
            'ui': self.ui.to_dict(),
            'bookmark_id': self.bookmark_id,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if self.query_snapshot is not None:
            d['query_snapshot'] = self.query_snapshot.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionEntry:
        if not isinstance(data, dict):
            return cls()
        ui = UIState.from_dict(data.get('ui', {}))
        qs_raw = data.get('query_snapshot')
        qs = QueryState.from_dict(qs_raw) if isinstance(qs_raw, dict) else None
        return cls(
            session_id=data.get('session_id', _new_id()),
            name=data.get('name', ''),
            color=data.get('color', ''),
            ui=ui,
            bookmark_id=data.get('bookmark_id', ''),
            query_snapshot=qs,
            created_at=data.get('created_at', _now_iso()),
            updated_at=data.get('updated_at', _now_iso()),
        )


class SessionStore:
    _instance: SessionStore | None = None

    @classmethod
    def instance(cls) -> SessionStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, path: str | None = None):
        self._path = path or resolve_data_path(_STORE_FILENAME)
        self._lock_path = self._path + '.lock'

    def _load_raw(self) -> dict[str, Any]:
        data = read_json_file(self._path, default=None)
        if isinstance(data, dict):
            return data
        return {'sessions': {}, 'active_session_ids': [], 'restore_session_ids': []}

    def _save_raw(self, data: dict[str, Any]) -> None:
        write_json_file(self._path, data)

    def _locked_update(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        with file_lock(self._lock_path):
            raw = self._load_raw()
            result = fn(raw)
            self._save_raw(raw)
            return result

    def list_sessions(self) -> list[SessionEntry]:
        raw = self._load_raw()
        sessions = raw.get('sessions', {})
        return [SessionEntry.from_dict(v) for v in sessions.values()]

    def get_session(self, session_id: str) -> SessionEntry | None:
        raw = self._load_raw()
        entry = raw.get('sessions', {}).get(session_id)
        if entry is None:
            return None
        return SessionEntry.from_dict(entry)

    def save_session(self, entry: SessionEntry) -> None:
        entry.updated_at = _now_iso()
        def _update(raw):
            raw.setdefault('sessions', {})[entry.session_id] = entry.to_dict()
        self._locked_update(_update)

    def delete_session(self, session_id: str) -> bool:
        def _update(raw):
            sessions = raw.get('sessions', {})
            if session_id not in sessions:
                return False
            del sessions[session_id]
            active = raw.get('active_session_ids', [])
            if session_id in active:
                active.remove(session_id)
            restore = raw.get('restore_session_ids', [])
            if session_id in restore:
                restore.remove(session_id)
            return True
        return self._locked_update(_update)

    def get_active_session_ids(self) -> list[str]:
        raw = self._load_raw()
        return list(raw.get('active_session_ids', []))

    def set_active_session_ids(self, ids: list[str]) -> None:
        def _update(raw):
            raw['active_session_ids'] = list(ids)
        self._locked_update(_update)

    def get_restore_session_ids(self) -> list[str]:
        raw = self._load_raw()
        ids = raw.get('restore_session_ids', [])
        sessions = raw.get('sessions', {})
        return [sid for sid in ids if sid in sessions]

    def set_restore_session_ids(self, ids: list[str]) -> None:
        def _update(raw):
            raw['restore_session_ids'] = list(ids)
        self._locked_update(_update)

    def claim_session(self, session_id: str) -> bool:
        def _update(raw):
            active = raw.setdefault('active_session_ids', [])
            if session_id in active:
                return False
            active.append(session_id)
            return True
        return self._locked_update(_update)

    def has_session_name(self, name: str) -> bool:
        return any(e.name == name for e in self.list_sessions())

    def find_session_by_name(self, name: str) -> SessionEntry | None:
        for e in self.list_sessions():
            if e.name == name:
                return e
        return None

    def create_session(self, name: str, color: str = '') -> str | None:
        def _update(raw):
            sessions = raw.setdefault('sessions', {})
            for v in sessions.values():
                if v.get('name') == name:
                    return None
            sid = _new_id()
            entry = SessionEntry(session_id=sid, name=name, color=color)
            entry.updated_at = _now_iso()
            sessions[sid] = entry.to_dict()
            return sid
        return self._locked_update(_update)

    def create_session_with_unique_name(self, base_name: str = '', color: str = '') -> str:
        def _update(raw):
            sessions = raw.setdefault('sessions', {})
            existing = {v.get('name') for v in sessions.values()}
            name = base_name or f'{DEFAULT_SESSION_NAME}1'
            if name in existing:
                n = 1
                while f'{base_name} ({n})' in existing:
                    n += 1
                name = f'{base_name} ({n})'
            sid = _new_id()
            entry = SessionEntry(session_id=sid, name=name, color=color)
            entry.updated_at = _now_iso()
            sessions[sid] = entry.to_dict()
            return sid
        return self._locked_update(_update)

    def next_default_name(self) -> str:
        existing_names = {e.name for e in self.list_sessions()}
        n = 1
        while f'{DEFAULT_SESSION_NAME}{n}' in existing_names:
            n += 1
        return f'{DEFAULT_SESSION_NAME}{n}'

    def find_inactive_session_id(self) -> str | None:
        raw = self._load_raw()
        active = set(raw.get('active_session_ids', []))
        for sid in raw.get('sessions', {}):
            if sid not in active:
                return sid
        return None

    def list_session_names(self) -> list[str]:
        return [e.name for e in self.list_sessions()]

    def set_session_color(self, session_id: str, color: str) -> bool:
        def _update(raw):
            sessions = raw.get('sessions', {})
            data = sessions.get(session_id)
            if data is None:
                return False
            entry = SessionEntry.from_dict(data)
            entry.color = color
            entry.updated_at = _now_iso()
            sessions[session_id] = entry.to_dict()
            return True
        return self._locked_update(_update)

    def rename_session(self, session_id: str, new_name: str) -> bool:
        def _update(raw):
            sessions = raw.get('sessions', {})
            data = sessions.get(session_id)
            if data is None:
                return False
            for sid, v in sessions.items():
                if sid != session_id and v.get('name') == new_name:
                    return False
            entry = SessionEntry.from_dict(data)
            entry.name = new_name
            entry.updated_at = _now_iso()
            sessions[session_id] = entry.to_dict()
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
        if not bookmark_id or not re.fullmatch(r'[\w-]+', bookmark_id):
            raise ValueError(f'invalid bookmark id: {bookmark_id!r}')
        return self._base / f'{bookmark_id}.json'

    def list_bookmarks(self) -> list[BookmarkEntry]:
        if not self._base.is_dir():
            return []
        entries = []
        for f in sorted(self._base.iterdir()):
            if f.suffix == '.json' and f.is_file():
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
