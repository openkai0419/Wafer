from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore

from ...core.logs import AppLogger
from ...core.ipc.node import Node

UPDATE_TOPICS = ("update", "folderchanged", "files.changed")


class ViewerIpcBridge(QtCore.QObject):
    _instance: ViewerIpcBridge | None = None
    _update_instance: ViewerIpcBridge | None = None

    HANDLERS = {
        "update": "_on_update",
        "folderchanged": "_on_folder_changed",
        "progress": "_on_progress",
        "maximum": "_on_maximum",
        "show_toggle": "_on_show_toggle",
        "slot.close": "_on_slot_close",
        "slot.restart": "_on_slot_restart",
        "slot.shutdown": "_on_slot_shutdown",
        "slot.renamed": "_on_slot_renamed",
        "slot.open_path": "_on_slot_open_path",
        "app.shutdown": "_on_app_shutdown",
        "db.created": "_on_db_created",
        "db.deleted": "_on_db_deleted",
        "dev.log": "_on_dev_log",
        "tags.updated": "_on_tags_updated",
        "files.changed": "_on_files_changed",
        "settings.changed": "_on_settings_changed",
    }

    db_content_updated = QtCore.Signal(str)
    folder_changed = QtCore.Signal(str, list)
    progress_updated = QtCore.Signal(str, int)
    progress_maximum = QtCore.Signal(str, int)
    show_toggled = QtCore.Signal(str, bool)
    slot_closed = QtCore.Signal(str)
    slot_restarted = QtCore.Signal(str)
    slot_shutdown = QtCore.Signal(str)
    slot_renamed = QtCore.Signal(str, str)
    open_path_requested = QtCore.Signal(str, str)
    app_shutdown = QtCore.Signal()
    db_created = QtCore.Signal(str)
    db_deleted = QtCore.Signal(str)
    remote_log_received = QtCore.Signal(str, str, str, str)
    tags_updated = QtCore.Signal(dict)
    files_changed = QtCore.Signal(str, dict)
    settings_received = QtCore.Signal(dict)

    def __init__(self, node: Node, parent: QtCore.QObject | None = None, topics: Sequence[str] | None = None):
        super().__init__(parent)
        self._node = node
        for topic in topics if topics is not None else self.HANDLERS:
            node.subscribe(topic, getattr(self, self.HANDLERS[topic]))

    @classmethod
    def instance(cls) -> ViewerIpcBridge | None:
        return cls._instance

    @classmethod
    def updates(cls) -> ViewerIpcBridge | None:
        return cls._instance or cls._update_instance

    @classmethod
    def for_updates(cls, node: Node, parent: QtCore.QObject | None = None) -> ViewerIpcBridge:
        bridge = cls(node, parent, topics=UPDATE_TOPICS)
        cls._update_instance = bridge
        return bridge

    def stop_updates(self):
        if ViewerIpcBridge._update_instance is self:
            ViewerIpcBridge._update_instance = None

    def start(self):
        ViewerIpcBridge._instance = self
        self._node.start()
        AppLogger.set_node(self._node, role="viewer")

    def stop(self):
        self._node.stop()
        if ViewerIpcBridge._instance is self:
            ViewerIpcBridge._instance = None

    @property
    def node(self) -> Node:
        return self._node

    def _on_update(self, msg):
        self.db_content_updated.emit(msg.db or "")
        return True

    def _on_folder_changed(self, msg):
        p = msg.payload if isinstance(msg.payload, dict) else {}
        self.folder_changed.emit(msg.db or "", [path for path in p.get("paths") or () if isinstance(path, str)])
        return True

    def _on_progress(self, msg):
        try:
            value = int(msg.payload)
        except (ValueError, TypeError) as e:
            AppLogger.debug(f"[IPC] invalid progress payload: {msg.payload!r}", exc=e)
            return True
        self.progress_updated.emit(msg.db or "", value)
        return True

    def _on_maximum(self, msg):
        try:
            value = int(msg.payload)
        except (ValueError, TypeError) as e:
            AppLogger.debug(f"[IPC] invalid maximum payload: {msg.payload!r}", exc=e)
            return True
        self.progress_maximum.emit(msg.db or "", value)
        return True

    def _on_show_toggle(self, msg):
        self.show_toggled.emit(msg.db or "", bool(msg.payload))
        return True

    def _on_slot_close(self, msg):
        self.slot_closed.emit(str(msg.payload))
        return True

    def _on_slot_restart(self, msg):
        self.slot_restarted.emit(str(msg.payload))
        return True

    def _on_slot_shutdown(self, msg):
        self.slot_shutdown.emit(str(msg.payload))
        return True

    def _on_slot_renamed(self, msg):
        p = msg.payload if isinstance(msg.payload, dict) else {}
        slot_id = p.get("slot_id")
        if not isinstance(slot_id, str) or not slot_id:
            return True
        self.slot_renamed.emit(slot_id, str(p.get("name") or ""))
        return True

    def _on_slot_open_path(self, msg):
        p = msg.payload if isinstance(msg.payload, dict) else {}
        if not self._node.session_id or p.get("slot_id") != self._node.session_id:
            return True
        path = p.get("path")
        if not isinstance(path, str) or not path:
            AppLogger.warning(f"[IPC] slot.open_path without a path: {msg.payload!r}")
            return True
        self._node.enqueue(msg.reply({"ok": True}))
        self.open_path_requested.emit(path, str(p.get("database_name") or ""))
        return True

    def _on_app_shutdown(self, msg):
        self.app_shutdown.emit()
        return True

    def _on_db_created(self, msg):
        self.db_created.emit(str(msg.payload))
        return True

    def _on_db_deleted(self, msg):
        self.db_deleted.emit(str(msg.payload))
        return True

    def _on_tags_updated(self, msg):
        p = msg.payload if isinstance(msg.payload, dict) else {}
        self.tags_updated.emit(p)
        return True

    def _on_files_changed(self, msg):
        p = msg.payload if isinstance(msg.payload, dict) else {}
        self.files_changed.emit(msg.db or "", {key: list(p.get(key) or ()) for key in ("modified", "removed", "created")})
        return True

    def _on_settings_changed(self, msg):
        p = msg.payload if isinstance(msg.payload, dict) else {}
        if p:
            self.settings_received.emit(p)
        return True

    def broadcast_settings(self, updates: dict):
        if not isinstance(updates, dict) or not updates:
            return
        self._node.send("settings.changed", dict(updates), dst="viewer")

    def _on_dev_log(self, msg):
        p = msg.payload
        if not isinstance(p, dict):
            return True
        self.remote_log_received.emit(str(p.get("level", "info")), str(p.get("text", "")), msg.source, msg.db or "")
        return True
