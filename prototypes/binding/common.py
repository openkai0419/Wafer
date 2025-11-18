from PySide6 import QtCore, QtGui, QtWidgets
from .manager import BindingManager

class WidgetRef:
    def __init__(self, name: str, widget):
        self.name = name
        self.widget = widget
    def __str__(self):
        return self.name

def resolve_scope_by_focus() -> tuple[str | None, QtWidgets.QWidget | None]:
    w = QtWidgets.QApplication.focusWidget()
    if not w:
        return None, None
    anc = BindingManager.instance().find_registered_ancestor(w)
    if not anc:
        return None, None
    if hasattr(anc, "binding_scope") and callable(getattr(anc, "binding_scope")):
        return anc.binding_scope(), anc
    return None, anc

def resolve_scope_by_cursor_pos(pos: QtCore.QPoint | None = None) -> tuple[str | None, QtWidgets.QWidget | None]:
    p = pos or QtGui.QCursor.pos()
    w = BindingManager.instance().find_binding_widget_at(p)
    if not w:
        return None, None
    if hasattr(w, "binding_scope") and callable(getattr(w, "binding_scope")):
        return w.binding_scope(), w
    return None, w
