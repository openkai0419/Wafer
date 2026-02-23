import py_compile
import pytest

from unittest.mock import patch, MagicMock
from source.io.grid.handler import grid_handler, VIEWER_THUMBNAIL_DEFAULT_SIZE


def test_compile():
    py_compile.compile('source/image_viewer/commands/setting_commands.py')


class TestViewerThumbnailDefaultSize:
    def setup_method(self):
        self._original = grid_handler.viewer_thumbnail_size

    def teardown_method(self):
        grid_handler.viewer_thumbnail_size = self._original

    def test_default_value(self):
        assert VIEWER_THUMBNAIL_DEFAULT_SIZE == 1024

    def test_grid_handler_initial_value(self):
        assert grid_handler.viewer_thumbnail_size == self._original

    def test_fallback_uses_viewer_thumbnail_size_when_no_size(self):
        grid_handler.viewer_thumbnail_size = 2048
        thumbnailer = MagicMock()
        thumbnailer.get_thumbnail.return_value = None
        grid_handler._thumbnailer = thumbnailer
        grid_handler._fallback_load('dummy.xyz', size=None)
        thumbnailer.get_thumbnail.assert_called_once_with('dummy.xyz', size=2048)

    def test_fallback_uses_explicit_size_when_provided(self):
        from PySide6 import QtCore
        grid_handler.viewer_thumbnail_size = 2048
        thumbnailer = MagicMock()
        thumbnailer.get_thumbnail.return_value = None
        grid_handler._thumbnailer = thumbnailer
        size = QtCore.QSize(400, 300)
        grid_handler._fallback_load('dummy.xyz', size=size)
        thumbnailer.get_thumbnail.assert_called_once_with('dummy.xyz', size=400)

    def test_restore_from_setting(self):
        with patch('source.image_viewer.commands.setting_commands.main_setting') as mock_setting:
            mock_setting.get.return_value = 4096
            from source.image_viewer.commands.setting_commands import _restore_viewer_thumbnail_size
            _restore_viewer_thumbnail_size()
            assert grid_handler.viewer_thumbnail_size == 4096

    def test_set_command_saves_value(self):
        with patch('source.image_viewer.commands.setting_commands.main_setting') as mock_setting, \
             patch('source.image_viewer.commands.setting_commands.QtWidgets') as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ('2048', True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from source.image_viewer.commands.setting_commands import set_viewer_thumbnail_default_size
            set_viewer_thumbnail_default_size(ctx)
            assert grid_handler.viewer_thumbnail_size == 2048
            mock_setting.save_important.assert_called_once_with('viewer/thumbnail_default_size', 2048)

    def test_set_command_clamps_minimum(self):
        with patch('source.image_viewer.commands.setting_commands.main_setting'), \
             patch('source.image_viewer.commands.setting_commands.QtWidgets') as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ('10', True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from source.image_viewer.commands.setting_commands import set_viewer_thumbnail_default_size
            set_viewer_thumbnail_default_size(ctx)
            assert grid_handler.viewer_thumbnail_size == 64

    def test_set_command_clamps_maximum(self):
        with patch('source.image_viewer.commands.setting_commands.main_setting'), \
             patch('source.image_viewer.commands.setting_commands.QtWidgets') as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ('99999', True)
            ctx = MagicMock()
            ctx.get.return_value = None
            from source.image_viewer.commands.setting_commands import set_viewer_thumbnail_default_size
            set_viewer_thumbnail_default_size(ctx)
            assert grid_handler.viewer_thumbnail_size == 16384

    def test_set_command_cancel_does_nothing(self):
        with patch('source.image_viewer.commands.setting_commands.main_setting') as mock_setting, \
             patch('source.image_viewer.commands.setting_commands.QtWidgets') as mock_qt:
            mock_qt.QInputDialog.getItem.return_value = ('', False)
            ctx = MagicMock()
            ctx.get.return_value = None
            grid_handler.viewer_thumbnail_size = 1024
            from source.image_viewer.commands.setting_commands import set_viewer_thumbnail_default_size
            set_viewer_thumbnail_default_size(ctx)
            assert grid_handler.viewer_thumbnail_size == 1024
            mock_setting.save_important.assert_not_called()
