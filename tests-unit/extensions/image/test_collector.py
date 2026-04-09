import py_compile
from unittest.mock import patch, MagicMock
import pytest

from extensions.image.collector import ExifCollectorPlugin


def test_compile():
    py_compile.compile("extensions/image/collector.py")


class TestExifCollectorFilter:
    @patch("extensions.image.collector.ExifCollectorPlugin._load_filter")
    def test_no_filter_keys_returns_all_keys(self, _mock):
        plugin = ExifCollectorPlugin()
        assert plugin._filter_keys == set()
        assert plugin._filter_mode == "blacklist"

    @patch("extensions.image.collector.ExifCollectorPlugin._load_filter")
    def test_blacklist_mode_excludes_keys(self, _mock_load, tmp_path):
        from PIL import Image

        with patch("extensions.image.exif_parser.ExifParser.parse_img") as mock_parse:
            mock_parse.return_value = {
                "width": 100, "height": 80, "orientation": 1, "aspect": 1.25,
                "exif": {"Make": "TestCam", "Model": "X1", "ExifOffset": "123"},
                "info_items": {"Software": "PIL"},
                "error": None,
            }
            img_path = str(tmp_path / "test.png")
            Image.new("RGB", (100, 80)).save(img_path)

            plugin = ExifCollectorPlugin()
            plugin._filter_mode = "blacklist"
            plugin._filter_keys = {"Make", "ExifOffset"}

            result = plugin.process(img_path, (1.0, 100))
            assert result.status is True
            meta = result.meta_info or {}
            assert "Make" not in meta
            assert "ExifOffset" not in meta
            assert "Model" in meta
            assert "Software" in meta

    @patch("extensions.image.collector.ExifCollectorPlugin._load_filter")
    def test_whitelist_mode_keeps_only_allowed_keys(self, _mock_load, tmp_path):
        from PIL import Image

        with patch("extensions.image.exif_parser.ExifParser.parse_img") as mock_parse:
            mock_parse.return_value = {
                "width": 100, "height": 80, "orientation": 1, "aspect": 1.25,
                "exif": {"Make": "TestCam", "Model": "X1", "ExifOffset": "123"},
                "info_items": {"Software": "PIL"},
                "error": None,
            }
            img_path = str(tmp_path / "test.png")
            Image.new("RGB", (100, 80)).save(img_path)

            plugin = ExifCollectorPlugin()
            plugin._filter_mode = "whitelist"
            plugin._filter_keys = {"Make", "Software"}

            result = plugin.process(img_path, (1.0, 100))
            assert result.status is True
            meta = result.meta_info or {}
            assert "Make" in meta
            assert "Software" in meta
            assert "Model" not in meta
            assert "ExifOffset" not in meta

    @patch("extensions.image.collector.ExifCollectorPlugin._load_filter")
    @patch("extensions.image.exif_parser.ExifParser.parse_img")
    def test_no_filter_keys_passes_all(self, mock_parse, _mock_load, tmp_path):
        from PIL import Image

        mock_parse.return_value = {
            "width": 100, "height": 80, "orientation": 1, "aspect": 1.25,
            "exif": {"Make": "TestCam", "Model": "X1"},
            "info_items": {"Software": "PIL"},
            "error": None,
        }
        img_path = str(tmp_path / "test.png")
        Image.new("RGB", (100, 80)).save(img_path)

        plugin = ExifCollectorPlugin()
        plugin._filter_mode = "blacklist"
        plugin._filter_keys = set()

        result = plugin.process(img_path, (1.0, 100))
        assert result.status is True
        meta = result.meta_info or {}
        assert "Make" in meta
        assert "Model" in meta
        assert "Software" in meta

    @patch("extensions.image.settings.read_filter_config", return_value=("blacklist", set()))
    def test_on_notify_reloads_filter(self, _mock_config):
        plugin = ExifCollectorPlugin()
        assert plugin._filter_keys == set()
        assert plugin._filter_mode == "blacklist"

        _mock_config.return_value = ("whitelist", {"NewKey"})
        plugin.on_notify()
        assert plugin._filter_mode == "whitelist"
        assert plugin._filter_keys == {"NewKey"}

    @patch("extensions.image.collector.ExifCollectorPlugin._load_filter")
    def test_process_bad_path_returns_failure(self, _mock):
        plugin = ExifCollectorPlugin()
        result = plugin.process("/nonexistent/path.jpg", (1.0, 100))
        assert result.status is False
