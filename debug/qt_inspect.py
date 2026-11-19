import enum
import sys
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from wafer.core.logs import AppLogger
from wafer.qt.commands.bridge import Command
from wafer.qt.commands.command.core import CommandRegistry

MAIN_WINDOW_MODULE = "wafer.app.viewer.mainwindow"
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
DEFAULT_TREE_DEPTH = 3
DEFAULT_SCREENSHOT_SIDE = 1600
FIELD_TYPES = (QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)
WHEEL_NOTCH = 120
MOUSE_BUTTONS = {"left": QtCore.Qt.LeftButton, "right": QtCore.Qt.RightButton, "middle": QtCore.Qt.MiddleButton}
MODIFIER_NAMES = {
    "ctrl": QtCore.Qt.ControlModifier,
    "control": QtCore.Qt.ControlModifier,
    "shift": QtCore.Qt.ShiftModifier,
    "alt": QtCore.Qt.AltModifier,
    "meta": QtCore.Qt.MetaModifier,
    "win": QtCore.Qt.MetaModifier,
}


class AmbiguousTargetError(LookupError):
    pass


def active_modal() -> QtWidgets.QWidget | None:
    return QtWidgets.QApplication.activeModalWidget() or QtWidgets.QApplication.activePopupWidget()


def screenshot(target: str | None = None, max_side: int | None = DEFAULT_SCREENSHOT_SIDE) -> bytes:
    if max_side is not None and max_side <= 0:
        raise ValueError(f"max_side must be positive, not {max_side}")
    widget = _default_window() if target is None else find_widget(target)
    pixmap = widget.grab()
    if max_side is not None and max(pixmap.width(), pixmap.height()) > max_side:
        pixmap = pixmap.scaled(max_side, max_side, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.WriteOnly)
    if not pixmap.save(buffer, "PNG"):
        raise RuntimeError(f"could not encode a screenshot of {_label(widget)} as PNG")
    buffer.close()
    return bytes(data.data())


def get_state() -> dict:
    window = _main_window()
    if window is None:
        return {}
    return {
        "database": window.database_name or "",
        "paths": list(window.folder_view.get_selected_paths()),
        "query": _plain(window.query_coord.capture()),
        "selected": list(window.grid_items.selected_paths()),
        "count": window.grid_items.count(),
    }


def widget_tree(root: str | None = None, depth: int = DEFAULT_TREE_DEPTH) -> list[dict]:
    roots = _visible_roots() if root is None else [find_widget(root)]
    return [_tree_node(widget, depth) for widget in roots]


def get_property(name: str, prop: str) -> Any:
    widget = find_widget(name)
    dynamic = {bytes(raw).decode() for raw in widget.dynamicPropertyNames()}
    if widget.metaObject().indexOfProperty(prop) >= 0 or prop in dynamic:
        return _plain(widget.property(prop))
    value = getattr(widget, prop)
    return _plain(value() if callable(value) else value)


def list_commands(filter: str = "") -> list[dict]:
    needle = filter.lower()
    entries = []
    for command_id, command_class in sorted(CommandRegistry.instance().get_all_commands().items()):
        meta = command_class.meta
        if needle and needle not in command_id.lower() and needle not in meta.display.lower():
            continue
        entries.append(
            {
                "id": command_id,
                "display": meta.display,
                "hidden": meta.hidden,
                "params": [{"name": p.name, "required": p.required, "description": p.description} for p in meta.params or []],
            }
        )
    return entries


def run_command(id: str, args: dict | None = None) -> dict:
    if not CommandRegistry.instance().has_command(id):
        raise LookupError(f"command {id!r} is not registered")
    kwargs = dict(args or {})
    QtCore.QTimer.singleShot(0, lambda: _invoke_command(id, kwargs))
    return {"started": True}


def modal_state() -> dict | None:
    modal = active_modal()
    if modal is None:
        return None
    widgets = _visible_widgets(modal)
    if isinstance(modal, QtWidgets.QMenu):
        buttons = [_action_state(action) for action in modal.actions() if not action.isSeparator() and action.isVisible()]
    else:
        buttons = [_button_state(w) for w in widgets if isinstance(w, QtWidgets.QAbstractButton)]
    return {
        "title": modal.windowTitle(),
        "class": type(modal).__name__,
        "object_name": modal.objectName(),
        "labels": [w.text() for w in widgets if isinstance(w, QtWidgets.QLabel) and w.text()],
        "fields": [_field_state(w) for w in widgets if _is_field(w)],
        "buttons": buttons,
    }


