import sys
import types

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from debug import inspect
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
    QtCore.QTimer.singleShot(0, lambda: (inspect.modal_input("name", "typed"), inspect.modal_click("OK")))
    assert dialog.exec() == 1 and dialog.findChild(QtWidgets.QLineEdit).text() == "typed"


def test_modal_input_finds_the_field_by_its_form_label(qtbot):
    dialog = make_rename_dialog()
    dialog.findChild(QtWidgets.QLineEdit).setText("old")
    QtCore.QTimer.singleShot(0, lambda: (inspect.modal_input("Name", "new"), inspect.modal_click("OK")))
    assert dialog.exec() == 1
    assert dialog.findChild(QtWidgets.QLineEdit).text() == "new"


def test_modal_state_describes_the_open_dialog(qtbot):
    dialog = make_rename_dialog()
    seen = []
    QtCore.QTimer.singleShot(0, lambda: (seen.append(inspect.modal_state()), inspect.modal_click("Cancel")))
    assert dialog.exec() == 0
    state = seen[0]
    assert state["title"] == "Rename"
    assert state["class"] == "QDialog"
    assert "Pick a new name" in state["labels"]
    assert {"object_name": "name", "class": "QLineEdit", "text": "", "placeholder": "New name"} in state["fields"]
    assert {"text": "OK", "enabled": True, "checked": None} in state["buttons"]


def test_modal_state_is_none_without_a_modal(qtbot):
    assert inspect.modal_state() is None


def test_modal_click_reports_an_unknown_button(qtbot):
    dialog = make_rename_dialog()
    errors = []

    def attempt():
        try:
            inspect.modal_click("Apply")
        except LookupError as e:
            errors.append(str(e))
        inspect.modal_click("Cancel")

    QtCore.QTimer.singleShot(0, attempt)
    assert dialog.exec() == 0
    assert errors and "Apply" in errors[0]


def test_modal_click_without_a_modal_raises(qtbot):
    with pytest.raises(LookupError):
        inspect.modal_click("OK")


def test_screenshot_returns_png(qtbot, window):
    assert inspect.screenshot(None)[:8] == PNG_SIGNATURE


def test_screenshot_of_a_named_widget(qtbot, window):
    assert inspect.screenshot("query")[:8] == PNG_SIGNATURE
    assert inspect.screenshot("Debug Panel")[:8] == PNG_SIGNATURE


def test_unknown_target_raises(qtbot, window):
    with pytest.raises(LookupError, match="no-such-widget"):
        inspect.screenshot("no-such-widget")


def test_screenshot_downscales_to_max_side(qtbot, window):
    window.resize(400, 300)
    qtbot.waitUntil(lambda: window.width() == 400)
    image = QtGui.QImage.fromData(inspect.screenshot(None, max_side=100))
    assert (image.width(), image.height()) == (100, 75)


def test_screenshot_does_not_upscale_a_small_widget(qtbot, window):
    edit = window.findChild(QtWidgets.QLineEdit)
    image = QtGui.QImage.fromData(inspect.screenshot("query"))
    assert image.width() == edit.grab().width()


def test_screenshot_rejects_a_non_positive_max_side(qtbot, window):
    with pytest.raises(ValueError):
        inspect.screenshot(None, max_side=0)


def test_click_by_button_text(qtbot, window):
    clicked = []
    window.findChild(QtWidgets.QPushButton).clicked.connect(lambda: clicked.append(True))
    result = inspect.click("Go")
    assert result["class"] == "QPushButton" and result["deferred"] is True
    assert clicked == []
    qtbot.waitUntil(lambda: clicked == [True])


def test_inputs_behind_a_modal_are_blocked(qtbot, window):
    clicked = []
    window.findChild(QtWidgets.QPushButton).clicked.connect(lambda: clicked.append(True))
    dialog = make_rename_dialog()
    errors = []

    def attempt():
        for action in (lambda: inspect.click("Go"), lambda: inspect.type_text("Search", "x"), lambda: inspect.key("query", "A")):
            try:
                action()
            except LookupError as e:
                errors.append(str(e))
        inspect.modal_click("Cancel")

    QtCore.QTimer.singleShot(0, attempt)
    assert dialog.exec() == 0
    assert len(errors) == 3 and all("blocked by modal 'Rename'" in error for error in errors)
    assert clicked == []
    assert window.findChild(QtWidgets.QLineEdit).text() == ""


