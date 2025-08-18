import os
from blake3 import blake3

def fast_sig_hash(path: str, size: int, part_bytes = 64) -> str:
    if size == 0:
        return "z"  # 任意のゼロサイズ印
    part_bytes = part_bytes * 1024
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
    return h.hexdigest(16)  # 128bit相当で十分（衝突は full で最終確認）


def file_hash(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = blake3()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b: break
            h.update(b)
    return h.hexdigest()

def full_hash(path: str, threads: int | None = None) -> str:
    hasher = blake3(max_threads=threads or os.cpu_count())
    with open(path, 'rb', buffering=8*1024*1024) as f:
        while True:
            b = f.read(8*1024*1024)
            if not b: break
            hasher.update(b)
    return hasher.hexdigest()