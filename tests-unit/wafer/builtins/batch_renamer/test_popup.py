from PySide6 import QtWidgets

from wafer.plugin.rename.base import DropdownButton, ToggleButton, RenameConfigWidget
from wafer.builtins.batch_renamer.popup import ColumnSettingsPopup
from wafer.builtins.batch_renamer.engine import RenameColumn
from wafer.builtins.rename_sources import (
    NameSource,
    FixedSource,
    ExtSource,
    SequentialSource,
)


class TestToggleButton:
    def test_initial_unchecked(self, qtbot):
        btn = ToggleButton("Trim")
        qtbot.addWidget(btn)
        assert not btn.isChecked()
        assert "\u25b8" in btn.text()

    def test_initial_checked(self, qtbot):
        btn = ToggleButton("Trim", True)
        qtbot.addWidget(btn)
        assert btn.isChecked()
        assert "\u25be" in btn.text()

    def test_toggle_emits_and_updates(self, qtbot):
        btn = ToggleButton("Test")
        qtbot.addWidget(btn)
        received = []
        btn.toggled.connect(received.append)
        btn.setChecked(True)
        assert received == [True]
        assert "\u25be" in btn.text()


class TestDropdownButton:
    def test_initial_value(self, qtbot):
        btn = DropdownButton("Key", ["a", "b", "c"], "b")
        qtbot.addWidget(btn)
        assert btn.value() == "b"
        assert "b" in btn.text()

    def test_default_first_choice(self, qtbot):
        btn = DropdownButton("Key", ["x", "y"])
        qtbot.addWidget(btn)
        assert btn.value() == "x"

    def test_empty_choices(self, qtbot):
        btn = DropdownButton("Key", [])
        qtbot.addWidget(btn)
        assert btn.value() == ""

    def test_pick_emits_signal(self, qtbot):
        btn = DropdownButton("Key", ["a", "b", "c"], "a")
        qtbot.addWidget(btn)
        received = []
        btn.value_changed.connect(received.append)
        btn._pick("c")
        assert received == ["c"]
        assert btn.value() == "c"


class TestColumnSettingsPopup:
    def test_resize_and_clamp(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        popup.move(0, 0)
        popup.adjustSize()
        popup._resize_and_clamp()
        geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
        assert popup.x() >= geo.left()
        assert popup.y() >= geo.top()

    def test_ext_column_has_enabled_checkbox(self, qtbot):
        col = RenameColumn(ExtSource())
        popup = ColumnSettingsPopup(col, is_ext=True)
        qtbot.addWidget(popup)
        checkboxes = popup.findChildren(QtWidgets.QCheckBox)
        enabled_cb = [cb for cb in checkboxes if "Include" in cb.text()]
        assert len(enabled_cb) == 1
        assert enabled_cb[0].isChecked()
        enabled_cb[0].setChecked(False)
        assert not col.enabled

    def test_source_config_widget_embedded(self, qtbot):
        src = FixedSource("hello")
        col = RenameColumn(src)
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        config_widgets = popup.findChildren(RenameConfigWidget)
        assert len(config_widgets) == 1

    def test_sequential_resequence_signal(self, qtbot):
        src = SequentialSource()
        col = RenameColumn(src)
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        received = []
        popup.resequence_requested.connect(lambda: received.append(True))
        config_w = popup.findChild(RenameConfigWidget)
        config_w.resequence_requested.emit()
        assert len(received) == 1


class TestPostProcessToggles:
    def _popup(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        toggles = {b.text().split(" ", 1)[-1]: b for b in popup.findChildren(ToggleButton)}
        return col.post, popup, toggles

    def test_reenabling_replace_applies_the_shown_values(self, qtbot):
        post, popup, toggles = self._popup(qtbot)
        toggles["Replace"].setChecked(True)
        find_e, repl_e = [e for e in popup.findChildren(QtWidgets.QLineEdit) if e.placeholderText() in ("Find", "Replace")]
        find_e.setText("_")
        repl_e.setText("-")
        toggles["Replace"].setChecked(False)
        assert (post.find, post.replace) == ("", "")
        toggles["Replace"].setChecked(True)
        assert (post.find, post.replace) == ("_", "-")

    def test_reenabling_insert_applies_the_shown_values(self, qtbot):
        post, popup, toggles = self._popup(qtbot)
        toggles["Insert"].setChecked(True)
        prefix_e = next(e for e in popup.findChildren(QtWidgets.QLineEdit) if e.placeholderText() == "prefix")
        prefix_e.setText("x_")
        toggles["Insert"].setChecked(False)
        toggles["Insert"].setChecked(True)
        assert post.prefix == "x_"

    def test_trim_end_zero_keeps_the_whole_name(self, qtbot):
        post, popup, toggles = self._popup(qtbot)
        toggles["Trim"].setChecked(True)
        start_s, end_s = popup.findChildren(QtWidgets.QSpinBox)[:2]
        start_s.setValue(1)
        end_s.setValue(2)
        end_s.setValue(0)
        assert post.apply("abcdef") == "bcdef"
        toggles["Trim"].setChecked(False)
        toggles["Trim"].setChecked(True)
        assert (post.trim_start, post.trim_end) == (1, None)
