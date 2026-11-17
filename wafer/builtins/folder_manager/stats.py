import os
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from wafer.core.common.paths import child_prefix, normalize_path, parent_folder
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
        self.totals = {}
        for root in self.roots:
            if root in self.nodes:
                self.total_subtree(root)
        self.finished = True

    def total_subtree(self, start: str) -> None:
        order: list[str] = []
        stack = [start]
        while stack:
            path = stack.pop()
            order.append(path)
            stack.extend(child for child in self.nodes[path][0] if child in self.nodes)
        for path in reversed(order):
            self.totals[path] = self.sum_children(path)

    def sum_children(self, path: str) -> tuple[int, int]:
        child_dirs, file_count = self.nodes[path]
        all_files = file_count
        all_folders = 0
        for child in child_dirs:
            child_total = self.totals.get(child)
            if child_total is not None:
                all_files += child_total[0]
                all_folders += child_total[1] + 1
        return all_files, all_folders

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

    def update_folder(self, path: str, child_dirs: list[str], file_count: int) -> None:
        before = self.contribution(path)
        old = self.nodes.get(path)
        if old is not None:
            kept = set(child_dirs)
            for child in old[0]:
                if child not in kept:
                    self.forget(child)
        self.nodes[path] = (list(child_dirs), file_count)
        if self.finished and path in self.totals:
            self.totals[path] = self.sum_children(path)
            self.push_up(path, before)

    def replace_subtrees(self, paths: Sequence[str], entries: Iterable[tuple[str, list[str], int]]) -> None:
        before = {path: self.contribution(path) for path in paths}
        for path in paths:
            for child in self.nodes.get(path, ([], 0))[0]:
                self.forget(child)
        for path, child_dirs, file_count in entries:
            self.nodes[path] = (list(child_dirs), file_count)
        if not self.finished:
            return
        for path in paths:
            if path in self.nodes:
                self.total_subtree(path)
                self.push_up(path, before[path])

    def forget(self, path: str) -> None:
        stack = [path]
        while stack:
            current = stack.pop()
            self.totals.pop(current, None)
            node = self.nodes.pop(current, None)
            if node is not None:
                stack.extend(node[0])

    def contribution(self, path: str) -> tuple[int, int]:
        total = self.totals.get(path)
        return (total[0], total[1] + 1) if total is not None else (0, 0)

    def push_up(self, path: str, before: tuple[int, int]) -> None:
        after = self.contribution(path)
        files_delta, folders_delta = after[0] - before[0], after[1] - before[1]
        if not files_delta and not folders_delta:
            return
        child = path
        while True:
            parent = parent_folder(child)
            node = self.nodes.get(parent)
            total = self.totals.get(parent)
            if len(parent) >= len(child) or node is None or total is None or child not in node[0]:
                return
            self.totals[parent] = (total[0] + files_delta, total[1] + folders_delta)
            child = parent


def count_sources_by_folder(sources: Iterable[str], roots: Sequence[str]) -> dict[str, tuple[int, int]]:
    root_prefixes = sorted(((root, child_prefix(root)) for root in map(normalize_path, roots)), key=lambda r: -len(r[0]))
    direct = Counter(parent_folder(source) for source in sources)
    total: dict[str, int] = {}
    for folder, count in direct.items():
        root = next((r for r, prefix in root_prefixes if folder == r or folder.startswith(prefix)), None)
        if root is None:
            continue
        current = folder
        while True:
            total[current] = total.get(current, 0) + count
            parent = parent_folder(current)
            if current == root or len(parent) >= len(current):
                break
            current = parent
    return {folder: (direct.get(folder, 0), all_count) for folder, all_count in total.items()}
