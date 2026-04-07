import py_compile


def test_compile():
    py_compile.compile("wafer/app/viewer/widgets/combo_with_buttons.py")


class TestComboBoxWithButtons:
    def test_add_remove_buttons_have_icons(self, qtbot):
        from wafer.app.viewer.widgets.combo_with_buttons import ComboBoxWithButtons

        w = ComboBoxWithButtons()
        assert not w.button_add.icon().isNull()
        assert not w.button_remove.icon().isNull()

    def test_no_button_text(self, qtbot):
        from wafer.app.viewer.widgets.combo_with_buttons import ComboBoxWithButtons

        w = ComboBoxWithButtons()
        assert w.button_add.text() == ""
        assert w.button_remove.text() == ""

    def test_theme_change_refreshes_icons(self, qtbot):
        from wafer.app.viewer.widgets.combo_with_buttons import ComboBoxWithButtons
        from wafer.core.color.theme_palette import LIGHT

        w = ComboBoxWithButtons()
        w._on_theme_changed(LIGHT)
        assert not w.button_add.icon().isNull()
        assert not w.button_remove.icon().isNull()
