import sys
import types

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from debug import qt_inspect
from wafer.qt.commands.command.core import CommandMeta, CommandParam, CommandRegistry, create_command_from_meta

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def make_rename_dialog() -> QtWidgets.QDialog:
    dialog = QtWidgets.QDialog()
    dialog.setWindowTitle("Rename")
    layout = QtWidgets.QFormLayout(dialog)
    layout.addRow(QtWidgets.QLabel("Pick a new name"))
    edit = QtWidgets.QLineEdit()
    edit.setObjectName("name")
    edit.setPlaceholderText("New name")
    layout.addRow("Name", edit)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)
    return dialog


@pytest.fixture
def window(qtbot):
    win = QtWidgets.QWidget()
    win.setObjectName("panel")
    win.setWindowTitle("Debug Panel")
    layout = QtWidgets.QVBoxLayout(win)
    edit = QtWidgets.QLineEdit()
    edit.setObjectName("query")
    edit.setPlaceholderText("Search")
    button = QtWidgets.QPushButton("&Go")
    layout.addWidget(edit)
    layout.addWidget(button)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win
    win.close()


def test_modal_input_and_click_during_exec(qtbot):
    dialog = make_rename_dialog()
    QtCore.QTimer.singleShot(0, lambda: (qt_inspect.modal_input("name", "typed"), qt_inspect.modal_click("OK")))
    assert dialog.exec() == 1 and dialog.findChild(QtWidgets.QLineEdit).text() == "typed"


def test_modal_input_finds_the_field_by_its_form_label(qtbot):
    dialog = make_rename_dialog()
    dialog.findChild(QtWidgets.QLineEdit).setText("old")
    QtCore.QTimer.singleShot(0, lambda: (qt_inspect.modal_input("Name", "new"), qt_inspect.modal_click("OK")))
    assert dialog.exec() == 1
    assert dialog.findChild(QtWidgets.QLineEdit).text() == "new"


def test_modal_state_describes_the_open_dialog(qtbot):
    dialog = make_rename_dialog()
    seen = []
    QtCore.QTimer.singleShot(0, lambda: (seen.append(qt_inspect.modal_state()), qt_inspect.modal_click("Cancel")))
    assert dialog.exec() == 0
    state = seen[0]
    assert state["title"] == "Rename"
    assert state["class"] == "QDialog"
    assert "Pick a new name" in state["labels"]
    assert {"object_name": "name", "class": "QLineEdit", "text": "", "placeholder": "New name"} in state["fields"]
    assert {"text": "OK", "enabled": True, "checked": None} in state["buttons"]


def test_modal_state_tells_two_modals_with_the_same_title_apart(qtbot):
    first, second = make_rename_dialog(), make_rename_dialog()
    states = []
    try:
        for dialog in (first, second):
            qtbot.addWidget(dialog)
            dialog.setWindowModality(QtCore.Qt.ApplicationModal)
            dialog.show()
            qtbot.waitUntil(lambda d=dialog: QtWidgets.QApplication.activeModalWidget() is d)
            states.append(qt_inspect.modal_state())
            assert qt_inspect.modal_state()["id"] == states[-1]["id"]
    finally:
        second.close()
        first.close()
    assert [s["title"] for s in states] == ["Rename", "Rename"]
    assert states[0]["id"] != states[1]["id"]


def test_modal_state_is_none_without_a_modal(qtbot):
    assert qt_inspect.modal_state() is None


def test_modal_click_reports_an_unknown_button(qtbot):
    dialog = make_rename_dialog()
    errors = []

    def attempt():
        try:
            qt_inspect.modal_click("Apply")
        except LookupError as e:
            errors.append(str(e))
        qt_inspect.modal_click("Cancel")

    QtCore.QTimer.singleShot(0, attempt)
    assert dialog.exec() == 0
    assert errors and "Apply" in errors[0]


def test_modal_click_without_a_modal_raises(qtbot):
    with pytest.raises(LookupError):
        qt_inspect.modal_click("OK")


def test_screenshot_returns_png(qtbot, window):
    assert qt_inspect.screenshot(None)[:8] == PNG_SIGNATURE


def test_screenshot_of_a_named_widget(qtbot, window):
    assert qt_inspect.screenshot("query")[:8] == PNG_SIGNATURE
    assert qt_inspect.screenshot("Debug Panel")[:8] == PNG_SIGNATURE


