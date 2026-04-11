import os
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    lib_dir = str(tmp_path / "lib")
    import extensions.ffmpeg._downloader as dl

    monkeypatch.setattr(dl, "_LIB_DIR", lib_dir)
    monkeypatch.setattr(dl, "_FFPROBE_PATH", os.path.join(lib_dir, "ffprobe.exe"))
    monkeypatch.setattr(dl, "_FFMPEG_PATH", os.path.join(lib_dir, "ffmpeg.exe"))
    monkeypatch.setattr(dl, "_7ZR_PATH", os.path.join(lib_dir, "7zr.exe"))


class TestValidateUrl:
    def test_accepts_gyan_dev(self):
        from extensions.ffmpeg._downloader import _validate_url, _ALLOWED_HOSTS

        url = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1-essentials_build.7z"
        assert _validate_url(url, _ALLOWED_HOSTS) == url

    def test_rejects_http(self):
        from extensions.ffmpeg._downloader import _validate_url, _ALLOWED_HOSTS

        with pytest.raises(ValueError, match="Insecure URL scheme"):
            _validate_url("http://www.gyan.dev/foo", _ALLOWED_HOSTS)

    def test_rejects_untrusted_host(self):
        from extensions.ffmpeg._downloader import _validate_url, _ALLOWED_HOSTS

        with pytest.raises(ValueError, match="Untrusted host"):
            _validate_url("https://evil.com/ffmpeg.7z", _ALLOWED_HOSTS)


class TestSafeDownload:
    def test_atomic_success(self, tmp_path):
        from extensions.ffmpeg._downloader import _safe_download

        dest = str(tmp_path / "file.bin")

        def fake_retrieve(url, d):
            open(d, "w").close()

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve):
            _safe_download("https://example.com/f", dest)

        assert os.path.isfile(dest)
        assert not os.path.isfile(dest + ".tmp")

    def test_cleans_up_on_failure(self, tmp_path):
        from extensions.ffmpeg._downloader import _safe_download

        dest = str(tmp_path / "file.bin")

        def fake_retrieve(url, d):
            open(d, "w").close()
            raise ConnectionError("network down")

        with pytest.raises(ConnectionError):
            with patch("urllib.request.urlretrieve", side_effect=fake_retrieve):
                _safe_download("https://example.com/f", dest)

        assert not os.path.isfile(dest)
        assert not os.path.isfile(dest + ".tmp")


class TestValidateArchivePath:
    def test_safe_path(self, tmp_path):
        from extensions.ffmpeg._downloader import _validate_archive_path

        _validate_archive_path("ffmpeg-8.1/bin/ffprobe.exe", str(tmp_path))

    def test_traversal_rejected(self, tmp_path):
        from extensions.ffmpeg._downloader import _validate_archive_path

        with pytest.raises(ValueError, match="Path traversal"):
            _validate_archive_path("../../etc/passwd", str(tmp_path))


class TestGetPaths:
    def test_get_ffprobe_path_missing(self):
        from extensions.ffmpeg._downloader import get_ffprobe_path

        assert get_ffprobe_path() is None

    def test_get_ffprobe_path_exists(self, tmp_path):
        import extensions.ffmpeg._downloader as dl

        os.makedirs(dl._LIB_DIR, exist_ok=True)
        probe = os.path.join(dl._LIB_DIR, "ffprobe.exe")
        open(probe, "w").close()
        assert dl.get_ffprobe_path() == probe

    def test_get_ffmpeg_path_missing(self):
        from extensions.ffmpeg._downloader import get_ffmpeg_path

        assert get_ffmpeg_path() is None

    def test_get_ffmpeg_path_exists(self, tmp_path):
        import extensions.ffmpeg._downloader as dl

        os.makedirs(dl._LIB_DIR, exist_ok=True)
        ffmpeg = os.path.join(dl._LIB_DIR, "ffmpeg.exe")
        open(ffmpeg, "w").close()
        assert dl.get_ffmpeg_path() == ffmpeg


class TestEnsureFfmpeg:
    def test_already_present(self, tmp_path):
        import extensions.ffmpeg._downloader as dl

        os.makedirs(dl._LIB_DIR, exist_ok=True)
        open(dl._FFPROBE_PATH, "w").close()
        open(dl._FFMPEG_PATH, "w").close()
        assert dl.ensure_ffmpeg() is True

    def test_download_failure_raises(self, tmp_path):
        import extensions.ffmpeg._downloader as dl

        with patch.object(dl, "_safe_download", side_effect=ConnectionError("offline")):
            with pytest.raises(RuntimeError, match="Failed to acquire ffmpeg"):
                dl.ensure_ffmpeg()
