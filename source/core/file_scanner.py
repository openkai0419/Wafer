import os
from pathlib import Path
from ..common import normalize_path

class FileScanner:
    def __init__(self, exclude_cb=None, extensions=None):
        self.exclude_cb = exclude_cb or (lambda p: False)
        self.extensions = tuple(e.lower() for e in (extensions or []))

    def scan(self, root_path):
        stack = [str(root_path)]
        while stack:
            current = stack.pop()
            full_path = normalize_path(current)
            if self.exclude_cb(full_path):
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(self.extensions):
                            stat = entry.stat()
                            yield normalize_path(entry.path), (stat.st_mtime, stat.st_size)
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
            except Exception:
                continue

    def load_previous(self, cursor):
        result = {}
        cursor.execute("SELECT path, mtime, size FROM images")
        while True:
            rows = cursor.fetchmany(10000)
            if not rows:
                break
            result.update({normalize_path(path): (mtime, size) for path, mtime, size in rows})
        return result
