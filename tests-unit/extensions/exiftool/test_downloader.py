import os
import pytest
from extensions.exiftool._downloader import (
    _validate_url,
    _validate_archive_path,
    get_exiftool_path,
    _EXIFTOOL_PATH,
)


class TestValidateUrl:
    def test_valid_https(self):
        url = "https://sourceforge.net/projects/exiftool/files/test.zip/download"
        assert _validate_url(url, ("sourceforge.net",)) == url

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="Insecure URL scheme"):
            _validate_url("http://sourceforge.net/test", ("sourceforge.net",))

    def test_untrusted_host(self):
        with pytest.raises(ValueError, match="Untrusted host"):
            _validate_url("https://evil.com/test", ("sourceforge.net",))

    def test_subdomain_allowed(self):
        url = "https://downloads.sourceforge.net/test"
        assert _validate_url(url, ("sourceforge.net",)) == url

    def test_empty_hostname(self):
        with pytest.raises(ValueError, match="no hostname"):
            _validate_url("https:///test", ("sourceforge.net",))


class TestValidateArchivePath:
    def test_normal_path(self, tmp_path):
        _validate_archive_path("exiftool.exe", str(tmp_path))

    def test_nested_path(self, tmp_path):
        _validate_archive_path("exiftool_files/lib/test.pm", str(tmp_path))

    def test_path_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_archive_path("../../../etc/passwd", str(tmp_path))

    def test_absolute_path_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_archive_path("C:\\Windows\\System32\\evil.exe", str(tmp_path))



class TestEnsureExiftool:
    def test_raises_on_download_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join(str(tmp_path), "nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Windows")
        monkeypatch.setattr(
            "extensions.exiftool._downloader._safe_download",
            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("network error")),
        )
        from extensions.exiftool._downloader import ensure_exiftool

        with pytest.raises(RuntimeError, match="Failed to acquire ExifTool"):
            ensure_exiftool()

    def test_raises_on_non_windows_without_system_exiftool(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join(str(tmp_path), "nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Linux")
        monkeypatch.setattr("shutil.which", lambda _: None)
        from extensions.exiftool._downloader import ensure_exiftool

        with pytest.raises(RuntimeError, match="Install exiftool via package manager"):
            ensure_exiftool()

    def test_non_windows_succeeds_with_system_exiftool(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join(str(tmp_path), "nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Linux")
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/exiftool")
        from extensions.exiftool._downloader import ensure_exiftool

        assert ensure_exiftool() is True

    def test_returns_true_when_exists(self, monkeypatch, tmp_path):
        exe = tmp_path / "exiftool.exe"
        exe.write_text("fake")
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            str(exe),
        )
        from extensions.exiftool._downloader import ensure_exiftool

        assert ensure_exiftool() is True
    def test_returns_none_when_not_installed(self, monkeypatch):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join("nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("shutil.which", lambda _: None)
        assert get_exiftool_path() is None

    def test_returns_lib_path_when_exists(self, tmp_path, monkeypatch):
        exe = tmp_path / "exiftool.exe"
        exe.write_text("fake")
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            str(exe),
        )
        assert get_exiftool_path() == str(exe)

    def test_falls_back_to_system(self, monkeypatch):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join("nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/exiftool")
        assert get_exiftool_path() == "/usr/bin/exiftool"
