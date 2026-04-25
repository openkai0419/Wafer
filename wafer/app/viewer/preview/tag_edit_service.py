from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from PySide6 import QtCore

from ....utils.logs import AppLogger
from ....utils.notifier import Notifier
from ....core.lang.manager import t


_DEFAULT_TIMEOUT_SEC = 10.0


@dataclass
class PendingEdit:
    op: str
    value: str = ""
    locked: bool = False
    new_key: str = ""
    request_id: str = ""
    sent_at: float = field(default_factory=time.time)
    failed: bool = False


class TagEditService(QtCore.QObject):
    overlay_changed = QtCore.Signal(str)
    commit_confirmed = QtCore.Signal(str, dict, list)

    _instance: TagEditService | None = None

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._pending: dict[tuple[str, str], PendingEdit] = {}
        self._request_index: dict[str, list[tuple[str, str]]] = {}
        self._timeout_timer: QtCore.QTimer | None = None

    def _ensure_timeout_timer(self):
        if self._timeout_timer is not None:
            return
        if QtCore.QCoreApplication.instance() is None:
            return
        self._timeout_timer = QtCore.QTimer(self)
        self._timeout_timer.setInterval(2000)
        self._timeout_timer.timeout.connect(self._check_timeouts)
        self._timeout_timer.start()

    @classmethod
    def instance(cls) -> TagEditService:
        if cls._instance is None:
            cls._instance = TagEditService()
        return cls._instance

    def submit(
        self,
        paths: list[str],
        upserts: list[tuple[str, str, bool]],
        deletes: list[str],
        db: str,
        *,
        lock_only: bool = False,
        renames: list[tuple[str, str, str, bool]] | None = None,
        file_hash: str | None = None,
    ) -> str | None:
        renames = list(renames or [])
        paths = list(paths or [])
        if not paths or (not upserts and not deletes and not renames):
            return None
        node = self._resolve_node()
        if node is None:
            Notifier.warning(t("Tag edit failed: IPC node unavailable"))
            return None
        request_id = uuid.uuid4().hex
        keys: list[tuple[str, str]] = []
        if file_hash:
            for key, value, locked in upserts:
                self._pending[(file_hash, key)] = PendingEdit(op="upsert", value=value, locked=locked, request_id=request_id)
                keys.append((file_hash, key))
            for key in deletes:
                self._pending[(file_hash, key)] = PendingEdit(op="delete", request_id=request_id)
                keys.append((file_hash, key))
            for old_key, new_key, value, locked in renames:
                self._pending[(file_hash, old_key)] = PendingEdit(op="rename", value=value, locked=locked, new_key=new_key, request_id=request_id)
                keys.append((file_hash, old_key))
            self._request_index[request_id] = keys
        payload = {
            "paths": list(paths),
            "request_id": request_id,
            "upserts": [{"key": k, "value": v, "locked": bool(lk)} for (k, v, lk) in upserts],
            "renames": [{"old": ok, "new": nk, "value": v, "locked": bool(lk)} for (ok, nk, v, lk) in renames],
            "deletes": list(deletes),
            "lock_only": bool(lock_only),
        }
        try:
            node.send_reliable("tags.update", payload, dst="indexer", db=db)
        except Exception as e:
            AppLogger.warning(f"[TagEdit] send_reliable failed: {e}", exc=e)
            self._mark_failed(request_id)
            Notifier.warning(t("Tag edit send failed"))
            return None
        if file_hash:
            self._ensure_timeout_timer()
        AppLogger.info(f"[TagEdit] submitted paths={len(paths)} hash={file_hash or '-'} upserts={len(upserts)} renames={len(renames)} deletes={len(deletes)} rid={request_id}")
        if file_hash:
            self.overlay_changed.emit(file_hash)
        return request_id

    def handle_ack(self, payload: dict):
        if not isinstance(payload, dict):
            return
        request_id = payload.get("request_id", "")
        if not request_id:
            return
        applied_by_path = payload.get("applied") or {}
        deleted_by_path = payload.get("deleted") or {}
        hashes_by_path = payload.get("file_hashes") or {}
        applied_keys = {k for keys in applied_by_path.values() for k in (keys or [])}
        deleted_keys_set = {k for keys in deleted_by_path.values() for k in (keys or [])}
        deleted_keys: list[str] = list(deleted_keys_set)
        keys = self._request_index.pop(request_id, [])
        affected_hashes: set[str] = set()
        committed: dict[str, tuple[str, bool]] = {}
        synthetic_deletes: list[str] = []
        for fh, key in keys:
            current = self._pending.get((fh, key))
            if current is None:
                continue
            if current.request_id != request_id:
                continue
            if current.op == "upsert" and key in applied_keys:
                committed[key] = (current.value, current.locked)
            elif current.op == "rename" and current.new_key in applied_keys:
                committed[current.new_key] = (current.value, current.locked)
                if key not in deleted_keys_set:
                    synthetic_deletes.append(key)
            self._pending.pop((fh, key), None)
            affected_hashes.add(fh)
        if synthetic_deletes:
            deleted_keys = list(deleted_keys) + synthetic_deletes
        for fh in hashes_by_path.values():
            if fh:
                affected_hashes.add(fh)
        for fh in affected_hashes:
            self.commit_confirmed.emit(fh, committed, deleted_keys)
            self.overlay_changed.emit(fh)
        AppLogger.info(f"[TagEdit] ack rid={request_id} applied={len(committed)} deleted={len(deleted_keys)}")

    def apply_overlay(self, file_hash: str | None, tags: dict[str, str], locks: dict[str, bool]) -> tuple[dict[str, str], dict[str, bool], dict[str, str]]:
        if not file_hash:
            return tags, locks, {}
        merged_tags = dict(tags)
        merged_locks = dict(locks)
        states: dict[str, str] = {}
        for (fh, key), pending in self._pending.items():
            if fh != file_hash:
                continue
            if pending.op == "delete":
                merged_tags.pop(key, None)
                merged_locks.pop(key, None)
                states[key] = "deleting" if not pending.failed else "delete_failed"
            elif pending.op == "rename":
                merged_tags.pop(key, None)
                merged_locks.pop(key, None)
                merged_tags[pending.new_key] = pending.value
                merged_locks[pending.new_key] = pending.locked
                states[pending.new_key] = "saving" if not pending.failed else "save_failed"
            else:
                merged_tags[key] = pending.value
                merged_locks[key] = pending.locked
                states[key] = "saving" if not pending.failed else "save_failed"
        return merged_tags, merged_locks, states

    def has_pending_for(self, file_hash: str) -> bool:
        return any(fh == file_hash for (fh, _) in self._pending)

    def _resolve_node(self):
        try:
            from ..ipc_bridge import ViewerIpcBridge

            bridge = ViewerIpcBridge.instance()
            if bridge is None:
                return None
            return bridge.node
        except Exception as e:
            AppLogger.warning(f"[TagEdit] resolve node failed: {e}", exc=e)
            return None

    def _mark_failed(self, request_id: str):
        keys = self._request_index.get(request_id, [])
        affected: set[str] = set()
        for fh, key in keys:
            pending = self._pending.get((fh, key))
            if pending:
                pending.failed = True
                affected.add(fh)
        for fh in affected:
            self.overlay_changed.emit(fh)

    def _check_timeouts(self):
        now = time.time()
        timed_out_rids: set[str] = set()
        for pending in list(self._pending.values()):
            if pending.failed:
                continue
            if now - pending.sent_at > _DEFAULT_TIMEOUT_SEC:
                timed_out_rids.add(pending.request_id)
        for rid in timed_out_rids:
            AppLogger.warning(f"[TagEdit] timeout rid={rid}")
            self._mark_failed(rid)
            Notifier.warning(t("Tag edit timed out"))