def modal_input(field: str, value: str) -> dict:
    _require_modal()
    widget = _input_widget(find_widget(field, _blocking_roots(), FIELD_TYPES))
    if isinstance(widget, QtWidgets.QAbstractButton) and widget.isCheckable():
        _require_enabled(widget.isEnabled(), field)
        if widget.isChecked() != (value.strip().lower() in TRUE_VALUES):
            _later(widget, widget.click, f"modal_input {field!r}")
            return {**_describe(widget), "deferred": True}
        return _describe(widget)
    _enter_value(widget, value)
    return _describe(widget)


def modal_click(text: str) -> dict:
    modal = _require_modal()
    wanted = _plain_text(text)
    if isinstance(modal, QtWidgets.QMenu):
        action = next((a for a in modal.actions() if a.isVisible() and _plain_text(a.text()) == wanted), None)
        if action is None:
            raise LookupError(f"the open menu has no item {text!r}")
        _require_enabled(action.isEnabled(), text)
        _later(modal, lambda: _trigger_menu_action(modal, action), f"modal_click {text!r}")
        return {"class": "QAction", "object_name": action.objectName(), "text": action.text(), "deferred": True}
    button = next((w for w in _visible_widgets(modal) if isinstance(w, QtWidgets.QAbstractButton) and _plain_text(w.text()) == wanted), None)
    if button is None:
        raise LookupError(f"the modal {modal.windowTitle()!r} has no button {text!r}")
    _require_enabled(button.isEnabled(), text)
    _later(button, button.click, f"modal_click {text!r}")
    return {**_describe(button), "deferred": True}


def click(target: str) -> dict:
    widget = _reachable_widget(target, (QtWidgets.QAbstractButton,))
    _require_enabled(widget.isEnabled(), target)
    if isinstance(widget, QtWidgets.QAbstractButton):
        _later(widget, widget.click, f"click {target!r}")
    else:
        _later(widget, lambda: QTest.mouseClick(widget, QtCore.Qt.LeftButton), f"click {target!r}")
    return {**_describe(widget), "deferred": True}


def type_text(target: str, text: str) -> dict:
    widget = _text_receiver(_input_widget(_reachable_widget(target, FIELD_TYPES)))
    widget.setFocus()
    QTest.keyClicks(widget, text)
    return _describe(widget)


def key(target: str | None, sequence: str) -> dict:
    keys = QtGui.QKeySequence(sequence)
    if keys.isEmpty():
        raise ValueError(f"{sequence!r} is not a key sequence")
    widget = _key_receiver() if target is None else _reachable_widget(target, FIELD_TYPES)
    _later(widget, lambda: QTest.keySequence(widget, keys), f"key {sequence!r}")
    return {**_describe(widget), "deferred": True}


def mouse(target: str, kind: str = "click", button: str = "left", x: int | None = None, y: int | None = None, modifiers: str = "") -> dict:
    send = MOUSE_KINDS.get(kind)
    if send is None:
        raise ValueError(f"kind must be one of {sorted(MOUSE_KINDS)}, not {kind!r}")
    qt_button = MOUSE_BUTTONS.get(button)
    if qt_button is None:
        raise ValueError(f"button must be one of {sorted(MOUSE_BUTTONS)}, not {button!r}")
    qt_modifiers = _modifiers(modifiers)
    widget, point, receiver, local = _pointer_target(target, x, y)
    _later(receiver, lambda: send(receiver, qt_button, qt_modifiers, local), f"mouse {kind} {target!r}")
    return {**_describe(widget), "position": [point.x(), point.y()], "deferred": True}


def wheel(target: str, dy: int = 0, dx: int = 0, x: int | None = None, y: int | None = None, modifiers: str = "") -> dict:
    if not dy and not dx:
        raise ValueError("wheel needs dy or dx (notches; negative dy scrolls down)")
    qt_modifiers = _modifiers(modifiers)
    widget, point, receiver, local = _pointer_target(target, x, y)
    delta = QtCore.QPoint(dx * WHEEL_NOTCH, dy * WHEEL_NOTCH)
    _later(receiver, lambda: _send_wheel(receiver, local, delta, qt_modifiers), f"wheel {target!r}")
    return {**_describe(widget), "position": [point.x(), point.y()], "deferred": True}


