import hashlib
import io
import json
import os
from unittest import mock

import pytest

from wafer.utils import downloader as dl


HELLO = b"hello world"
HELLO_SHA = hashlib.sha256(HELLO).hexdigest()


class TestValidateUrl:
    def test_https_allowed_exact_host(self):
        assert dl.validate_url("https://example.com/a", ("example.com",))

    def test_https_allowed_subdomain(self):
        assert dl.validate_url("https://api.example.com/x", ("example.com",))

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="Insecure URL scheme"):
            dl.validate_url("http://example.com/x", ("example.com",))

    def test_no_hostname_rejected(self):
        with pytest.raises(ValueError, match="no hostname"):
            dl.validate_url("https:///path", ("example.com",))

    def test_untrusted_host_rejected(self):
        with pytest.raises(ValueError, match="Untrusted host"):
            dl.validate_url("https://evil.com/x", ("example.com",))


class TestSafeDownload:
    def _patch_retrieve(self, monkeypatch, payload: bytes):
        def fake(url, tmp_dest):
            with open(tmp_dest, "wb") as f:
                f.write(payload)
        monkeypatch.setattr(dl.urllib.request, "urlretrieve", fake)

    def test_success_writes_file(self, tmp_path, monkeypatch):
        self._patch_retrieve(monkeypatch, HELLO)
        dest = str(tmp_path / "out.bin")
        dl.safe_download("https://example.com/x", dest, allowed_hosts=("example.com",))
        assert open(dest, "rb").read() == HELLO
        assert not os.path.exists(dest + ".tmp")

    def test_sha256_match(self, tmp_path, monkeypatch):
        self._patch_retrieve(monkeypatch, HELLO)
        dest = str(tmp_path / "out.bin")
        dl.safe_download("https://example.com/x", dest,
                         allowed_hosts=("example.com",), expected_sha256=HELLO_SHA)
        assert os.path.isfile(dest)

    def test_sha256_mismatch_raises_and_cleans(self, tmp_path, monkeypatch):
        self._patch_retrieve(monkeypatch, HELLO)
        dest = str(tmp_path / "out.bin")
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            dl.safe_download("https://example.com/x", dest,
                             allowed_hosts=("example.com",), expected_sha256="0" * 64)
        assert not os.path.exists(dest)
        assert not os.path.exists(dest + ".tmp")

    def test_retrieve_failure_cleans_tmp(self, tmp_path, monkeypatch):
        def fake(url, tmp_dest):
            with open(tmp_dest, "wb") as f:
                f.write(b"partial")
            raise IOError("network down")
        monkeypatch.setattr(dl.urllib.request, "urlretrieve", fake)
        dest = str(tmp_path / "out.bin")
        with pytest.raises(IOError):
            dl.safe_download("https://example.com/x", dest, allowed_hosts=("example.com",))
        assert not os.path.exists(dest + ".tmp")

    def test_disallowed_host_rejected(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(dl.urllib.request, "urlretrieve",
                            lambda *a, **k: called.append(a))
        with pytest.raises(ValueError):
            dl.safe_download("https://evil.com/x", str(tmp_path / "x"),
                             allowed_hosts=("example.com",))
        assert called == []


class _FakeResp:
    def __init__(self, payload: bytes):
        self._buf = io.BytesIO(payload)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestFetchText:
    def test_success(self, monkeypatch):
        captured = {}

        def fake(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.headers)
            return _FakeResp(b"hello")

        monkeypatch.setattr(dl.urllib.request, "urlopen", fake)
        out = dl.fetch_text("https://example.com/x",
                            allowed_hosts=("example.com",),
                            max_bytes=1024, user_agent="ua-test")
        assert out == "hello"
        assert captured["url"] == "https://example.com/x"
        assert captured["headers"].get("User-agent") == "ua-test"

    def test_extra_headers_passed(self, monkeypatch):
        captured = {}

        def fake(req, timeout=None):
            captured["headers"] = dict(req.headers)
            return _FakeResp(b"{}")

        monkeypatch.setattr(dl.urllib.request, "urlopen", fake)
        dl.fetch_text("https://example.com/x",
                       allowed_hosts=("example.com",),
                       max_bytes=64, user_agent="u",
                       extra_headers={"Accept": "application/json"})
        assert captured["headers"].get("Accept") == "application/json"

    def test_max_bytes_exceeded(self, monkeypatch):
        big = b"x" * 100
        monkeypatch.setattr(dl.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp(big))
        with pytest.raises(RuntimeError, match="too large"):
            dl.fetch_text("https://example.com/x",
                           allowed_hosts=("example.com",),
                           max_bytes=10, user_agent="u")


class TestFetchJson:
    def test_parses(self, monkeypatch):
        monkeypatch.setattr(dl.urllib.request, "urlopen",
                            lambda req, timeout=None: _FakeResp(json.dumps({"a": 1}).encode()))
        assert dl.fetch_json("https://example.com/x",
                             allowed_hosts=("example.com",),
                             max_bytes=64, user_agent="u") == {"a": 1}


class TestValidateArchivePath:
    def test_simple_name_ok(self, tmp_path):
        dl.validate_archive_path("file.txt", str(tmp_path))

    def test_nested_ok(self, tmp_path):
        dl.validate_archive_path("sub/file.txt", str(tmp_path))

    def test_dotdot_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="traversal"):
            dl.validate_archive_path("../evil", str(tmp_path))

    def test_absolute_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="traversal"):
            dl.validate_archive_path("C:\\Windows\\evil" if os.name == "nt" else "/etc/passwd",
                                     str(tmp_path))


