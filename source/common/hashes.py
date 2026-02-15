import os
from blake3 import blake3

from .logs import AppLogger

def fast_sig_hash(path: str, size=None, part_bytes = 256) -> str:
    try:
        if not size:
            st = os.stat(path)
            size = st.st_size
        if size == 0:
            return "z"  # 任意のゼロサイズ印
        offsets = [0, max(0, size // 2 - part_bytes // 2), max(0, size - part_bytes)]
        h = blake3()
        with open(path, 'rb', buffering=1024*1024) as f:
            for off in offsets:
                f.seek(off)
                remaining = min(part_bytes, size - off)
                while remaining > 0:
                    chunk = f.read(min(1024*1024, remaining))
                    if not chunk: break
                    h.update(chunk)
                    remaining -= len(chunk)
        return h.hexdigest(16)
    except (OSError, ValueError) as e:
        AppLogger.warning(f"fast_sig_hash failed: {path}", exc=e)
        return "f"

def full_hash(path: str, threads: int | None = None) -> str:
    try:
        hasher = blake3(max_threads=threads or os.cpu_count())
        with open(path, 'rb', buffering=8*1024*1024) as f:
            while True:
                b = f.read(8*1024*1024)
                if not b: break
                hasher.update(b)
        return hasher.hexdigest()
    except (OSError, ValueError) as e:
        AppLogger.warning(f"full_hash failed: {path}", exc=e)
        return "f"