def find_widget(target: str, roots: list[QtWidgets.QWidget] | None = None, prefer: tuple[type, ...] = ()) -> QtWidgets.QWidget:
    roots = _search_roots() if roots is None else roots
    for root in roots:
        for widget in _visible_widgets(root):
            if widget.objectName() == target:
                return widget
    wanted = _plain_text(target)
    for root in roots:
        matches = [w for w in _visible_widgets(root) if wanted in _texts(w)]
        if matches:
            return _single_match(target, matches, prefer)
    raise LookupError(f"no visible widget has the objectName or text {target!r}")


def _single_match(target: str, matches: list[QtWidgets.QWidget], prefer: tuple[type, ...]) -> QtWidgets.QWidget:
    if len(matches) > 1 and prefer:
        matches = [w for w in matches if isinstance(w, prefer)] or matches
    if len(matches) > 1:
        names = ", ".join(f"{type(w).__name__} {w.objectName()!r}" for w in matches)
        raise AmbiguousTargetError(f"the text {target!r} matches more than one widget ({names}); use an objectName")
    return matches[0]


def _reachable_widget(target: str, prefer: tuple[type, ...]) -> QtWidgets.QWidget:
    roots = _blocking_roots()
    if not roots:
        return find_widget(target, prefer=prefer)
    try:
        return find_widget(target, roots, prefer)
    except AmbiguousTargetError:
        raise
    except LookupError as missing:
        if not _exists(target):
            raise
        raise LookupError(f"{target!r} is blocked by {_blocker_name(roots)}") from missing


def _blocking_roots() -> list[QtWidgets.QWidget]:
    app = QtWidgets.QApplication
    return [w for w in (app.activePopupWidget(), app.activeModalWidget()) if w is not None]


def _blocker_name(roots: list[QtWidgets.QWidget]) -> str:
    modal = QtWidgets.QApplication.activeModalWidget()
    if modal is not None:
        return f"modal {modal.windowTitle() or type(modal).__name__!r}"
    return f"popup {type(roots[0]).__name__}"


def _exists(target: str) -> bool:
    wanted = _plain_text(target)
    return any(w.objectName() == target or wanted in _texts(w) for root in _search_roots() for w in _visible_widgets(root))


def _inside(widget: QtWidgets.QWidget, roots: list[QtWidgets.QWidget]) -> bool:
    current = widget
    while current is not None:
        if current in roots:
            return True
        current = current.parentWidget()
    return False


def _search_roots() -> list[QtWidgets.QWidget]:
    app = QtWidgets.QApplication
    roots: list[QtWidgets.QWidget] = []
    for widget in [app.activePopupWidget(), app.activeModalWidget(), app.activeWindow(), *app.topLevelWidgets()]:
        if widget is not None and widget.isVisible() and widget not in roots:
            roots.append(widget)
    return roots


def _visible_roots() -> list[QtWidgets.QWidget]:
    return [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]


def _visible_widgets(root: QtWidgets.QWidget) -> list[QtWidgets.QWidget]:
    return [root, *(w for w in root.findChildren(QtWidgets.QWidget) if w.isVisible())]


def _default_window() -> QtWidgets.QWidget:
    window = active_modal() or QtWidgets.QApplication.activeWindow()
    if window is not None:
        return window
    roots = _visible_roots()
    if not roots:
        raise LookupError("no window is visible")
    return roots[0]


def _main_window() -> QtWidgets.QMainWindow | None:
    module = sys.modules.get(MAIN_WINDOW_MODULE)
    if module is None:
        return None
    windows = [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, module.MainWindow)]
    active = QtWidgets.QApplication.activeWindow()
    if active in windows:
        return active
    visible = [w for w in windows if w.isVisible()]
    return (visible or windows or [None])[0]


def _require_modal() -> QtWidgets.QWidget:
    modal = active_modal()
    if modal is None:
        raise LookupError("no modal dialog or popup is open")
    return modal


def _require_enabled(enabled: bool, target: str) -> None:
    if not enabled:
        raise ValueError(f"{target!r} is disabled")


def _later(widget: QtWidgets.QWidget, action: Callable[[], Any], what: str) -> None:
    def run():
        if not shiboken6.isValid(widget):
            AppLogger.warning(f"[debug] {what}: the widget was deleted before the input was sent")
            return
        try:
            action()
        except Exception as e:
            AppLogger.warning(f"[debug] {what} failed", exc=e)

    QtCore.QTimer.singleShot(0, run)


def _modifiers(text: str) -> QtCore.Qt.KeyboardModifier:
    combined = QtCore.Qt.NoModifier
    for name in filter(None, (part.strip().lower() for part in text.split("+"))):
        modifier = MODIFIER_NAMES.get(name)
        if modifier is None:
            raise ValueError(f"unknown modifier {name!r}; use {'/'.join(sorted(MODIFIER_NAMES))} joined by '+'")
        combined |= modifier
    return combined