def test_unknown_target_raises(qtbot, window):
    with pytest.raises(LookupError, match="no-such-widget"):
        qt_inspect.screenshot("no-such-widget")


def test_screenshot_downscales_to_max_side(qtbot, window):
    window.resize(400, 300)
    qtbot.waitUntil(lambda: window.width() == 400)
    image = QtGui.QImage.fromData(qt_inspect.screenshot(None, max_side=100))
    assert (image.width(), image.height()) == (100, 75)


def test_screenshot_does_not_upscale_a_small_widget(qtbot, window):
    edit = window.findChild(QtWidgets.QLineEdit)
    image = QtGui.QImage.fromData(qt_inspect.screenshot("query"))
    assert image.width() == edit.grab().width()


def test_screenshot_rejects_a_non_positive_max_side(qtbot, window):
    with pytest.raises(ValueError):
        qt_inspect.screenshot(None, max_side=0)


def test_click_by_button_text(qtbot, window):
    clicked = []
    window.findChild(QtWidgets.QPushButton).clicked.connect(lambda: clicked.append(True))
    result = qt_inspect.click("Go")
    assert result["class"] == "QPushButton" and result["deferred"] is True
    assert clicked == []
    qtbot.waitUntil(lambda: clicked == [True])


def test_inputs_behind_a_modal_are_blocked(qtbot, window):
    clicked = []
    window.findChild(QtWidgets.QPushButton).clicked.connect(lambda: clicked.append(True))
    dialog = make_rename_dialog()
    errors = []

    def attempt():
        for action in (lambda: qt_inspect.click("Go"), lambda: qt_inspect.type_text("Search", "x"), lambda: qt_inspect.key("query", "A")):
            try:
                action()
            except LookupError as e:
                errors.append(str(e))
        qt_inspect.modal_click("Cancel")

    QtCore.QTimer.singleShot(0, attempt)
    assert dialog.exec() == 0
    assert len(errors) == 3 and all("blocked by modal 'Rename'" in error for error in errors)
    assert clicked == []
    assert window.findChild(QtWidgets.QLineEdit).text() == ""


def test_click_inside_the_modal_is_allowed(qtbot, window):
    dialog = make_rename_dialog()
    results = []
    QtCore.QTimer.singleShot(0, lambda: results.append(qt_inspect.click("OK")))
    assert dialog.exec() == 1
    assert results[0]["deferred"] is True


def test_modal_input_toggles_a_checkbox_after_replying(qtbot):
    dialog = make_rename_dialog()
    checkbox = QtWidgets.QCheckBox("Enabled")
    dialog.layout().insertRow(0, checkbox)
    seen = []

    def drive():
        seen.append(qt_inspect.modal_input("Enabled", "true"))
        seen.append(checkbox.isChecked())
        qt_inspect.modal_click("OK")

    QtCore.QTimer.singleShot(0, drive)
    assert dialog.exec() == 1
    assert seen[0]["deferred"] is True and seen[1] is False
    assert checkbox.isChecked()


@pytest.fixture
def twins(qtbot, window):
    layout = window.layout()
    for widget in (QtWidgets.QLabel("Same"), QtWidgets.QPushButton("Same"), QtWidgets.QPushButton("Twin"), QtWidgets.QPushButton("Twin")):
        layout.addWidget(widget)
    qtbot.waitUntil(lambda: all(w.isVisible() for w in window.findChildren(QtWidgets.QPushButton)))
    return window


def test_text_matching_several_widgets_is_ambiguous(qtbot, twins):
    with pytest.raises(qt_inspect.AmbiguousTargetError, match="QLabel.*QPushButton"):
        qt_inspect.get_property("Same", "text")
    with pytest.raises(qt_inspect.AmbiguousTargetError, match="Twin"):
        qt_inspect.click("Twin")


def test_click_prefers_a_button_over_a_label_with_the_same_text(qtbot, twins):
    assert qt_inspect.click("Same")["class"] == "QPushButton"


def test_type_text_and_key(qtbot, window):
    edit = window.findChild(QtWidgets.QLineEdit)
    qt_inspect.type_text("Search", "abc")
    assert edit.text() == "abc"
    qt_inspect.key("query", "Backspace")
    qtbot.waitUntil(lambda: edit.text() == "ab")


