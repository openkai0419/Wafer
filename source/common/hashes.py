
from blake3 import blake3

def file_hash(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = blake3()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b: break
            h.update(b)
    return h.hexdigest()