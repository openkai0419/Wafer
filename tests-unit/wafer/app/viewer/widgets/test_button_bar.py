class TestIconButtonBar:
    def test_theme_change_refreshes_icons(self, qtbot):
        from wafer.app.viewer.widgets.button_bar import IconButtonBar, IconButtonConfig
        from wafer.qt.theme import ThemeManager
        from wafer.qt.palette import DARK

        bar = IconButtonBar(
            left_buttons=[IconButtonConfig("gear", "S"), IconButtonConfig("folder_plus", "A")],
        )
        for btn, _, _ in bar._icon_keys:
            assert not btn.icon().isNull()
        bar._on_theme_changed(DARK)
        for btn, _, _ in bar._icon_keys:
            assert not btn.icon().isNull()