def _pointer_target(target: str, x: int | None, y: int | None) -> tuple[QtWidgets.QWidget, QtCore.QPoint, QtWidgets.QWidget, QtCore.QPoint]:
    widget = _reachable_widget(target, ())
    point = _point_in(widget, x, y)
    _require_enabled(widget.isEnabled(), target)
    receiver, local = _pointer_receiver(widget, point)
    return widget, point, receiver, local


def _point_in(widget: QtWidgets.QWidget, x: int | None, y: int | None) -> QtCore.QPoint:
    if (x is None) != (y is None):
        raise ValueError("give both x and y, or neither for the center")
    if x is None:
        return widget.rect().center()
    point = QtCore.QPoint(x, y)
    if not widget.rect().contains(point):
        raise ValueError(f"({x}, {y}) is outside {_label(widget)} (size {widget.width()}x{widget.height()})")
    return point


def _pointer_receiver(widget: QtWidgets.QWidget, point: QtCore.QPoint) -> tuple[QtWidgets.QWidget, QtCore.QPoint]:
    if isinstance(widget, QtWidgets.QAbstractScrollArea):
        viewport = widget.viewport()
        local = viewport.mapFrom(widget, point)
        if viewport.rect().contains(local):
            return viewport, local
    return widget, point


def _mouse_click(widget: QtWidgets.QWidget, button: QtCore.Qt.MouseButton, modifiers: QtCore.Qt.KeyboardModifier, point: QtCore.QPoint) -> None:
    QTest.mousePress(widget, button, modifiers, point)
    _mouse_release(widget, button, modifiers, point)


def _mouse_double(widget: QtWidgets.QWidget, button: QtCore.Qt.MouseButton, modifiers: QtCore.Qt.KeyboardModifier, point: QtCore.QPoint) -> None:
    QTest.mousePress(widget, button, modifiers, point)
    QTest.mouseRelease(widget, button, modifiers, point)
    QTest.mouseDClick(widget, button, modifiers, point)
    QTest.mouseRelease(widget, button, modifiers, point)


def _mouse_release(widget: QtWidgets.QWidget, button: QtCore.Qt.MouseButton, modifiers: QtCore.Qt.KeyboardModifier, point: QtCore.QPoint) -> None:
    QTest.mouseRelease(widget, button, modifiers, point)
    if button == QtCore.Qt.RightButton and shiboken6.isValid(widget):
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, point, widget.mapToGlobal(point), modifiers)
        QtWidgets.QApplication.sendEvent(widget, event)


def _mouse_move(widget: QtWidgets.QWidget, button: QtCore.Qt.MouseButton, modifiers: QtCore.Qt.KeyboardModifier, point: QtCore.QPoint) -> None:
    QTest.mouseMove(widget, point)


MOUSE_KINDS = {"click": _mouse_click, "double": _mouse_double, "press": QTest.mousePress, "release": _mouse_release, "move": _mouse_move}


def _send_wheel(receiver: QtWidgets.QWidget, local: QtCore.QPoint, delta: QtCore.QPoint, modifiers: QtCore.Qt.KeyboardModifier) -> None:
    position = QtCore.QPointF(local)
    event = QtGui.QWheelEvent(position, QtCore.QPointF(receiver.mapToGlobal(local)), QtCore.QPoint(), delta, QtCore.Qt.NoButton, modifiers, QtCore.Qt.NoScrollPhase, False)
    QtWidgets.QApplication.sendEvent(receiver, event)


def _invoke_command(command_id: str, kwargs: dict) -> None:
    try:
        Command.invoke(command_id, parent=QtWidgets.QApplication.activeWindow(), **kwargs)
    except Exception as e:
        AppLogger.warning(f"[debug] run_command {command_id!r} failed", exc=e)


def _trigger_menu_action(menu: QtWidgets.QMenu, action: QtGui.QAction) -> None:
    menu.setActiveAction(action)
    QTest.keyClick(menu, QtCore.Qt.Key_Return)


