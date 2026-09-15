from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from ..common.window_state import DialogLayoutStore
from ..common.dpi import dpix


_standalone_dialogs: dict[str, QtWidgets.QDialog] = {}


def open_standalone(
    widget_factory: Callable[[], QtWidgets.QWidget],
    title: str,
    store_key: str,
    size: tuple[int, int] | None = None,
    parent: QtWidgets.QWidget | None = None,
) -> QtWidgets.QWidget:
    existing = _standalone_dialogs.get(store_key)
    if existing is not None and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return existing.content_widget
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setWindowFlags(dlg.windowFlags() | QtCore.Qt.Window | QtCore.Qt.WindowMinimizeButtonHint | QtCore.Qt.WindowMaximizeButtonHint)
    dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    dlg.resize(*(size if size else (dpix(550), dpix(700))))
    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    content = widget_factory()
    dlg.content_widget = content
    layout.addWidget(content)
    store = DialogLayoutStore(store_key)
    store.restore(dlg)
    _standalone_dialogs[store_key] = dlg

    def _on_close(event):
        store.save(dlg)
        _standalone_dialogs.pop(store_key, None)
        QtWidgets.QDialog.closeEvent(dlg, event)

    dlg.closeEvent = _on_close
    dlg.show()
    return content