def test_click_inside_the_modal_is_allowed(qtbot, window):
    dialog = make_rename_dialog()
    results = []
    QtCore.QTimer.singleShot(0, lambda: results.append(inspect.click("OK")))
    assert dialog.exec() == 1
    assert results[0]["deferred"] is True


def test_modal_input_toggles_a_checkbox_after_replying(qtbot):
    dialog = make_rename_dialog()
    checkbox = QtWidgets.QCheckBox("Enabled")
    dialog.layout().insertRow(0, checkbox)
    seen = []

    def drive():
        seen.append(inspect.modal_input("Enabled", "true"))
        seen.append(checkbox.isChecked())
        inspect.modal_click("OK")

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
    with pytest.raises(inspect.AmbiguousTargetError, match="QLabel.*QPushButton"):
        inspect.get_property("Same", "text")
    with pytest.raises(inspect.AmbiguousTargetError, match="Twin"):
        inspect.click("Twin")


def test_click_prefers_a_button_over_a_label_with_the_same_text(qtbot, twins):
    assert inspect.click("Same")["class"] == "QPushButton"


def test_type_text_and_key(qtbot, window):
    edit = window.findChild(QtWidgets.QLineEdit)
    inspect.type_text("Search", "abc")
    assert edit.text() == "abc"
    inspect.key("query", "Backspace")
    qtbot.waitUntil(lambda: edit.text() == "ab")


def test_get_property_reads_qt_properties_and_getters(qtbot, window):
    window.findChild(QtWidgets.QLineEdit).setText("hello")
    assert inspect.get_property("query", "text") == "hello"
    assert inspect.get_property("query", "placeholderText") == "Search"
    assert inspect.get_property("query", "isEnabled") is True
    assert inspect.get_property("panel", "size") == [window.width(), window.height()]


def test_widget_tree_lists_children_to_the_given_depth(qtbot, window):
    tree = inspect.widget_tree("panel", 1)
    assert len(tree) == 1 and tree[0]["object_name"] == "panel"
    children = tree[0]["children"]
    assert {"query", ""} <= {child["object_name"] for child in children}
    assert all(child["children"] == [] for child in children)
    assert any(node["object_name"] == "panel" for node in inspect.widget_tree(None, 0))


def test_list_commands_filters_by_id(qtbot):
    command_id = sorted(CommandRegistry.instance().get_all_commands())[0]
    listed = inspect.list_commands(command_id)
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
    assert inspect.run_command("debugtest.echo", {"value": "hi"}) == {"started": True}
    assert echo_command == []
    qtbot.waitUntil(lambda: echo_command == ["hi"])


def test_run_command_without_a_required_arg_opens_the_options_dialog(qtbot, echo_command):
    seen = []

    def cancel_when_open():
        state = inspect.modal_state()
        if state is None:
            QtCore.QTimer.singleShot(10, cancel_when_open)
            return
        seen.append(state)
        inspect.modal_click("Cancel")

    QtCore.QTimer.singleShot(0, cancel_when_open)
    inspect.run_command("debugtest.echo", {})
    qtbot.waitUntil(lambda: bool(seen) and inspect.modal_state() is None)
    assert "Cancel" in [button["text"] for button in seen[0]["buttons"]]
    assert echo_command == []


def test_run_command_unknown_id_raises(qtbot):
    with pytest.raises(LookupError, match="no.such"):
        inspect.run_command("no.such", {})


def test_get_state_is_empty_outside_a_viewer(qtbot):
    assert inspect.get_state() == {}


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
        assert inspect.get_state() == {"database": "sample", "paths": ["C:/"], "query": {"bars": [], "sort_by": "none"}, "selected": ["C:/a.png"], "count": 3}
    finally:
        main.close()