class Pad(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("pad")
        self.setFixedSize(120, 80)
        self.events = []

    def mousePressEvent(self, event):
        self.events.append(("press", event.button(), event.position().toPoint(), event.modifiers()))

    def mouseReleaseEvent(self, event):
        self.events.append(("release", event.button(), event.position().toPoint(), event.modifiers()))

    def mouseDoubleClickEvent(self, event):
        self.events.append(("double", event.button(), event.position().toPoint(), event.modifiers()))

    def mouseMoveEvent(self, event):
        self.events.append(("move", event.buttons(), event.position().toPoint(), event.modifiers()))

    def wheelEvent(self, event):
        self.events.append(("wheel", event.angleDelta(), event.position().toPoint(), event.modifiers()))


@pytest.fixture
def pad(qtbot, window):
    widget = Pad()
    widget.setMouseTracking(True)
    window.layout().addWidget(widget)
    qtbot.waitUntil(widget.isVisible)
    return widget


@pytest.fixture
def long_list(qtbot, window):
    widget = QtWidgets.QListWidget()
    widget.setObjectName("list")
    widget.setFixedHeight(60)
    widget.addItems([f"item {i}" for i in range(200)])
    widget.contextMenuRequested = []
    widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    widget.customContextMenuRequested.connect(widget.contextMenuRequested.append)
    window.layout().addWidget(widget)
    qtbot.waitUntil(widget.isVisible)
    return widget


def test_mouse_click_defaults_to_the_left_button_at_the_center(qtbot, pad):
    center = pad.rect().center()
    result = qt_inspect.mouse("pad")
    assert result["deferred"] is True and result["position"] == [center.x(), center.y()]
    assert pad.events == []
    qtbot.waitUntil(lambda: [e[0] for e in pad.events] == ["press", "release"])
    assert all(e[1] == QtCore.Qt.LeftButton and e[2] == center for e in pad.events)


def test_mouse_sends_each_kind_with_button_position_and_modifiers(qtbot, pad):
    qt_inspect.mouse("pad", kind="press", button="right", x=5, y=6, modifiers="Ctrl+Shift")
    qt_inspect.mouse("pad", kind="move", x=30, y=20)
    qt_inspect.mouse("pad", kind="release", button="right", x=30, y=20)
    qt_inspect.mouse("pad", kind="double", button="middle", x=10, y=10)
    qtbot.waitUntil(lambda: "double" in [e[0] for e in pad.events])
    press = next(e for e in pad.events if e[0] == "press")
    assert press[1] == QtCore.Qt.RightButton and press[2] == QtCore.QPoint(5, 6)
    assert press[3] == QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier
    assert any(e[0] == "move" and e[2] == QtCore.QPoint(30, 20) for e in pad.events)
    assert any(e[0] == "release" and e[1] == QtCore.Qt.RightButton and e[2] == QtCore.QPoint(30, 20) for e in pad.events)
    assert any(e[0] == "double" and e[1] == QtCore.Qt.MiddleButton for e in pad.events)


def test_mouse_right_click_opens_the_context_menu(qtbot, long_list):
    qt_inspect.mouse("list", button="right", x=20, y=10)
    qtbot.waitUntil(lambda: len(long_list.contextMenuRequested) == 1)
    assert long_list.contextMenuRequested[0] == long_list.viewport().mapFrom(long_list, QtCore.QPoint(20, 10))


def test_mouse_on_a_window_reaches_the_child_under_the_point(qtbot, window, long_list):
    inside_list = QtCore.QPoint(20, 10)
    point = long_list.mapTo(window, inside_list)
    result = qt_inspect.mouse("panel", button="right", x=point.x(), y=point.y())
    assert result["position"] == [point.x(), point.y()]
    qtbot.waitUntil(lambda: len(long_list.contextMenuRequested) == 1)
    assert long_list.contextMenuRequested[0] == long_list.viewport().mapFrom(long_list, inside_list)


def test_mouse_double_click_on_a_list_item(qtbot, long_list):
    activated = []
    long_list.itemDoubleClicked.connect(lambda item: activated.append(item.text()))
    rect = long_list.visualItemRect(long_list.item(1))
    point = long_list.viewport().mapTo(long_list, rect.center())
    qt_inspect.mouse("list", kind="double", x=point.x(), y=point.y())
    qtbot.waitUntil(lambda: activated == ["item 1"])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"kind": "drag"}, "kind"),
        ({"button": "fourth"}, "button"),
        ({"modifiers": "Hyper"}, "modifier"),
        ({"x": 500, "y": 5}, "outside"),
        ({"x": 5}, "both"),
    ],
)
def test_mouse_rejects_bad_arguments(qtbot, pad, kwargs, message):
    with pytest.raises(ValueError, match=message):
        qt_inspect.mouse("pad", **kwargs)


