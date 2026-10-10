import io
import os
from unittest.mock import patch

import pytest

from wafer.core.common import downloader as common


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

        with patch.object(dl, "_fetch_expected_sha256", return_value="a" * 64), patch.object(dl, "safe_download", side_effect=ConnectionError("offline")):
            with pytest.raises(RuntimeError, match="Failed to acquire ffmpeg"):
                dl.ensure_ffmpeg()


class _Resp:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_urlopen(monkeypatch, payload: bytes):
    monkeypatch.setattr(common.urllib.request, "urlopen", lambda req, timeout=None: _Resp(payload))


class TestFetchExpectedSha256:
    def test_parses_companion_file(self, monkeypatch):
        import extensions.ffmpeg._downloader as dl

        _patch_urlopen(monkeypatch, b"23ad8969fbe701d44e6e7e2b97c5fae4a71224fc33a2560a9034e5110d029d15  ffmpeg-release-essentials.7z\n")
        assert dl._fetch_expected_sha256() == "23ad8969fbe701d44e6e7e2b97c5fae4a71224fc33a2560a9034e5110d029d15"

    def test_lowercases_hex(self, monkeypatch):
        import extensions.ffmpeg._downloader as dl

        _patch_urlopen(monkeypatch, b"ABCDEF" + b"0" * 58 + b"\n")
        assert dl._fetch_expected_sha256() == "abcdef" + "0" * 58

    def test_rejects_garbage(self, monkeypatch):
        import extensions.ffmpeg._downloader as dl

        _patch_urlopen(monkeypatch, b"<html>not a checksum</html>")
        with pytest.raises(RuntimeError, match="Unexpected .sha256 format"):
            dl._fetch_expected_sha256()

    def test_rejects_oversized(self, monkeypatch):
        import extensions.ffmpeg._downloader as dl

        _patch_urlopen(monkeypatch, b"a" * (dl._MAX_SHA256_RESPONSE + 10))
        with pytest.raises(RuntimeError, match="too large"):
            dl._fetch_expected_sha256()
