import os

from natsort import natsort_keygen

from ..logs import AppLogger
from .paths import normalize_path

FOLDER_SORT_KEY = natsort_keygen(key=lambda path: (os.path.basename(path) or path).lower())


def is_hidden_folder(path, excluded, ignore_pattern_re=None):
    return path in excluded or (ignore_pattern_re is not None and ignore_pattern_re.match(path) is not None)


def visible_roots(roots, excluded, ignore_pattern_re=None):
    visible = (root for root in dict.fromkeys(normalize_path(r) for r in roots) if not is_hidden_folder(root, excluded, ignore_pattern_re))
    return tuple(sorted(visible, key=FOLDER_SORT_KEY))


def scan_child_paths(path, excluded, ignore_pattern_re=None):
    children = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                full = normalize_path(entry.path)
                if not is_hidden_folder(full, excluded, ignore_pattern_re):
                    children.append(full)
    except OSError as e:
        AppLogger.warning(f"Cannot list the folders in {path}: {e}")
    return tuple(sorted(children, key=FOLDER_SORT_KEY))


def has_subfolders(path, excluded, ignore_pattern_re=None):
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) and not is_hidden_folder(normalize_path(entry.path), excluded, ignore_pattern_re):
                    return True
        return False
    except PermissionError:
        return False
    except OSError as e:
        AppLogger.warning(f"Cannot check the folders in {path}: {e}")
        return False


def scan_children(path, excluded, ignore_pattern_re=None):
    return [(child, has_subfolders(child, excluded, ignore_pattern_re)) for child in scan_child_paths(path, excluded, ignore_pattern_re)]


def scan_roots(roots, excluded, ignore_pattern_re=None):
    return [(root, has_subfolders(root, excluded, ignore_pattern_re)) for root in visible_roots(roots, excluded, ignore_pattern_re)]