def test_wheel_scrolls_a_list(qtbot, long_list):
    bar = long_list.verticalScrollBar()
    assert bar.value() == 0
    result = qt_inspect.wheel("list", dy=-3)
    assert result["deferred"] is True
    qtbot.waitUntil(lambda: bar.value() > 0)


def test_wheel_over_a_child_that_ignores_it_scrolls_the_area_around_it(qtbot, window):
    area = QtWidgets.QScrollArea()
    area.setObjectName("area")
    area.setFixedHeight(80)
    content = QtWidgets.QWidget()
    QtWidgets.QVBoxLayout(content)
    for i in range(60):
        content.layout().addWidget(QtWidgets.QLabel(f"row {i}"))
    area.setWidget(content)
    window.layout().addWidget(area)
    qtbot.waitUntil(area.isVisible)
    bar = area.verticalScrollBar()
    label = content.layout().itemAt(1).widget()
    point = label.mapTo(area, label.rect().center())
    assert area.childAt(point) is label

    qt_inspect.wheel("area", dy=-3, x=point.x(), y=point.y())

    qtbot.waitUntil(lambda: bar.value() > 0)


def test_wheel_stops_at_the_child_that_takes_it(qtbot, window):
    holder = QtWidgets.QWidget()
    holder.setObjectName("holder")
    holder.wheels = []
    holder.wheelEvent = lambda event: holder.wheels.append(event.angleDelta())
    QtWidgets.QVBoxLayout(holder)
    inner = Pad()
    holder.layout().addWidget(inner)
    window.layout().addWidget(holder)
    qtbot.waitUntil(inner.isVisible)
    point = inner.mapTo(holder, inner.rect().center())

    qt_inspect.wheel("holder", dy=1, x=point.x(), y=point.y())

    qtbot.waitUntil(lambda: len(inner.events) == 1)
    assert holder.wheels == []


@pytest.fixture
def two_pads(qtbot, window):
    row = QtWidgets.QWidget()
    row.setObjectName("row")
    QtWidgets.QHBoxLayout(row)
    left, right = Pad(), Pad()
    left.setObjectName("left")
    right.setObjectName("right")
    for pad in (left, right):
        pad.setMouseTracking(True)
        row.layout().addWidget(pad)
    window.layout().addWidget(row)
    qtbot.waitUntil(right.isVisible)
    return row, left, right


def test_a_drag_across_calls_stays_with_the_pressed_child(qtbot, two_pads):
    row, left, right = two_pads
    start = left.mapTo(row, QtCore.QPoint(10, 10))
    end = right.mapTo(row, QtCore.QPoint(20, 30))

    qt_inspect.mouse("row", kind="press", x=start.x(), y=start.y())
    qt_inspect.mouse("row", kind="move", x=end.x(), y=end.y())
    qt_inspect.mouse("row", kind="release", x=end.x(), y=end.y())

    qtbot.waitUntil(lambda: "release" in [e[0] for e in left.events])
    outside = left.mapFrom(row, end)
    assert [(e[0], e[2]) for e in left.events] == [("press", QtCore.QPoint(10, 10)), ("move", outside), ("release", outside)]
    assert right.events == []


def test_wheel_sends_notches_position_and_modifiers(qtbot, pad):
    qt_inspect.wheel("pad", dy=2, dx=-1, x=7, y=8, modifiers="Ctrl")
    qtbot.waitUntil(lambda: len(pad.events) == 1)
    kind, delta, position, modifiers = pad.events[0]
    assert kind == "wheel" and delta == QtCore.QPoint(-120, 240) and position == QtCore.QPoint(7, 8)
    assert modifiers == QtCore.Qt.ControlModifier


def test_wheel_needs_a_delta(qtbot, pad):
    with pytest.raises(ValueError, match="dy or dx"):
        qt_inspect.wheel("pad")


def test_mouse_and_wheel_on_a_disabled_widget_raise(qtbot, pad):
    pad.setEnabled(False)
    with pytest.raises(ValueError, match="disabled"):
        qt_inspect.mouse("pad")
    with pytest.raises(ValueError, match="disabled"):
        qt_inspect.wheel("pad", dy=1)


