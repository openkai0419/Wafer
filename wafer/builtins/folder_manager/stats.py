import os
import posixpath
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from wafer.core.common.paths import child_prefix, normalize_path
from wafer.core.logs import AppLogger


class Cancellable(Protocol):
    def is_cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class FolderValues:
    files: int
    all_files: int
    folders: int
    all_folders: int


def is_hidden(path: str, excluded: set[str], ignore_pattern_re) -> bool:
    return path in excluded or (ignore_pattern_re is not None and ignore_pattern_re.match(path) is not None)


def list_folder(path: str, excluded: set[str], ignore_pattern_re) -> tuple[list[str], int]:
    child_dirs: list[str] = []
    file_count = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    child = normalize_path(entry.path)
                    if not is_hidden(child, excluded, ignore_pattern_re):
                        child_dirs.append(child)
                else:
                    file_count += 1
    except OSError as exc:
        AppLogger.debug(f"[FolderManager] cannot list {path}: {exc}")
        return [], 0
    return child_dirs, file_count


def walk_disk(
    roots: Sequence[str],
    excluded: set[str],
    ignore_pattern_re,
    cancel: Cancellable,
    on_batch: Callable[[list[tuple[str, list[str], int]]], None],
    batch_size: int = 256,
) -> None:
    normalized = (normalize_path(root) for root in roots)
    queue = [root for root in normalized if not is_hidden(root, excluded, ignore_pattern_re)]
    head = 0
    batch: list[tuple[str, list[str], int]] = []
    while head < len(queue):
        if cancel.is_cancelled():
            return
        path = queue[head]
        head += 1
        child_dirs, file_count = list_folder(path, excluded, ignore_pattern_re)
        queue.extend(child_dirs)
        batch.append((path, child_dirs, file_count))
        if len(batch) >= batch_size:
            on_batch(batch)
            batch = []
    if batch and not cancel.is_cancelled():
        on_batch(batch)


class DiskTree:
    def __init__(self, roots: Sequence[str]):
        self.roots = [normalize_path(root) for root in roots]
        self.nodes: dict[str, tuple[list[str], int]] = {}
        self.totals: dict[str, tuple[int, int]] = {}
        self.finished = False

    def add(self, path: str, child_dirs: list[str], file_count: int) -> None:
        self.nodes[path] = (child_dirs, file_count)
        self.finished = False

    def finish(self) -> None:
        order: list[str] = []
        stack = [root for root in self.roots if root in self.nodes]
        while stack:
            path = stack.pop()
            order.append(path)
            stack.extend(child for child in self.nodes[path][0] if child in self.nodes)
        totals: dict[str, tuple[int, int]] = {}
        for path in reversed(order):
            child_dirs, file_count = self.nodes[path]
            all_files = file_count
            all_folders = 0
            for child in child_dirs:
                child_total = totals.get(child)
                if child_total is not None:
                    all_files += child_total[0]
                    all_folders += child_total[1] + 1
            totals[path] = (all_files, all_folders)
        self.totals = totals
        self.finished = True

    def values(self, path: str) -> FolderValues | None:
        node = self.nodes.get(path)
        if node is None:
            return None
        child_dirs, file_count = node
        folders = len(child_dirs)
        if not self.finished:
            return FolderValues(file_count, -1, folders, -1)
        all_files, all_folders = self.totals.get(path, (file_count, folders))
        return FolderValues(file_count, all_files, folders, all_folders)

    def drop_subtree(self, path: str) -> None:
        parent = self.nodes.get(posixpath.dirname(path))
        if parent is not None and path in parent[0]:
            self.nodes[posixpath.dirname(path)] = ([child for child in parent[0] if child != path], parent[1])
        stack = [path]
        while stack:
            current = stack.pop()
            node = self.nodes.pop(current, None)
            if node is not None:
                stack.extend(node[0])
        self.finished = False


def count_sources_by_folder(sources: Iterable[str], roots: Sequence[str]) -> dict[str, tuple[int, int]]:
    root_prefixes = sorted(((root, child_prefix(root)) for root in map(normalize_path, roots)), key=lambda r: -len(r[0]))
    direct_by_folder = Counter(posixpath.dirname(source) for source in sources)
    direct: dict[str, int] = {}
    total: dict[str, int] = {}
    for folder, count in direct_by_folder.items():
        root = next((r for r, prefix in root_prefixes if folder == r or folder.startswith(prefix)), None)
        if root is None:
            continue
        direct[folder] = count
        current = folder
        while True:
            total[current] = total.get(current, 0) + count
            if current == root:
                break
            current = posixpath.dirname(current)
    return {folder: (direct.get(folder, 0), all_count) for folder, all_count in total.items()}
