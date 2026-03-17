import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _suppress_notifier(monkeypatch):
    monkeypatch.setattr(
        "wafer.core.commands.command.require.Notifier",
        type("FakeNotifier", (), {"warning": staticmethod(lambda msg: None)}),
    )


def _make_ctx(vw=None):
    ctx = MagicMock()
    ctx.get_instance = MagicMock(return_value=vw)
    return ctx


class TestToggleFitMode:
    def test_calls_toggle_fit_mode(self):
        from extensions.animated.viewer_commands import toggle_fit_mode
        vw = MagicMock()
        ctx = _make_ctx(vw)
        toggle_fit_mode(ctx)
        vw.toggle_fit_mode.assert_called_once()

    def test_noop_without_instance(self):
        from extensions.animated.viewer_commands import toggle_fit_mode
        ctx = _make_ctx(None)
        result = toggle_fit_mode(ctx)
        assert result is None


class TestAnimatedViewerCommands:
    def test_is_menu_group(self):
        from extensions.animated.viewer_commands import AnimatedViewerCommands
        from wafer.plugin import MenuGroup
        assert issubclass(AnimatedViewerCommands, MenuGroup)

    def test_name(self):
        from extensions.animated.viewer_commands import AnimatedViewerCommands
        assert AnimatedViewerCommands.NAME == "Animated Viewer"

    def test_priority(self):
        from extensions.animated.viewer_commands import AnimatedViewerCommands
        assert AnimatedViewerCommands.PRIORITY == 1200

    def test_commands_contains_toggle_fit_mode(self):
        from extensions.animated.viewer_commands import AnimatedViewerCommands
        cmds = AnimatedViewerCommands.commands()
        paths = [c.path for c in cmds if hasattr(c, 'path')]
        assert "aview.toggle_fit_mode" in paths

    def test_toggle_fit_mode_is_checkable(self):
        from extensions.animated.viewer_commands import AnimatedViewerCommands
        cmds = AnimatedViewerCommands.commands()
        fit_cmd = next(c for c in cmds if hasattr(c, 'path') and c.path == "aview.toggle_fit_mode")
        assert fit_cmd.checkable is True
