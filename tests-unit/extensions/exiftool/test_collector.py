from unittest.mock import MagicMock, patch
import pytest
from extensions.exiftool.collector import ExifToolCollectorPlugin


class TestExifToolCollector:
    def test_attributes(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin.NAME == "exiftool"
        assert ".jpg" in plugin.EXTENSIONS
        assert ".cr2" in plugin.EXTENSIONS
        assert plugin.DEFAULT_ENABLED is True

    def test_match_jpg(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin.match("photo.jpg") is True
        assert plugin.match("photo.JPG") is True

    def test_match_raw(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin.match("photo.cr2") is True
        assert plugin.match("photo.nef") is True

    def test_no_match_video(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin.match("video.mp4") is False

    def test_post_install_calls_ensure(self):
        with patch("extensions.exiftool._downloader.ensure_exiftool") as mock_ensure:
            ExifToolCollectorPlugin.post_install("/fake/dir")
            mock_ensure.assert_called_once()

    def test_process_success(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = {
            "SourceFile": "test.jpg",
            "File:ImageWidth": 4000,
            "File:ImageHeight": 3000,
            "IFD0:Make": "Canon",
        }
        plugin._process = mock_proc
        result = plugin.process("test.jpg", (1000.0, 500))
        assert result.status is True
        assert result.meta_info["IFD0:Make"] == "Canon"
        assert result.aspect == pytest.approx(4000 / 3000)

    def test_process_query_returns_none(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = None
        plugin._process = mock_proc
        result = plugin.process("bad.jpg", (1000.0, 0))
        assert result.status is False

    def test_process_no_exiftool(self):
        plugin = ExifToolCollectorPlugin()
        with patch.object(plugin, "_ensure_process", return_value=None):
            result = plugin.process("test.jpg", (1000.0, 500))
        assert result.status is False

    def test_ensure_process_no_download(self):
        plugin = ExifToolCollectorPlugin()
        with patch("extensions.exiftool._downloader.get_exiftool_path", return_value=None):
            result = plugin._ensure_process()
        assert result is None

    def test_on_notify_stops_process(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        plugin._process = mock_proc
        plugin.on_notify()
        mock_proc.stop.assert_called_once()
        assert plugin._process is None
        assert plugin._exe_path is None
