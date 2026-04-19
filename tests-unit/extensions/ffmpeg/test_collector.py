import os
import pytest
from unittest.mock import patch, MagicMock

from extensions.ffmpeg.collector import FfmpegCollectorPlugin

SAMPLE_PROBE_RESULT = {
    "format": {
        "duration": "10.0",
        "bit_rate": "1000000",
        "format_name": "mov,mp4",
        "tags": {"encoder": "test"},
    },
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 640,
            "height": 480,
            "r_frame_rate": "24/1",
            "pix_fmt": "yuv420p",
        }
    ],
}


class TestFfmpegCollectorPlugin:
    def test_name_and_extensions(self):
        assert FfmpegCollectorPlugin.NAME == "ffmpeg"
        assert ".mp4" in FfmpegCollectorPlugin.EXTENSIONS
        assert ".mkv" in FfmpegCollectorPlugin.EXTENSIONS
        assert ".mpg" in FfmpegCollectorPlugin.EXTENSIONS
        assert ".mpeg" in FfmpegCollectorPlugin.EXTENSIONS
        assert ".mp3" in FfmpegCollectorPlugin.EXTENSIONS
        assert ".flac" in FfmpegCollectorPlugin.EXTENSIONS

    def test_priority(self):
        assert FfmpegCollectorPlugin.PRIORITY == 100
        assert FfmpegCollectorPlugin.DEFAULT_ENABLED is True

    def test_post_install_calls_ensure(self):
        with patch("extensions.ffmpeg._downloader.ensure_ffmpeg") as mock_ensure:
            FfmpegCollectorPlugin.post_install("/fake/dir")
            mock_ensure.assert_called_once()

    def test_resolve_ffprobe_no_download(self):
        plugin = FfmpegCollectorPlugin()
        with patch("extensions.ffmpeg._downloader.get_ffprobe_path", return_value=None):
            result = plugin._resolve_ffprobe()
        assert result is None

    @patch("extensions.ffmpeg.collector.FfmpegCollectorPlugin._resolve_ffprobe")
    def test_process_success(self, mock_resolve):
        mock_resolve.return_value = "/fake/ffprobe.exe"

        with patch("extensions.ffmpeg.parser.probe", return_value=SAMPLE_PROBE_RESULT):
            plugin = FfmpegCollectorPlugin()
            result = plugin.process("/test/video.mp4", (1.0, 1000))

        assert result.status is True
        assert result.source == "/test/video.mp4"
        assert result.meta_info["VideoCodec"] == "h264"
        assert result.meta_info["Width"] == "640"
        assert result.meta_info["Height"] == "480"
        assert result.meta_info["Duration"] == "10.0"
        assert abs(result.aspect - (640 / 480)) < 0.001

    @patch("extensions.ffmpeg.collector.FfmpegCollectorPlugin._resolve_ffprobe")
    def test_process_no_ffprobe(self, mock_resolve):
        mock_resolve.return_value = None

        plugin = FfmpegCollectorPlugin()
        result = plugin.process("/test/video.mp4", (1.0, 1000))
        assert result.status is False

    @patch("extensions.ffmpeg.collector.FfmpegCollectorPlugin._resolve_ffprobe")
    def test_process_probe_failure(self, mock_resolve):
        mock_resolve.return_value = "/fake/ffprobe.exe"

        with patch("extensions.ffmpeg.parser.probe", return_value=None):
            plugin = FfmpegCollectorPlugin()
            result = plugin.process("/test/video.mp4", (1.0, 1000))

        assert result.status is False

    def test_on_notify_resets_ffprobe_path(self):
        plugin = FfmpegCollectorPlugin()
        plugin._ffprobe_path = "/cached/path"
        plugin.on_notify()
        assert plugin._ffprobe_path is None
