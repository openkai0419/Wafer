from wafer.core.color.theme import ThemeManager
from wafer.core.color.theme_palette import DARK, LIGHT, ThemePalette


class TestThemeManager:

    def setup_method(self):
        ThemeManager.on_theme_changed._callbacks.clear()
        ThemeManager._instance = None

    def test_singleton(self, qtbot):
        a = ThemeManager.instance()
        b = ThemeManager.instance()
        assert a is b

    def test_default_palette(self, qtbot):
        tm = ThemeManager.instance()
        assert isinstance(tm.palette, ThemePalette)

    def test_set_dark(self, qtbot):
        tm = ThemeManager.instance()
        tm.set_dark()
        assert tm.is_dark
        assert tm.palette is DARK

    def test_set_light(self, qtbot):
        tm = ThemeManager.instance()
        tm.set_light()
        assert not tm.is_dark
        assert tm.palette is LIGHT

    def test_toggle(self, qtbot):
        tm = ThemeManager.instance()
        tm.set_dark()
        tm.toggle()
        assert tm.palette is LIGHT
        tm.toggle()
        assert tm.palette is DARK

    def test_on_theme_changed_fires(self, qtbot):
        tm = ThemeManager.instance()
        tm.set_dark()
        received = []
        tm.on_theme_changed.connect(lambda p: received.append(p))
        tm.set_light()
        assert received == [LIGHT]

    def test_no_signal_when_same(self, qtbot):
        tm = ThemeManager.instance()
        tm.set_dark()
        received = []
        tm.on_theme_changed.connect(lambda p: received.append(p))
        tm.set_dark()
        assert received == []

    def test_sync_system(self, qtbot):
        tm = ThemeManager.instance()
        tm.sync_system()
        assert isinstance(tm.palette, ThemePalette)
