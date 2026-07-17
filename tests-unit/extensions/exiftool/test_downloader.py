import io
import os

import pytest

from extensions.exiftool._downloader import (
    _fetch_latest_version,
    get_exiftool_path,
    _VERSION_PATTERN,
)


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
    from wafer.utils import downloader as dl
    monkeypatch.setattr(dl.urllib.request, "urlopen", lambda req, timeout=None: _Resp(payload))


class TestFetchLatestVersion:
    def test_valid_version(self, monkeypatch):
        _patch_urlopen(monkeypatch, b"13.55\n")
        assert _fetch_latest_version() == "13.55"

    def test_rejects_invalid_format(self, monkeypatch):
        _patch_urlopen(monkeypatch, b"<html>hack</html>")
        with pytest.raises(RuntimeError, match="Unexpected version format"):
            _fetch_latest_version()

    def test_rejects_oversized_response(self, monkeypatch):
        _patch_urlopen(monkeypatch, b"x" * 100)
        with pytest.raises(RuntimeError, match="too large"):
            _fetch_latest_version()

    @pytest.mark.parametrize("ver", ["13.55", "12.0", "99.99"])
    def test_version_pattern_valid(self, ver):
        assert _VERSION_PATTERN.match(ver)

    @pytest.mark.parametrize("ver", ["13", "13.55.1", "abc", "13.55beta", ""])
    def test_version_pattern_invalid(self, ver):
        assert not _VERSION_PATTERN.match(ver)


class TestEnsureExiftool:
    def test_raises_on_download_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join(str(tmp_path), "nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PL",
            os.path.join(str(tmp_path), "nonexistent", "exiftool_files", "exiftool.pl"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Windows")
        monkeypatch.setattr(
            "extensions.exiftool._downloader._fetch_latest_version",
            lambda: "13.55",
        )
        monkeypatch.setattr(
            "extensions.exiftool._downloader._fetch_expected_sha256",
            lambda v: "a" * 64,
        )
        monkeypatch.setattr(
            "extensions.exiftool._downloader.safe_download",
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
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PL",
            os.path.join(str(tmp_path), "nonexistent", "exiftool_files", "exiftool.pl"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Linux")
        monkeypatch.setattr("extensions.exiftool._downloader.shutil.which", lambda _: None)
        from extensions.exiftool._downloader import ensure_exiftool

        with pytest.raises(RuntimeError, match="Install exiftool via package manager"):
            ensure_exiftool()

    def test_non_windows_succeeds_with_system_exiftool(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join(str(tmp_path), "nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PL",
            os.path.join(str(tmp_path), "nonexistent", "exiftool_files", "exiftool.pl"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Linux")
        monkeypatch.setattr("extensions.exiftool._downloader.shutil.which", lambda _: "/usr/bin/exiftool")
        from extensions.exiftool._downloader import ensure_exiftool

        assert ensure_exiftool() is True

    def test_returns_true_when_install_valid(self, monkeypatch, tmp_path):
        exe = tmp_path / "exiftool.exe"
        exe.write_text("fake")
        pl_dir = tmp_path / "exiftool_files"
        pl_dir.mkdir()
        pl = pl_dir / "exiftool.pl"
        pl.write_text("fake")
        monkeypatch.setattr("extensions.exiftool._downloader._EXIFTOOL_PATH", str(exe))
        monkeypatch.setattr("extensions.exiftool._downloader._EXIFTOOL_PL", str(pl))
        from extensions.exiftool._downloader import ensure_exiftool

        assert ensure_exiftool() is True


class TestGetExiftoolPath:
    def test_returns_none_when_not_installed(self, monkeypatch):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join("nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.shutil.which", lambda _: None)
        assert get_exiftool_path() is None

    def test_returns_lib_path_when_valid(self, tmp_path, monkeypatch):
        exe = tmp_path / "exiftool.exe"
        exe.write_text("fake")
        pl_dir = tmp_path / "exiftool_files"
        pl_dir.mkdir()
        pl = pl_dir / "exiftool.pl"
        pl.write_text("fake")
        monkeypatch.setattr("extensions.exiftool._downloader._EXIFTOOL_PATH", str(exe))
        monkeypatch.setattr("extensions.exiftool._downloader._EXIFTOOL_PL", str(pl))
        assert get_exiftool_path() == str(exe)

    def test_falls_back_to_system(self, monkeypatch):
        monkeypatch.setattr(
            "extensions.exiftool._downloader._EXIFTOOL_PATH",
            os.path.join("nonexistent", "exiftool.exe"),
        )
        monkeypatch.setattr("extensions.exiftool._downloader.shutil.which", lambda _: "/usr/bin/exiftool")
        assert get_exiftool_path() == "/usr/bin/exiftool"


class TestVersionMarker:
    def _prepare(self, monkeypatch, tmp_path):
        lib = tmp_path / "lib"
        exe = lib / "exiftool.exe"
        pl = lib / "exiftool_files" / "exiftool.pl"
        monkeypatch.setattr("extensions.exiftool._downloader._LIB_DIR", str(lib))
        monkeypatch.setattr("extensions.exiftool._downloader._EXIFTOOL_PATH", str(exe))
        monkeypatch.setattr("extensions.exiftool._downloader._EXIFTOOL_PL", str(pl))
        return lib, exe, pl

    def test_marker_stores_post_install_version_not_upstream(self, monkeypatch, tmp_path):
        from wafer.utils import downloader as common
        from extensions.exiftool import _downloader as dl

        lib, exe, pl = self._prepare(monkeypatch, tmp_path)
        monkeypatch.setattr("extensions.exiftool._downloader.platform.system", lambda: "Windows")
        monkeypatch.setattr(dl, "_fetch_latest_version", lambda: "13.55")
        monkeypatch.setattr(dl, "_fetch_expected_sha256", lambda v: "a" * 64)
        monkeypatch.setattr(dl, "safe_download", lambda *a, **k: None)

        def fake_extract(_archive):
            pl.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("x")
            pl.write_text("x")

        monkeypatch.setattr(dl, "_extract", fake_extract)

        assert dl.ensure_exiftool(version="1") is True
        assert common.read_lib_version(str(lib)) == "1"

    def test_reinstall_with_marker_skips_download(self, monkeypatch, tmp_path):
        from wafer.utils import downloader as common
        from extensions.exiftool import _downloader as dl

        lib, exe, pl = self._prepare(monkeypatch, tmp_path)
        pl.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("x")
        pl.write_text("x")
        common.write_lib_version(str(lib), "1")

        def boom(*a, **k):
            raise AssertionError("should not download when marker matches")

        monkeypatch.setattr(dl, "_fetch_latest_version", boom)
        monkeypatch.setattr(dl, "safe_download", boom)

        assert dl.ensure_exiftool(version="1") is True

