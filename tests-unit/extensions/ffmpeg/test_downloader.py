import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    lib_dir = str(tmp_path / "lib")
    import extensions.ffmpeg._downloader as dl

    monkeypatch.setattr(dl, "_LIB_DIR", lib_dir)
    monkeypatch.setattr(dl, "_FFPROBE_PATH", os.path.join(lib_dir, "ffprobe.exe"))
    monkeypatch.setattr(dl, "_FFMPEG_PATH", os.path.join(lib_dir, "ffmpeg.exe"))


class TestGetPaths:
    def test_get_ffprobe_path_missing(self):
        from extensions.ffmpeg._downloader import get_ffprobe_path

        assert get_ffprobe_path() is None

    def test_get_ffprobe_path_exists(self):
        import extensions.ffmpeg._downloader as dl

        os.makedirs(dl._LIB_DIR, exist_ok=True)
        open(dl._FFPROBE_PATH, "w").close()
        assert dl.get_ffprobe_path() == dl._FFPROBE_PATH

    def test_get_ffmpeg_path_missing(self):
        from extensions.ffmpeg._downloader import get_ffmpeg_path

        assert get_ffmpeg_path() is None

    def test_get_ffmpeg_path_exists(self):
        import extensions.ffmpeg._downloader as dl

        os.makedirs(dl._LIB_DIR, exist_ok=True)
        open(dl._FFMPEG_PATH, "w").close()
        assert dl.get_ffmpeg_path() == dl._FFMPEG_PATH


class TestEnsureFfmpeg:
    def test_already_present(self):
        import extensions.ffmpeg._downloader as dl

        os.makedirs(dl._LIB_DIR, exist_ok=True)
        open(dl._FFPROBE_PATH, "w").close()
        open(dl._FFMPEG_PATH, "w").close()
        assert dl.ensure_ffmpeg() is True

    def test_download_failure_raises(self):
        import extensions.ffmpeg._downloader as dl

        with patch.object(dl, "_fetch_expected_sha256", return_value="a" * 64), \
             patch.object(dl, "safe_download", side_effect=ConnectionError("offline")):
            with pytest.raises(RuntimeError, match="Failed to acquire ffmpeg"):
                dl.ensure_ffmpeg()
