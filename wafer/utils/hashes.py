import hashlib
import os
from blake3 import blake3

from .logs import AppLogger


def fast_signature_hash(path: str, size=None, part_bytes=256) -> str:
    try:
        if not size:
            st = os.stat(path)
            size = st.st_size
        if size == 0:
            return "z"
        offsets = [0, max(0, size // 2 - part_bytes // 2), max(0, size - part_bytes)]
        h = blake3()
        with open(path, "rb", buffering=1024 * 1024) as f:
            for off in offsets:
                f.seek(off)
                remaining = min(part_bytes, size - off)
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
        return h.hexdigest(16)
    except (OSError, ValueError) as e:
        AppLogger.warning(f"fast_signature_hash failed: {path}", exc=e)
        return "f"


def full_hash(path: str, threads: int | None = None) -> str:
    try:
        hasher = blake3(max_threads=threads or os.cpu_count())
        with open(path, "rb", buffering=8 * 1024 * 1024) as f:
            while True:
                b = f.read(8 * 1024 * 1024)
                if not b:
                    break
                hasher.update(b)
        return hasher.hexdigest()
    except (OSError, ValueError) as e:
        AppLogger.warning(f"full_hash failed: {path}", exc=e)
        return "f"


def sha256_file(path: str, chunk_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb", buffering=chunk_size) as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(path: str, expected_hex: str) -> bool:
    expected = (expected_hex or "").strip().lower()
    if len(expected) != 64 or not all(c in "0123456789abcdef" for c in expected):
        raise ValueError(f"invalid sha256 hex: {expected_hex!r}")
    actual = sha256_file(path)
    return actual == expected
