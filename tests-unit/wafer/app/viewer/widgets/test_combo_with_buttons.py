class TestComboBoxWithButtons:
    def test_theme_change_refreshes_icons(self, qtbot):
        from wafer.app.viewer.widgets.combo_with_buttons import ComboBoxWithButtons
        from wafer.qt.palette import LIGHT

        w = ComboBoxWithButtons()
        w._on_theme_changed(LIGHT)
        assert not w.button_add.icon().isNull()
        assert not w.button_remove.icon().isNull()
