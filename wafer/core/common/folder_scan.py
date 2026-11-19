import os
import stat
from collections.abc import Iterable

from natsort import natsort_keygen

from ..logs import AppLogger
from .paths import normalize_path

FOLDER_SORT_KEY = natsort_keygen(key=lambda path: (os.path.basename(path) or path).lower())


def real_path_within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder if folder.endswith(os.sep) else folder + os.sep)


class JunctionFilter:
    """Walks a junction like a folder unless it loops back to a folder above it or points into a root."""

    def __init__(self, roots: Iterable[str] = ()):
        self.roots = tuple(roots)
        self.real_roots: tuple[str, ...] | None = None
        self.real_paths: dict[str, str] = {}

    def skips(self, entry: os.DirEntry) -> bool:
        if getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0) != stat.IO_REPARSE_TAG_MOUNT_POINT:
            return False
        target = self.real_path(entry.path)
        if any(real_path_within(target, root) for root in self.real_root_paths()):
            AppLogger.debug(f"[Folders] Skipped junction {normalize_path(entry.path)}: its target {target} is inside a root")
            return True
        folder = os.path.dirname(entry.path)
        while True:
            if real_path_within(self.real_path(folder), target):
                AppLogger.debug(f"[Folders] Skipped junction {normalize_path(entry.path)}: its target {target} contains the junction")
                return True
            parent = os.path.dirname(folder)
            if parent == folder:
                return False
            folder = parent

    def real_root_paths(self) -> tuple[str, ...]:
        if self.real_roots is None:
            self.real_roots = tuple(self.real_path(root) for root in self.roots)
        return self.real_roots

    def real_path(self, path: str) -> str:
        real = self.real_paths.get(path)
        if real is None:
            real = self.real_paths[path] = os.path.normcase(os.path.realpath(path))
        return real


def is_hidden_folder(path, excluded, ignore_pattern_re=None):
    return path in excluded or (ignore_pattern_re is not None and ignore_pattern_re.match(path) is not None)


def visible_roots(roots, excluded, ignore_pattern_re=None):
    visible = (root for root in dict.fromkeys(normalize_path(r) for r in roots) if not is_hidden_folder(root, excluded, ignore_pattern_re))
    return tuple(sorted(visible, key=FOLDER_SORT_KEY))


def scan_child_paths(path, excluded, ignore_pattern_re=None, roots=()):
    children = []
    junctions = JunctionFilter(roots)
    try:
        with os.scandir(path) as it:
            for entry in it:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                full = normalize_path(entry.path)
                if not is_hidden_folder(full, excluded, ignore_pattern_re) and not junctions.skips(entry):
                    children.append(full)
    except OSError as e:
        AppLogger.warning(f"Cannot list the folders in {path}: {e}")
    return tuple(sorted(children, key=FOLDER_SORT_KEY))


def has_subfolders(path, excluded, ignore_pattern_re=None, roots=()):
    junctions = JunctionFilter(roots)
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) and not is_hidden_folder(normalize_path(entry.path), excluded, ignore_pattern_re) and not junctions.skips(entry):
                    return True
        return False
    except PermissionError:
        return False
    except OSError as e:
        AppLogger.warning(f"Cannot check the folders in {path}: {e}")
        return False


def scan_children(path, excluded, ignore_pattern_re=None, roots=()):
    return [(child, has_subfolders(child, excluded, ignore_pattern_re, roots)) for child in scan_child_paths(path, excluded, ignore_pattern_re, roots)]


def scan_roots(roots, excluded, ignore_pattern_re=None):
    roots = tuple(roots)
    return [(root, has_subfolders(root, excluded, ignore_pattern_re, roots)) for root in visible_roots(roots, excluded, ignore_pattern_re)]
