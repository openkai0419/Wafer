import os
import tempfile
import pytest
from wafer.utils.hashes import fast_signature_hash, full_hash, sha256_file, verify_sha256


def _make_file(content: bytes):
    f = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    f.write(content)
    f.close()
    return f.name


def test_fast_signature_hash_basic():
    path = _make_file(b"hello world" * 100)
    try:
        h = fast_signature_hash(path)
        assert isinstance(h, str)
        assert len(h) > 0
        assert h != "f"
    finally:
        os.unlink(path)


def test_fast_signature_hash_deterministic():
    path = _make_file(b"test data" * 50)
    try:
        h1 = fast_signature_hash(path)
        h2 = fast_signature_hash(path)
        assert h1 == h2
    finally:
        os.unlink(path)


def test_fast_signature_hash_different_files():
    p1 = _make_file(b"aaa" * 100)
    p2 = _make_file(b"bbb" * 100)
    try:
        assert fast_signature_hash(p1) != fast_signature_hash(p2)
    finally:
        os.unlink(p1)
        os.unlink(p2)


def test_fast_signature_hash_empty_file():
    path = _make_file(b"")
    try:
        assert fast_signature_hash(path) == "z"
    finally:
        os.unlink(path)


def test_fast_signature_hash_nonexistent():
    h = fast_signature_hash("/nonexistent/file.bin")
    assert h == "f"


def test_full_hash_basic():
    path = _make_file(b"full hash test content")
    try:
        h = full_hash(path)
        assert isinstance(h, str)
        assert len(h) > 0
        assert h != "f"
    finally:
        os.unlink(path)


def test_full_hash_deterministic():
    path = _make_file(b"same content")
    try:
        assert full_hash(path) == full_hash(path)
    finally:
        os.unlink(path)


def test_full_hash_different_files():
    p1 = _make_file(b"content_a")
    p2 = _make_file(b"content_b")
    try:
        assert full_hash(p1) != full_hash(p2)
    finally:
        os.unlink(p1)
        os.unlink(p2)


def test_full_hash_nonexistent():
    h = full_hash("/nonexistent/file.bin")
    assert h == "f"


def test_fast_vs_full_different():
    path = _make_file(b"x" * 10000)
    try:
        fh = fast_signature_hash(path)
        fl = full_hash(path)
        assert isinstance(fh, str)
        assert isinstance(fl, str)
        assert fh != fl
    finally:
        os.unlink(path)


_HELLO_SHA256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_sha256_file_known_value():
    path = _make_file(b"hello world")
    try:
        assert sha256_file(path) == _HELLO_SHA256
    finally:
        os.unlink(path)


def test_verify_sha256_match():
    path = _make_file(b"hello world")
    try:
        assert verify_sha256(path, _HELLO_SHA256) is True
        assert verify_sha256(path, _HELLO_SHA256.upper()) is True
    finally:
        os.unlink(path)


def test_verify_sha256_mismatch():
    path = _make_file(b"hello world")
    try:
        assert verify_sha256(path, "a" * 64) is False
    finally:
        os.unlink(path)


def test_verify_sha256_invalid_hex():
    path = _make_file(b"hello world")
    try:
        with pytest.raises(ValueError):
            verify_sha256(path, "not-a-valid-sha")
    finally:
        os.unlink(path)
