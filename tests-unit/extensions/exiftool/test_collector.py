from unittest.mock import MagicMock, patch
import time
import threading
import pytest
from extensions.exiftool.collector import ExifToolCollectorPlugin, _IDLE_TIMEOUT


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
        assert plugin.match("video.mkv") is False
        assert plugin.match("audio.mp3") is False

    def test_match_apng(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin.match("anim.apng") is True

    def test_no_match_unknown(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin.match("file.xyz") is False

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

    def test_process_video_returns_meta(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = {
            "SourceFile": "test.mp4",
            "File:ImageWidth": 1920,
            "File:ImageHeight": 1080,
            "QuickTime:Make": "Apple",
        }
        plugin._process = mock_proc
        result = plugin.process("test.mp4", (1000.0, 500))
        assert result.status is True
        assert result.meta_info["QuickTime:Make"] == "Apple"
        assert result.aspect == pytest.approx(1920 / 1080)

    def test_process_audio_returns_meta(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = {
            "SourceFile": "test.mp3",
            "ID3:Artist": "Test",
        }
        plugin._process = mock_proc
        result = plugin.process("test.mp3", (1000.0, 500))
        assert result.status is True
        assert result.aspect is None

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
        mock_timer = MagicMock()
        plugin._idle_timer = mock_timer
        plugin.on_notify()
        mock_proc.stop.assert_called_once()
        assert plugin._process is None
        assert plugin._exe_path is None
        mock_timer.cancel.assert_called_once()
        assert plugin._idle_timer is None

    def test_blacklist_filter_excludes_keys(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = {
            "SourceFile": "test.jpg",
            "File:ImageWidth": 4000,
            "File:ImageHeight": 3000,
            "IFD0:Make": "Canon",
            "IFD0:Model": "EOS R5",
        }
        plugin._process = mock_proc
        plugin._filter_mode = "blacklist"
        plugin._filter_keys = {"IFD0:Make"}
        result = plugin.process("test.jpg", (1000.0, 500))
        assert result.status is True
        assert "IFD0:Make" not in result.meta_info
        assert "IFD0:Model" in result.meta_info

    def test_whitelist_filter_keeps_only_selected(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = {
            "SourceFile": "test.jpg",
            "File:ImageWidth": 4000,
            "File:ImageHeight": 3000,
            "IFD0:Make": "Canon",
            "IFD0:Model": "EOS R5",
            "ExifIFD:ISO": "100",
        }
        plugin._process = mock_proc
        plugin._filter_mode = "whitelist"
        plugin._filter_keys = {"IFD0:Make"}
        result = plugin.process("test.jpg", (1000.0, 500))
        assert result.status is True
        assert result.meta_info == {"IFD0:Make": "Canon"}

    def test_empty_filter_keys_passes_all(self):
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
        plugin._filter_mode = "blacklist"
        plugin._filter_keys = set()
        result = plugin.process("test.jpg", (1000.0, 500))
        assert result.status is True
        assert "IFD0:Make" in result.meta_info

    @patch("extensions.exiftool.settings.read_filter_config", return_value=("whitelist", {"IFD0:Model"}))
    def test_on_notify_reloads_filter(self, _mock_config):
        plugin = ExifToolCollectorPlugin()
        assert plugin._filter_mode == "whitelist"
        assert plugin._filter_keys == {"IFD0:Model"}


class TestExifToolCooldown:
    def test_touch_starts_idle_timer(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin._idle_timer is None
        plugin._touch()
        assert plugin._idle_timer is not None
        assert plugin._idle_timer.is_alive()
        plugin._idle_timer.cancel()

    def test_touch_resets_last_used(self):
        plugin = ExifToolCollectorPlugin()
        assert plugin._last_used == 0.0
        plugin._touch()
        assert plugin._last_used > 0.0
        plugin._idle_timer.cancel()

    def test_touch_replaces_previous_timer(self):
        plugin = ExifToolCollectorPlugin()
        plugin._touch()
        first_timer = plugin._idle_timer
        plugin._touch()
        second_timer = plugin._idle_timer
        assert first_timer is not second_timer
        assert not first_timer.is_alive()
        assert second_timer.is_alive()
        second_timer.cancel()

    def test_check_idle_stops_process_when_expired(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        plugin._process = mock_proc
        plugin._last_used = time.monotonic() - _IDLE_TIMEOUT - 1
        plugin._check_idle()
        mock_proc.stop.assert_called_once()
        assert plugin._process is None

    def test_check_idle_keeps_process_when_recent(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        plugin._process = mock_proc
        plugin._last_used = time.monotonic()
        plugin._check_idle()
        mock_proc.stop.assert_not_called()
        assert plugin._process is mock_proc

    def test_check_idle_noop_when_no_process(self):
        plugin = ExifToolCollectorPlugin()
        plugin._last_used = time.monotonic() - _IDLE_TIMEOUT - 1
        plugin._check_idle()
        assert plugin._process is None

    def test_process_calls_touch(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        mock_proc.alive = True
        mock_proc.query.return_value = {
            "SourceFile": "test.jpg",
            "File:ImageWidth": 100,
            "File:ImageHeight": 100,
        }
        plugin._process = mock_proc
        assert plugin._last_used == 0.0
        plugin.process("test.jpg", (1000.0, 500))
        assert plugin._last_used > 0.0
        assert plugin._idle_timer is not None
        plugin._idle_timer.cancel()

    def test_restart_after_idle_shutdown(self):
        plugin = ExifToolCollectorPlugin()
        mock_proc = MagicMock()
        plugin._process = mock_proc
        plugin._last_used = time.monotonic() - _IDLE_TIMEOUT - 1
        plugin._check_idle()
        assert plugin._process is None
        mock_proc.stop.assert_called_once()

        new_proc = MagicMock()
        new_proc.alive = True
        with patch("extensions.exiftool.parser.ExifToolProcess", return_value=new_proc):
            plugin._exe_path = "/fake/exiftool"
            result = plugin._ensure_process()
        assert result is new_proc
        assert plugin._process is new_proc
        new_proc.start.assert_called_once()