class TestFindSystem7z:
    def test_path_lookup(self, monkeypatch):
        monkeypatch.setattr(dl.shutil, "which", lambda n: "C:/fake/7z.exe" if n == "7z" else None)
        assert dl.find_system_7z() == "7z"

    def test_program_files_lookup(self, monkeypatch, tmp_path):
        monkeypatch.setattr(dl.shutil, "which", lambda n: None)
        pf = tmp_path / "PF"
        (pf / "7-Zip").mkdir(parents=True)
        exe = pf / "7-Zip" / "7z.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("ProgramFiles", str(pf))
        monkeypatch.setenv("ProgramFiles(x86)", "")
        assert dl.find_system_7z() == str(exe)

    def test_not_found(self, monkeypatch):
        monkeypatch.setattr(dl.shutil, "which", lambda n: None)
        monkeypatch.setenv("ProgramFiles", "")
        monkeypatch.setenv("ProgramFiles(x86)", "")
        assert dl.find_system_7z() is None


class TestEnsure7zr:
    def test_existing_returns(self, tmp_path):
        path = tmp_path / "7zr.exe"
        path.write_bytes(b"x")
        assert dl.ensure_7zr(str(tmp_path)) == str(path)

    def test_downloads_with_pinned_sha(self, tmp_path, monkeypatch):
        calls = {}
        # Construct fake content that matches the pinned SHA — not feasible.
        # Instead, monkeypatch verify_sha256 to True and just check flow.
        def fake_retrieve(url, dest):
            calls["url"] = url
            calls["dest"] = dest
            with open(dest, "wb") as f:
                f.write(b"fake")
        monkeypatch.setattr(dl.urllib.request, "urlretrieve", fake_retrieve)
        monkeypatch.setattr(dl, "verify_sha256", lambda p, h: True)
        out = dl.ensure_7zr(str(tmp_path))
        assert out == str(tmp_path / "7zr.exe")
        assert calls["url"] == dl._SEVEN_ZR_URL

    def test_pin_mismatch_raises(self, tmp_path, monkeypatch):
        def fake_retrieve(url, dest):
            with open(dest, "wb") as f:
                f.write(b"fake")
        monkeypatch.setattr(dl.urllib.request, "urlretrieve", fake_retrieve)
        monkeypatch.setattr(dl, "verify_sha256", lambda p, h: False)
        with pytest.raises(RuntimeError, match="SHA256 mismatch"):
            dl.ensure_7zr(str(tmp_path))