def _input_widget(widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    if not isinstance(widget, QtWidgets.QLabel):
        return widget
    if widget.buddy() is not None:
        return widget.buddy()
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if isinstance(layout, QtWidgets.QFormLayout):
        for row in range(layout.rowCount()):
            label = layout.itemAt(row, QtWidgets.QFormLayout.LabelRole)
            field = layout.itemAt(row, QtWidgets.QFormLayout.FieldRole)
            if label is not None and label.widget() is widget and field is not None and field.widget() is not None:
                return field.widget()
    raise LookupError(f"the label {widget.text()!r} has no input field")


def _text_receiver(widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    if isinstance(widget, QtWidgets.QComboBox) and widget.isEditable():
        return widget.lineEdit()
    return widget


def _key_receiver() -> QtWidgets.QWidget:
    roots = _blocking_roots()
    focus = QtWidgets.QApplication.focusWidget()
    if roots:
        return focus if focus is not None and _inside(focus, roots) else roots[0]
    widget = focus or QtWidgets.QApplication.activeWindow()
    if widget is None:
        raise LookupError("no widget has the keyboard focus")
    return widget


def _enter_value(widget: QtWidgets.QWidget, value: str) -> None:
    if isinstance(widget, QtWidgets.QComboBox) and not widget.isEditable():
        index = widget.findText(value)
        if index < 0:
            items = [widget.itemText(i) for i in range(widget.count())]
            raise ValueError(f"{value!r} is not one of {items}")
        widget.setCurrentIndex(index)
        return
    receiver = _text_receiver(widget)
    if not isinstance(receiver, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
        raise TypeError(f"cannot enter a value into {type(widget).__name__}")
    receiver.setFocus()
    QTest.keyClick(receiver, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
    if value:
        QTest.keyClicks(receiver, value)
    else:
        QTest.keyClick(receiver, QtCore.Qt.Key_Delete)


def _is_field(widget: QtWidgets.QWidget) -> bool:
    if isinstance(widget, QtWidgets.QLineEdit):
        return not isinstance(widget.parentWidget(), (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox))
    return isinstance(widget, FIELD_TYPES)


def _field_state(widget: QtWidgets.QWidget) -> dict:
    if isinstance(widget, QtWidgets.QComboBox):
        text = widget.currentText()
    elif isinstance(widget, (QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
        text = widget.toPlainText()
    else:
        text = widget.text()
    placeholder = widget.placeholderText() if hasattr(widget, "placeholderText") else ""
    return {"object_name": widget.objectName(), "class": type(widget).__name__, "text": text, "placeholder": placeholder}


def _button_state(button: QtWidgets.QAbstractButton) -> dict:
    return {"text": _plain_text(button.text()), "enabled": button.isEnabled(), "checked": button.isChecked() if button.isCheckable() else None}


def _action_state(action: QtGui.QAction) -> dict:
    return {"text": _plain_text(action.text()), "enabled": action.isEnabled(), "checked": action.isChecked() if action.isCheckable() else None}


def _tree_node(widget: QtWidgets.QWidget, depth: int) -> dict:
    children = widget.findChildren(QtWidgets.QWidget, options=QtCore.Qt.FindDirectChildrenOnly) if depth > 0 else []
    geometry = widget.geometry()
    return {
        "class": type(widget).__name__,
        "object_name": widget.objectName(),
        "text": next(iter(_texts(widget)), ""),
        "visible": widget.isVisible(),
        "geometry": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
        "children": [_tree_node(child, depth - 1) for child in children],
    }


def _texts(widget: QtWidgets.QWidget) -> list[str]:
    texts = []
    if isinstance(widget, (QtWidgets.QAbstractButton, QtWidgets.QLabel)):
        texts.append(widget.text())
    if isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit, QtWidgets.QTextEdit)):
        texts.append(widget.placeholderText())
    if isinstance(widget, QtWidgets.QGroupBox):
        texts.append(widget.title())
    if widget.isWindow():
        texts.append(widget.windowTitle())
    return [plain for plain in (_plain_text(text) for text in texts) if plain]


def _plain_text(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _describe(widget: QtWidgets.QWidget) -> dict:
    return {"class": type(widget).__name__, "object_name": widget.objectName(), "text": next(iter(_texts(widget)), "")}


def _label(widget: QtWidgets.QWidget) -> str:
    return widget.objectName() or type(widget).__name__


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    if isinstance(value, (QtCore.QPoint, QtCore.QPointF)):
        return [value.x(), value.y()]
    if isinstance(value, (QtCore.QSize, QtCore.QSizeF)):
        return [value.width(), value.height()]
    if isinstance(value, (QtCore.QRect, QtCore.QRectF)):
        return [value.x(), value.y(), value.width(), value.height()]
    if isinstance(value, QtGui.QColor):
        return value.name(QtGui.QColor.HexArgb)
    if isinstance(value, QtCore.QByteArray):
        return bytes(value.data())
    return repr(value)
