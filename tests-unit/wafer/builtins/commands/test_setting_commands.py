import py_compile
import pytest

from unittest.mock import patch, MagicMock
from wafer.plugin.grid.handler import grid_resolver, VIEWER_THUMBNAIL_DEFAULT_SIZE


def test_compile():
    py_compile.compile("wafer/builtins/commands/setting_commands.py")


class TestViewerThumbnailDefaultSize:
    def setup_method(self):
        self._original = grid_resolver.thumbnail_size

    def teardown_method(self):
        grid_resolver.thumbnail_size = self._original

    def test_default_value(self):
        assert VIEWER_THUMBNAIL_DEFAULT_SIZE == 512

    def test_grid_handler_initial_value(self):
        assert grid_resolver.thumbnail_size == self._original

    def test_fallback_uses_thumbnail_size_when_no_size(self):
        from wafer.plugin.imageloader.handler import image_loader_resolver

        grid_resolver.thumbnail_size = 2048
        thumbnailer = MagicMock()
        thumbnailer.get_thumbnail.return_value = None
        instance = image_loader_resolver.registry.instance("system_thumbnail")
        orig = instance._thumbnailer
        instance._thumbnailer = thumbnailer
        try:
            instance.load_pil("dummy.xyz", size=2048)
            thumbnailer.get_thumbnail.assert_called_once_with("dummy.xyz", size=2048)
        finally:
            instance._thumbnailer = orig

    def test_fallback_uses_explicit_size_when_provided(self):
        from wafer.plugin.imageloader.handler import image_loader_resolver

        grid_resolver.thumbnail_size = 2048
        thumbnailer = MagicMock()
        thumbnailer.get_thumbnail.return_value = None
        instance = image_loader_resolver.registry.instance("system_thumbnail")
        orig = instance._thumbnailer
        instance._thumbnailer = thumbnailer
        try:
            instance.load_pil("dummy.xyz", size=400)
            thumbnailer.get_thumbnail.assert_called_once_with("dummy.xyz", size=400)
        finally:
            instance._thumbnailer = orig

    def test_restore_from_setting(self):
        with patch("wafer.builtins.commands.setting_commands.app_settings") as mock_setting:
            mock_setting.get.return_value = 4096
            from wafer.builtins.commands.setting_commands import _restore_thumbnail_size

            _restore_thumbnail_size()
            assert grid_resolver.thumbnail_size == 4096

    def test_set_command_saves_value(self):
        with patch("wafer.builtins.commands.setting_commands.app_settings") as mock_setting, patch("wafer.builtins.commands.setting_commands.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("2048", True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from wafer.builtins.commands.setting_commands import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 2048
            mock_setting.save_immediate.assert_called_once_with("viewer/thumbnail_default_size", 2048)

    def test_set_command_clamps_minimum(self):
        with patch("wafer.builtins.commands.setting_commands.app_settings"), patch("wafer.builtins.commands.setting_commands.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("10", True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from wafer.builtins.commands.setting_commands import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 64

    def test_set_command_clamps_maximum(self):
        with patch("wafer.builtins.commands.setting_commands.app_settings"), patch("wafer.builtins.commands.setting_commands.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("99999", True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from wafer.builtins.commands.setting_commands import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 16384

    def test_set_command_cancel_does_nothing(self):
        with patch("wafer.builtins.commands.setting_commands.app_settings") as mock_setting, patch("wafer.builtins.commands.setting_commands.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("", False)
            ctx = MagicMock()
            ctx.get.return_value = None
            grid_resolver.thumbnail_size = 1024
            from wafer.builtins.commands.setting_commands import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 1024
            mock_setting.save_immediate.assert_not_called()
