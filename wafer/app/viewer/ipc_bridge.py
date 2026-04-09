from __future__ import annotations

from PySide6 import QtCore

from ...utils.logs import AppLogger
from ...core.ipc.node import Node


class ViewerIpcBridge(QtCore.QObject):
    _instance: ViewerIpcBridge | None = None

    db_content_updated = QtCore.Signal(str)
    folder_changed = QtCore.Signal(str)
    progress_updated = QtCore.Signal(str, int)
    progress_maximum = QtCore.Signal(str, int)
    show_toggled = QtCore.Signal(str, bool)
    session_focused = QtCore.Signal(str)
    session_closed = QtCore.Signal(str)
    session_restarted = QtCore.Signal(str)
    db_created = QtCore.Signal(str)
    db_deleted = QtCore.Signal(str)
    remote_log_received = QtCore.Signal(str, str, str, str)

    def __init__(self, node: Node, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._node = node
        self._subscribe_all()

    @classmethod
    def instance(cls) -> ViewerIpcBridge | None:
        return cls._instance

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

    def _subscribe_all(self):
        n = self._node
        n.subscribe("update", self._on_update)
        n.subscribe("folderchanged", self._on_folder_changed)
        n.subscribe("progress", self._on_progress)
        n.subscribe("maximum", self._on_maximum)
        n.subscribe("show_toggle", self._on_show_toggle)
        n.subscribe("session.focus", self._on_session_focus)
        n.subscribe("session.close", self._on_session_close)
        n.subscribe("session.restart", self._on_session_restart)
        n.subscribe("db.created", self._on_db_created)
        n.subscribe("db.deleted", self._on_db_deleted)
        n.subscribe("dev.log", self._on_dev_log)

    def _invoke(self, slot: str, *args):
        try:
            QtCore.QMetaObject.invokeMethod(self, slot, QtCore.Qt.QueuedConnection, *args)
        except RuntimeError:
            pass
        return True

    def _on_update(self, msg):
        return self._invoke("_emit_db_content_updated", QtCore.Q_ARG(str, msg.db or ""))

    def _on_folder_changed(self, msg):
        return self._invoke("_emit_folder_changed", QtCore.Q_ARG(str, msg.db or ""))

    def _on_progress(self, msg):
        try:
            return self._invoke(
                "_emit_progress_updated",
                QtCore.Q_ARG(str, msg.db or ""),
                QtCore.Q_ARG(int, int(msg.payload)),
            )
        except (ValueError, TypeError):
            return True

    def _on_maximum(self, msg):
        try:
            return self._invoke(
                "_emit_progress_maximum",
                QtCore.Q_ARG(str, msg.db or ""),
                QtCore.Q_ARG(int, int(msg.payload)),
            )
        except (ValueError, TypeError):
            return True

    def _on_show_toggle(self, msg):
        return self._invoke(
            "_emit_show_toggled",
            QtCore.Q_ARG(str, msg.db or ""),
            QtCore.Q_ARG(bool, bool(msg.payload)),
        )

    def _on_session_focus(self, msg):
        return self._invoke("_emit_session_focused", QtCore.Q_ARG(str, str(msg.payload)))

    def _on_session_close(self, msg):
        return self._invoke("_emit_session_closed", QtCore.Q_ARG(str, str(msg.payload)))

    def _on_session_restart(self, msg):
        return self._invoke("_emit_session_restarted", QtCore.Q_ARG(str, str(msg.payload)))

    def _on_db_created(self, msg):
        return self._invoke("_emit_db_created", QtCore.Q_ARG(str, str(msg.payload)))

    def _on_db_deleted(self, msg):
        return self._invoke("_emit_db_deleted", QtCore.Q_ARG(str, str(msg.payload)))

    def _on_dev_log(self, msg):
        p = msg.payload
        if not isinstance(p, dict):
            return True
        return self._invoke(
            "_emit_remote_log",
            QtCore.Q_ARG(str, p.get("level", "info")),
            QtCore.Q_ARG(str, p.get("text", "")),
            QtCore.Q_ARG(str, msg.source),
            QtCore.Q_ARG(str, msg.db or ""),
        )

    @QtCore.Slot(str)
    def _emit_db_content_updated(self, db: str):
        self.db_content_updated.emit(db)

    @QtCore.Slot(str)
    def _emit_folder_changed(self, db: str):
        self.folder_changed.emit(db)

    @QtCore.Slot(str, int)
    def _emit_progress_updated(self, db: str, value: int):
        self.progress_updated.emit(db, value)

    @QtCore.Slot(str, int)
    def _emit_progress_maximum(self, db: str, value: int):
        self.progress_maximum.emit(db, value)

    @QtCore.Slot(str, bool)
    def _emit_show_toggled(self, db: str, show: bool):
        self.show_toggled.emit(db, show)

    @QtCore.Slot(str)
    def _emit_session_focused(self, session_id: str):
        self.session_focused.emit(session_id)

    @QtCore.Slot(str)
    def _emit_session_closed(self, session_id: str):
        self.session_closed.emit(session_id)

    @QtCore.Slot(str)
    def _emit_session_restarted(self, session_id: str):
        self.session_restarted.emit(session_id)

    @QtCore.Slot(str)
    def _emit_db_created(self, name: str):
        self.db_created.emit(name)

    @QtCore.Slot(str)
    def _emit_db_deleted(self, name: str):
        self.db_deleted.emit(name)

    @QtCore.Slot(str, str, str, str)
    def _emit_remote_log(self, level: str, text: str, src: str, db: str):
        self.remote_log_received.emit(level, text, src, db)
