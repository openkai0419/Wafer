from typing import Any, Dict, List
import json
from PySide6 import QtCore, QtGui, QtWidgets
from .command.core import CommandRegistry
from .command.utils import to_payload_json, is_json_text, show_error


class ShortcutManager:
    def __init__(self):
        self._bindings: Dict[int, Dict[str, Any]] = {}
        self._shortcuts: Dict[int, List[QtGui.QShortcut]] = {}
        self._registry = CommandRegistry()

    def set_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[str, Any]):
        wid = id(widget)
        for sc in self._shortcuts.get(wid, []):
            try:
                sc.activated.disconnect()
            except Exception:
                pass
            sc.setParent(None)
            sc.deleteLater()
        self._shortcuts[wid] = []
        norm: Dict[str, Any] = {}
        for seq, cmd in bindings.items():
            if not seq or not cmd:
                continue
            try:
                if isinstance(cmd, str) and is_json_text(cmd):
                    norm[seq] = cmd.strip()
                else:
                    norm[seq] = to_payload_json(cmd)
            except Exception:
                norm[seq] = cmd
        self._bindings[wid] = norm
        for seq, cmd in norm.items():
            sc = QtGui.QShortcut(QtGui.QKeySequence(seq), widget)
            sc.activated.connect(lambda c=cmd: self._exec(c))
            self._shortcuts[wid].append(sc)

    def get_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, Any]:
        wid = id(widget)
        return dict(self._bindings.get(wid, {}))

    def clear_bindings(self, widget: QtWidgets.QWidget):
        self.set_bindings(widget, {})

    def _exec(self, command_name: Any):
        try:
            if isinstance(command_name, str) and is_json_text(command_name):
                self._registry.execute_payload(command_name)
                return
            if isinstance(command_name, dict):
                self._registry.execute_payload(command_name)
                return
            payload = to_payload_json(command_name)
            self._registry.execute_payload(payload)
        except Exception as e:
            show_error(None, str(e))
            raise