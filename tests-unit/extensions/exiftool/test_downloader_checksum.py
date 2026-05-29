import io

import pytest

import extensions.exiftool._downloader as dl
from wafer.utils import downloader as common


_CHECKSUMS_BODY = (
    b"SHA1(exiftool-13.58.tar.gz)= 0123456789abcdef0123456789abcdef01234567\n"
    b"SHA2-256(exiftool-13.58.tar.gz)= "
    b"1111111111111111111111111111111111111111111111111111111111111111\n"
    b"SHA2-256(exiftool-13.58_64.zip)= "
    b"fd3b407a01e6ffc6160f2d5fde5ff0c003f6c4c2ba85eee1ce8928ccb51fa3e6\n"
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


def _patch(monkeypatch, payload: bytes):
    monkeypatch.setattr(common.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(payload))


class TestFetchExpectedSha256:
    def test_extracts_zip_checksum(self, monkeypatch):
        _patch(monkeypatch, _CHECKSUMS_BODY)
        sha = dl._fetch_expected_sha256("13.58")
        assert sha == "fd3b407a01e6ffc6160f2d5fde5ff0c003f6c4c2ba85eee1ce8928ccb51fa3e6"

    def test_missing_line_raises(self, monkeypatch):
        _patch(monkeypatch, b"SHA1(other.zip)= xx\n")
        with pytest.raises(RuntimeError, match="missing SHA2-256"):
            dl._fetch_expected_sha256("13.58")

    def test_oversized_response_raises(self, monkeypatch):
        _patch(monkeypatch, b"x" * (dl._MAX_CHECKSUMS_RESPONSE + 10))
        with pytest.raises(RuntimeError, match="too large"):
            dl._fetch_expected_sha256("13.58")

    def test_version_mismatch_not_matched(self, monkeypatch):
        _patch(monkeypatch, _CHECKSUMS_BODY)
        with pytest.raises(RuntimeError, match="missing SHA2-256"):
            dl._fetch_expected_sha256("99.99")
