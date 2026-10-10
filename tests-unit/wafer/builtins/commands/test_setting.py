from unittest.mock import patch, MagicMock
from wafer.plugin.grid.handler import grid_resolver


class TestViewerThumbnailDefaultSize:
    def setup_method(self):
        self._original = grid_resolver.thumbnail_size

    def teardown_method(self):
        grid_resolver.thumbnail_size = self._original

    def test_restore_from_setting(self):
        with patch("wafer.builtins.commands.setting.app_settings") as mock_setting:
            mock_setting.get.return_value = 4096
            from wafer.builtins.commands.setting import _restore_thumbnail_size

            _restore_thumbnail_size()
            assert grid_resolver.thumbnail_size == 4096

    def test_set_command_saves_value(self):
        with patch("wafer.builtins.commands.setting.app_settings") as mock_setting, patch("wafer.builtins.commands.setting.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("2048", True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from wafer.builtins.commands.setting import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 2048
            mock_setting.save_immediate.assert_called_once_with("viewer/thumbnail_default_size", 2048)

    def test_set_command_clamps_minimum(self):
        with patch("wafer.builtins.commands.setting.app_settings"), patch("wafer.builtins.commands.setting.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("10", True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from wafer.builtins.commands.setting import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 64

    def test_set_command_clamps_maximum(self):
        with patch("wafer.builtins.commands.setting.app_settings"), patch("wafer.builtins.commands.setting.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("99999", True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from wafer.builtins.commands.setting import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 16384

    def test_set_command_cancel_does_nothing(self):
        with patch("wafer.builtins.commands.setting.app_settings") as mock_setting, patch("wafer.builtins.commands.setting.QtWidgets") as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ("", False)
            ctx = MagicMock()
            ctx.get.return_value = None
            grid_resolver.thumbnail_size = 1024
            from wafer.builtins.commands.setting import set_viewer_thumbnail_default_size

            set_viewer_thumbnail_default_size(ctx)
            assert grid_resolver.thumbnail_size == 1024
            mock_setting.save_immediate.assert_not_called()