def test_mouse_and_wheel_behind_a_modal_are_blocked(qtbot, pad):
    dialog = make_rename_dialog()
    errors = []

    def attempt():
        try:
            for action in (lambda: qt_inspect.mouse("pad"), lambda: qt_inspect.wheel("pad", dy=1)):
                try:
                    action()
                except LookupError as e:
                    errors.append(str(e))
        finally:
            dialog.reject()

    QtCore.QTimer.singleShot(0, attempt)
    assert dialog.exec() == 0
    assert len(errors) == 2 and all("blocked by modal 'Rename'" in error for error in errors)
    assert pad.events == []


def test_get_property_reads_qt_properties_and_getters(qtbot, window):
    window.findChild(QtWidgets.QLineEdit).setText("hello")
    assert qt_inspect.get_property("query", "text") == "hello"
    assert qt_inspect.get_property("query", "placeholderText") == "Search"
    assert qt_inspect.get_property("query", "isEnabled") is True
    assert qt_inspect.get_property("panel", "size") == [window.width(), window.height()]


def test_widget_tree_lists_children_to_the_given_depth(qtbot, window):
    tree = qt_inspect.widget_tree("panel", 1)
    assert len(tree) == 1 and tree[0]["object_name"] == "panel"
    children = tree[0]["children"]
    assert {"query", ""} <= {child["object_name"] for child in children}
    assert all(child["children"] == [] for child in children)
    assert any(node["object_name"] == "panel" for node in qt_inspect.widget_tree(None, 0))


def test_list_commands_filters_by_id(qtbot):
    command_id = sorted(CommandRegistry.instance().get_all_commands())[0]
    listed = qt_inspect.list_commands(command_id)
    assert command_id in [entry["id"] for entry in listed]
    assert all(command_id.lower() in entry["id"].lower() or command_id.lower() in entry["display"].lower() for entry in listed)


@pytest.fixture
def echo_command(monkeypatch):
    calls = []

    def echo(ctx, value):
        calls.append(value)

    meta = CommandMeta(path="debugtest.echo", display="Echo", func=echo, params=[CommandParam(name="value", value="", required=True)])
    meta.id = "debugtest.echo"
    monkeypatch.setitem(CommandRegistry.instance()._commands, meta.id, create_command_from_meta(meta))
    return calls


def test_run_command_starts_the_command_after_returning(qtbot, echo_command):
    assert qt_inspect.run_command("debugtest.echo", {"value": "hi"}) == {"started": True}
    assert echo_command == []
    qtbot.waitUntil(lambda: echo_command == ["hi"])


def test_run_command_without_a_required_arg_opens_the_options_dialog(qtbot, echo_command):
    seen = []

    def cancel_when_open():
        state = qt_inspect.modal_state()
        if state is None:
            QtCore.QTimer.singleShot(10, cancel_when_open)
            return
        seen.append(state)
        qt_inspect.modal_click("Cancel")

    QtCore.QTimer.singleShot(0, cancel_when_open)
    qt_inspect.run_command("debugtest.echo", {})
    qtbot.waitUntil(lambda: bool(seen) and qt_inspect.modal_state() is None)
    assert "Cancel" in [button["text"] for button in seen[0]["buttons"]]
    assert echo_command == []


def test_run_command_unknown_id_raises(qtbot):
    with pytest.raises(LookupError, match="no.such"):
        qt_inspect.run_command("no.such", {})


def test_get_state_is_empty_outside_a_viewer(qtbot):
    assert qt_inspect.get_state() == {}


def test_get_state_reads_the_main_window(qtbot, monkeypatch):
    class MainWindow(QtWidgets.QMainWindow):
        pass

    class Grid:
        def selected_paths(self):
            return ["C:/a.png"]

        def count(self):
            return 3

    monkeypatch.setitem(sys.modules, "wafer.app.viewer.mainwindow", types.SimpleNamespace(MainWindow=MainWindow))
    main = MainWindow()
    main.database_name = "sample"
    main.folder_view = types.SimpleNamespace(get_selected_paths=lambda: ["C:/"])
    main.query_coord = types.SimpleNamespace(capture=lambda: {"bars": [], "sort_by": "none"})
    main.grid_items = Grid()
    qtbot.addWidget(main)
    main.show()
    try:
        assert qt_inspect.get_state() == {"database": "sample", "paths": ["C:/"], "query": {"bars": [], "sort_by": "none"}, "selected": ["C:/a.png"], "count": 3}
    finally:
        main.close()
