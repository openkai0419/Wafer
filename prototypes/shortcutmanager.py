from typing import Dict, List
from PySide6 import QtCore, QtGui, QtWidgets
from .commandbase import CommandRegistry


class ShortcutManager:
    def __init__(self):
        self._bindings: Dict[int, Dict[str, str]] = {}
        self._shortcuts: Dict[int, List[QtGui.QShortcut]] = {}
        self._registry = CommandRegistry()

    def set_bindings(self, widget: QtWidgets.QWidget, bindings: Dict[str, str]):
        wid = id(widget)
        for sc in self._shortcuts.get(wid, []):
            try:
                sc.activated.disconnect()
            except Exception:
                pass
            sc.setParent(None)
            sc.deleteLater()
        self._shortcuts[wid] = []
        self._bindings[wid] = dict(bindings)
        for seq, cmd in bindings.items():
            if not seq or not cmd:
                continue
            sc = QtGui.QShortcut(QtGui.QKeySequence(seq), widget)
            sc.activated.connect(lambda c=cmd: self._exec(c))
            self._shortcuts[wid].append(sc)

    def get_bindings(self, widget: QtWidgets.QWidget) -> Dict[str, str]:
        wid = id(widget)
        return dict(self._bindings.get(wid, {}))

    def clear_bindings(self, widget: QtWidgets.QWidget):
        self.set_bindings(widget, {})

    def _exec(self, command_name: str):
        try:
            self._registry.execute(command_name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(None, "Error", str(e))
