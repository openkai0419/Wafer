import py_compile

from PySide6 import QtWidgets


def test_compile():
    py_compile.compile('wafer/app/viewer/widgets/button_bar.py')


class TestIconButtonBar:
    def test_creates_buttons_from_configs(self, qtbot):
        from wafer.app.viewer.widgets.button_bar import IconButtonBar, IconButtonConfig
        bar = IconButtonBar(
            left_buttons=[IconButtonConfig('gear', 'Settings')],
            right_buttons=[IconButtonConfig('fullscreen', 'FS')],
        )
        assert len(bar.left_buttons) == 1
        assert len(bar.right_buttons) == 1

    def test_icons_not_null(self, qtbot):
        from wafer.app.viewer.widgets.button_bar import IconButtonBar, IconButtonConfig
        bar = IconButtonBar(
            left_buttons=[IconButtonConfig('gear', 'S'), IconButtonConfig('folder_plus', 'A')],
        )
        for btn, _, _ in bar._icon_keys:
            assert not btn.icon().isNull()

    def test_theme_change_refreshes_icons(self, qtbot):
        from wafer.app.viewer.widgets.button_bar import IconButtonBar, IconButtonConfig
        from wafer.core.color.theme import ThemeManager
        from wafer.core.color.theme_palette import DARK
        bar = IconButtonBar(left_buttons=[IconButtonConfig('gear', 'S')])
        bar._on_theme_changed(DARK)
        assert not bar.left_buttons[0].icon().isNull()