def _make_fake_py7zr_module(archive_contents: dict):
    """archive_contents: {name_in_archive: bytes}"""
    class FakeZ:
        def __init__(self, path, mode):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def getnames(self):
            return list(archive_contents.keys())

        def extract(self, target_dir, targets):
            for t in targets:
                full = os.path.join(target_dir, t)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "wb") as f:
                    f.write(archive_contents[t])

    m = mock.MagicMock()
    m.SevenZipFile = FakeZ
    return m


class TestExtract7zMembers:
    def test_py7zr_path_flat_target(self, tmp_path, monkeypatch):
        archive = {"build/bin/ffprobe.exe": b"PROBE", "build/bin/ffmpeg.exe": b"FFMP", "build/readme.txt": b"r"}
        fake_mod = _make_fake_py7zr_module(archive)
        monkeypatch.setitem(__import__("sys").modules, "py7zr", fake_mod)
        target = tmp_path / "lib"
        dl.extract_7z_members(str(tmp_path / "fake.7z"), str(target),
                              ("ffprobe.exe", "ffmpeg.exe"))
        assert (target / "ffprobe.exe").read_bytes() == b"PROBE"
        assert (target / "ffmpeg.exe").read_bytes() == b"FFMP"
        # safety assertion: no subdirs polluted target
        assert sorted(p.name for p in target.iterdir()) == ["ffmpeg.exe", "ffprobe.exe"]

    def test_missing_member_raises(self, tmp_path, monkeypatch):
        archive = {"other.txt": b"x"}
        fake_mod = _make_fake_py7zr_module(archive)
        monkeypatch.setitem(__import__("sys").modules, "py7zr", fake_mod)
        # py7zr will raise FileNotFoundError("No matching members") inside, which is caught
        # and falls back to external 7z. Make external 7z fail predictably:
        monkeypatch.setattr(dl, "find_system_7z", lambda: "fake_7z.exe")
        def fake_run(*a, **k):
            class R: pass
            r = R()
            r.returncode = 0
            r.stderr = ""
            return r
        monkeypatch.setattr(dl.subprocess, "run", fake_run)
        with pytest.raises(FileNotFoundError, match="Missing after 7z extraction"):
            dl.extract_7z_members(str(tmp_path / "fake.7z"), str(tmp_path / "out"),
                                  ("ffprobe.exe",))

    def test_archive_traversal_rejected(self, tmp_path, monkeypatch):
        archive = {"../evil.exe": b"x"}
        fake_mod = _make_fake_py7zr_module(archive)
        monkeypatch.setitem(__import__("sys").modules, "py7zr", fake_mod)
        # Traversal in py7zr → falls back to external 7z; make 7z absent too
        monkeypatch.setattr(dl, "find_system_7z", lambda: None)
        monkeypatch.setattr(dl, "ensure_7zr", lambda d: (_ for _ in ()).throw(RuntimeError("no 7zr")))
        with pytest.raises(RuntimeError, match="no 7zr"):
            dl.extract_7z_members(str(tmp_path / "fake.7z"), str(tmp_path / "out"),
                                  ("evil.exe",))

    def test_external_fallback_when_py7zr_absent(self, tmp_path, monkeypatch):
        import sys
        sys.modules.pop("py7zr", None)
        # Force ImportError by inserting None? Use a finder. Simpler: monkeypatch import via builtins
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def fake_import(name, *a, **k):
            if name == "py7zr":
                raise ImportError("not installed")
            return real_import(name, *a, **k)

        monkeypatch.setattr("builtins.__import__", fake_import)
        monkeypatch.setattr(dl, "find_system_7z", lambda: "fake_7z")

        def fake_run(cmd, **k):
            # cmd: [exe, "e", archive, "-o<tmp>", name, "-r", "-y"]
            tmp_arg = cmd[3]
            assert tmp_arg.startswith("-o")
            out_dir = tmp_arg[2:]
            name = cmd[4]
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, name), "wb") as f:
                f.write(b"DATA")
            class R:
                returncode = 0
                stderr = ""
            return R()

        monkeypatch.setattr(dl.subprocess, "run", fake_run)
        target = tmp_path / "lib"
        dl.extract_7z_members(str(tmp_path / "fake.7z"), str(target), ("ffmpeg.exe",))
        assert (target / "ffmpeg.exe").read_bytes() == b"DATA"
