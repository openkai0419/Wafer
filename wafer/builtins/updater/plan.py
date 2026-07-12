from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ...plugin.badges import KNOWN_EXTENSIONS
from ...utils.logs import AppLogger


PLAN_FORMAT_HEADER = "wafer-update-plan 1"
UPDATE_DIR_NAME = ".update"
NEXT_DIR_NAME = "next"
BACKUP_DIR_NAME = "backup"
DOWNLOAD_DIR_NAME = "download"
PLAN_FILENAME = "apply.plan"
READY_FILENAME = "ready.json"
APPLIED_FILENAME = "applied.txt"
FAILED_FILENAME = "failed.txt"
APPLY_LOG_FILENAME = "apply.log"
LAUNCHER_EXE_NAME = "Wafer.exe"
UNINSTALLER_EXE_NAME = "Uninstaller.exe"
EXTENSIONS_DIR_NAME = "extensions"
EXTENSION_LIB_DIR_NAME = "lib"

_FIRST_ENTRY = "python"
_SKIPPED_CHILDREN = {"__pycache__"}


@dataclass(frozen=True)
class PlanOp:
    src: str
    dst: str
    optional: bool = False


class PlanError(Exception):
    pass


def update_dir(app_root: str | Path) -> Path:
    return Path(app_root) / UPDATE_DIR_NAME


def next_dir(app_root: str | Path) -> Path:
    return update_dir(app_root) / NEXT_DIR_NAME


def backup_dir(app_root: str | Path) -> Path:
    return update_dir(app_root) / BACKUP_DIR_NAME


def download_dir(app_root: str | Path) -> Path:
    return update_dir(app_root) / DOWNLOAD_DIR_NAME


def plan_path(app_root: str | Path) -> Path:
    return update_dir(app_root) / PLAN_FILENAME


def validate_plan_relpath(rel: str) -> str:
    value = str(rel or "").strip().replace("\\", "/")
    if not value:
        raise PlanError("plan path is empty")
    if value.startswith("/") or ":" in value:
        raise PlanError(f"plan path must be relative: {rel!r}")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PlanError(f"unsafe plan path: {rel!r}")
    return value


def _rel(*parts: str) -> str:
    return "/".join(parts)


def _removed_builtin_extensions(root: Path, staged_ext_names: set[str]) -> list[str]:
    live = root / EXTENSIONS_DIR_NAME
    if not live.is_dir():
        return []
    removed = []
    for child in sorted(p.name for p in live.iterdir() if p.is_dir()):
        if child.startswith(".") or child in _SKIPPED_CHILDREN:
            continue
        if child in staged_ext_names or child not in KNOWN_EXTENSIONS:
            continue
        removed.append(child)
    return removed


def generate_plan(app_root: str | Path) -> list[PlanOp]:
    root = Path(app_root)
    staged = next_dir(root)
    if not staged.is_dir():
        raise PlanError(f"staged update not found: {staged}")

    entries = sorted(p.name for p in staged.iterdir() if p.name not in _SKIPPED_CHILDREN)
    if UPDATE_DIR_NAME in entries:
        raise PlanError(f"staged tree must not contain {UPDATE_DIR_NAME}")

    plain = [e for e in entries if e not in (_FIRST_ENTRY, EXTENSIONS_DIR_NAME, LAUNCHER_EXE_NAME, UNINSTALLER_EXE_NAME)]
    ordered = [e for e in (_FIRST_ENTRY,) if e in entries] + plain

    ops: list[PlanOp] = []
    backup_rel = _rel(UPDATE_DIR_NAME, BACKUP_DIR_NAME)
    next_rel = _rel(UPDATE_DIR_NAME, NEXT_DIR_NAME)

    def add_replace(rel_path: str) -> None:
        ops.append(PlanOp(src=rel_path, dst=_rel(backup_rel, rel_path), optional=True))
        ops.append(PlanOp(src=_rel(next_rel, rel_path), dst=rel_path))

    for entry in ordered:
        add_replace(entry)

    ext_staged = staged / EXTENSIONS_DIR_NAME
    if ext_staged.is_dir():
        staged_ext_names: set[str] = set()
        for child in sorted(p.name for p in ext_staged.iterdir()):
            if child.startswith(".") or child in _SKIPPED_CHILDREN:
                continue
            staged_ext_names.add(child)
            ext_rel = _rel(EXTENSIONS_DIR_NAME, child)
            add_replace(ext_rel)
            lib_rel = _rel(ext_rel, EXTENSION_LIB_DIR_NAME)
            ops.append(PlanOp(src=_rel(backup_rel, lib_rel), dst=lib_rel, optional=True))

        removed = _removed_builtin_extensions(root, staged_ext_names)
        if removed:
            AppLogger.info(f"[Updater] Removing built-in extensions dropped from this release: {', '.join(removed)}")
            for name in removed:
                ext_rel = _rel(EXTENSIONS_DIR_NAME, name)
                ops.append(PlanOp(src=ext_rel, dst=_rel(backup_rel, ext_rel), optional=True))

    if UNINSTALLER_EXE_NAME in entries:
        add_replace(UNINSTALLER_EXE_NAME)
    if LAUNCHER_EXE_NAME in entries:
        add_replace(LAUNCHER_EXE_NAME)

    for op in ops:
        validate_plan_relpath(op.src)
        validate_plan_relpath(op.dst)
    return ops


def write_plan(path: str | Path, ops: list[PlanOp]) -> None:
    lines = [PLAN_FORMAT_HEADER]
    for op in ops:
        lines.append(f"move\t{1 if op.optional else 0}\t{validate_plan_relpath(op.src)}\t{validate_plan_relpath(op.dst)}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def read_plan(path: str | Path) -> list[PlanOp]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != PLAN_FORMAT_HEADER:
        raise PlanError(f"unsupported plan header: {lines[0] if lines else '<empty>'}")
    ops: list[PlanOp] = []
    for raw in lines[1:]:
        line = raw.strip()
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 4 or fields[0] != "move" or fields[1] not in ("0", "1"):
            raise PlanError(f"invalid plan line: {raw!r}")
        ops.append(PlanOp(src=validate_plan_relpath(fields[2]), dst=validate_plan_relpath(fields[3]), optional=fields[1] == "1"))
    return ops


def _resolve_within(root: Path, rel: str) -> Path:
    path = (root / validate_plan_relpath(rel)).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    if path != root_resolved and root_resolved not in path.parents:
        raise PlanError(f"plan path escapes app root: {rel!r}")
    return path


def execute_plan(ops: list[PlanOp], app_root: str | Path) -> None:
    root = Path(app_root)
    backup = backup_dir(root)
    if backup.exists():
        shutil.rmtree(backup)

    executed: list[tuple[Path, Path]] = []
    try:
        for op in ops:
            src = _resolve_within(root, op.src)
            dst = _resolve_within(root, op.dst)
            if not src.exists():
                if op.optional:
                    continue
                raise PlanError(f"required source missing: {op.src}")
            if dst.exists():
                if op.optional:
                    continue
                raise PlanError(f"destination already exists: {op.dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
            executed.append((src, dst))
    except Exception:
        _rollback(executed)
        raise


def _rollback(executed: list[tuple[Path, Path]]) -> None:
    for src, dst in reversed(executed):
        try:
            os.rename(dst, src)
        except OSError as e:
            AppLogger.error(f"[Updater] Rollback failed for {dst} -> {src}: {e}", exc=e)
