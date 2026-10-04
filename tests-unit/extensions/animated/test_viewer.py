from extensions.animated.viewer import AnimatedViewerPlugin


def _make_plugin(widget=None):
    plugin = AnimatedViewerPlugin.__new__(AnimatedViewerPlugin)
    plugin.widget = widget
    return plugin


class TestAnimatedViewerPluginState:
    def test_save_ui_state(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        plugin.widget.cover_mode = True
        state = plugin.save_ui_state()
        assert state == {"fit_mode": True}

    def test_restore_ui_state(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        plugin.restore_ui_state({"fit_mode": True})
        plugin.widget.set_cover_mode.assert_called_once_with(True)

    def test_restore_ui_state_default(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        plugin.restore_ui_state({})
        plugin.widget.set_cover_mode.assert_called_once_with(False)
