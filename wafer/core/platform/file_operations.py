from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import requests

from ...utils.logs import AppLogger
from ...utils.paths import safe_exists, safe_is_dir
from .path_utils import check_copy_conflict, is_http_url, unique_path

if TYPE_CHECKING:
    from .dragparser import ParsedItem


def _rmtree_onerror(func, path, exc_info):
    import stat

    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError as e:
        AppLogger.warning(f"rmtree fallback failed: {path} ({e})")


def _safe_remove(path: str | Path) -> None:
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return
    if p.is_symlink() or p.is_file():
        p.unlink(missing_ok=True)
        return
    if p.is_dir():
        shutil.rmtree(p, onerror=_rmtree_onerror)


def _copy_file(src: Path, dst: Path, follow_symlinks: bool = True) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    return dst


def _copy_dir(src: Path, dst: Path, follow_symlinks: bool = True) -> Path:
    if dst.exists():
        raise FileExistsError(f"Destination exists: {dst}")
    shutil.copytree(src, dst, symlinks=not follow_symlinks, dirs_exist_ok=False)
    return dst


def _move_any(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    return Path(shutil.move(str(src), str(dst)))


def _copy_or_move(src: Path, dst: Path, *, action: Literal["copy", "cut"], follow_symlinks: bool = True) -> Path:
    if action == "cut":
        return _move_any(src, dst)
    if src.is_dir():
        return _copy_dir(src, dst, follow_symlinks)
    return _copy_file(src, dst, follow_symlinks)


def _save_remote_item(item: ParsedItem, target_path: str, *, move: bool = False) -> OperationResult:
    d = os.path.dirname(target_path)
    if d:
        os.makedirs(d, exist_ok=True)

    src_info = str(getattr(item, "source", ""))

    if getattr(item, "is_binary", False) and isinstance(getattr(item, "source", None), (bytes, bytearray)):
        try:
            with open(target_path, "wb") as f:
                f.write(item.source)
            AppLogger.info(f"Saved binary data to {target_path}")
            return OperationResult(action="save", src="(binary)", dst=target_path, status="ok")
        except Exception as e:
            return OperationResult(action="save", src="(binary)", dst=target_path, status="error", error=repr(e))

    if isinstance(src_info, str) and is_http_url(src_info):
        try:
            session = requests.Session()
            session.max_redirects = 5
            with session.get(src_info, timeout=10, stream=True) as resp:
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                with open(target_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            AppLogger.info(f"Downloaded: {src_info} -> {target_path}")
            return OperationResult(action="download", src=src_info, dst=target_path, status="ok")
        except Exception as e:
            AppLogger.warning(f"Failed to download {src_info}: {e}")
            return OperationResult(action="download", src=src_info, dst=target_path, status="error", error=repr(e))

    return OperationResult(action="unknown", src=src_info, dst=target_path, status="error", error="Invalid item type")


@dataclass
class OperationResult:
    action: str
    src: str
    dst: str
    status: str
    error: str = ""


CutCopy = tuple[Literal["copy", "cut"], list[Path]]


@dataclass
class PastePlanItem:
    index: int
    src: Path
    is_dir: bool
    action: Literal["copy", "cut"]
    dst_default: Path
    conflict: bool
    suggested_dst: Path | None


@dataclass
class DropPlanItem:
    index: int
    src: Path | None
    name: str
    is_dir: bool
    action: str
    dst_default: Path
    conflict: bool
    suggested_dst: Path | None
    parsed_item: object


@dataclass
class PasteDecision:
    mode: Literal["overwrite", "rename", "skip", "merge"]
    new_name_or_path: str | None = None
    merge_decisions: dict[str, PasteDecision] | None = None


class PasteCancelledError(Exception):
    pass


@dataclass
class MergeConflictItem:
    src: Path
    dst: Path
    rel_path: str
    is_dir: bool


def _scan_merge_recursive(src: Path, dst: Path, root: Path, out: list[MergeConflictItem]) -> None:
    try:
        entries = sorted(src.iterdir(), key=lambda e: (not e.is_dir(), e.name))
    except OSError:
        return
    for entry in entries:
        d = dst / entry.name
        if not d.exists() and not d.is_symlink():
            continue
        if entry.is_dir() and d.is_dir():
            _scan_merge_recursive(entry, d, root, out)
        else:
            out.append(
                MergeConflictItem(
                    src=entry,
                    dst=d,
                    rel_path=str(entry.relative_to(root)),
                    is_dir=entry.is_dir(),
                )
            )


def scan_merge_conflicts(src_dir: Path, dst_dir: Path) -> list[MergeConflictItem]:
    out: list[MergeConflictItem] = []
    if src_dir.is_dir() and dst_dir.is_dir():
        _scan_merge_recursive(src_dir, dst_dir, src_dir, out)
    return out


class FileExecutor:
    def __init__(self, *, follow_symlinks: bool = True):
        self._follow_symlinks = follow_symlinks

    def execute_plans(
        self,
        plans: list[PastePlanItem],
        decisions: dict[int, PasteDecision],
    ) -> list[OperationResult]:
        results: list[OperationResult] = []
        for item in plans:
            dec = decisions.get(item.index)
            if dec is None:
                dec = PasteDecision(mode="skip")
            result = self._execute_item(item.src, item.dst_default, item.action, dec)
            results.append(result)
        return results

    def execute_drop_plans(
        self,
        plans: list[DropPlanItem],
        decisions: dict[int, PasteDecision],
        *,
        op: str,
    ) -> list[OperationResult]:
        action: Literal["copy", "cut"] = "cut" if op == "move" else "copy"
        results: list[OperationResult] = []
        for plan in plans:
            dec = decisions.get(plan.index)
            if dec is None or dec.mode == "skip":
                results.append(OperationResult(action="skip", src=str(plan.src or ""), dst="", status="skipped"))
                continue
            if plan.src is not None:
                result = self._execute_item(plan.src, plan.dst_default, action, dec)
                results.append(result)
            else:
                dst_path = str(plan.dst_default)
                if dec.mode == "rename" and plan.suggested_dst:
                    dst_path = str(plan.suggested_dst)
                elif dec.mode == "overwrite" and plan.conflict:
                    _safe_remove(dst_path)
                result = _save_remote_item(plan.parsed_item, dst_path, move=(op == "move"))
                results.append(result)
        return results

    def _execute_item(
        self,
        src: Path,
        dst: Path,
        action: Literal["copy", "cut"],
        decision: PasteDecision,
    ) -> OperationResult:
        is_dir = src.is_dir()
        if decision.mode == "skip":
            return OperationResult(action="skip", src=str(src), dst="", status="skipped")

        final_dst = self._resolve_dst(dst, decision)
        if final_dst is None:
            return OperationResult(action="unknown", src=str(src), dst="", status="error", error=f"unknown mode: {decision.mode}")

        conflict = check_copy_conflict(src, final_dst)
        if conflict == "same_path":
            if action == "cut" and str(src) != str(final_dst):
                try:
                    src.rename(final_dst)
                    return OperationResult(action="move", src=str(src), dst=str(final_dst), status="ok")
                except Exception as e:
                    return OperationResult(action="move", src=str(src), dst=str(final_dst), status="error", error=repr(e))
            if decision.mode in ("overwrite", "merge"):
                return OperationResult(action="skip", src=str(src), dst=str(final_dst), status="skipped")
            final_dst = Path(unique_path(final_dst.parent, final_dst.name))

        if action == "cut" and is_dir and conflict in ("same_path", "subpath"):
            return OperationResult(action="move", src=str(src), dst=str(final_dst), status="skipped", error="cannot move into itself")
        if is_dir and conflict == "subpath":
            return OperationResult(action="skip", src=str(src), dst=str(final_dst), status="skipped", error="cannot copy into itself")

        try:
            if decision.mode == "overwrite" and final_dst.exists():
                _safe_remove(final_dst)
            if is_dir and decision.mode == "merge" and final_dst.exists():
                self._merge_dir(src, final_dst, action=action, merge_decisions=decision.merge_decisions or {}, root_src=src)
                return OperationResult(action="move" if action == "cut" else "copy", src=str(src), dst=str(final_dst), status="ok")
            done = _copy_or_move(src, final_dst, action=action, follow_symlinks=self._follow_symlinks)
            return OperationResult(action="move" if action == "cut" else "copy", src=str(src), dst=str(done), status="ok")
        except Exception as e:
            AppLogger.warning(f"copy/move failed: {src} -> {final_dst}", exc=e)
            return OperationResult(action="move" if action == "cut" else "copy", src=str(src), dst=str(final_dst), status="error", error=repr(e))

    @staticmethod
    def _resolve_dst(dst: Path, decision: PasteDecision) -> Path | None:
        if decision.mode in ("overwrite", "merge"):
            return dst
        if decision.mode == "rename":
            if decision.new_name_or_path:
                p = Path(decision.new_name_or_path)
                final = p if p.is_absolute() else (dst.parent / p)
            else:
                final = dst
            if final.exists():
                final = Path(unique_path(final.parent, final.name))
            return final
        if decision.mode == "skip":
            return dst
        return None

    def _merge_dir(
        self,
        src: Path,
        dst: Path,
        *,
        action: Literal["copy", "cut"],
        merge_decisions: dict[str, PasteDecision],
        root_src: Path,
    ) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            d = dst / entry.name
            is_dir = entry.is_dir()

            if not d.exists() and not d.is_symlink():
                _copy_or_move(entry, d, action=action, follow_symlinks=self._follow_symlinks)
                continue

            if is_dir and d.is_dir():
                self._merge_dir(entry, d, action=action, merge_decisions=merge_decisions, root_src=root_src)
                continue

            rel = str(entry.relative_to(root_src))
            dec = merge_decisions.get(rel, PasteDecision(mode="overwrite"))

            if dec.mode == "skip":
                continue
            if dec.mode == "rename":
                _copy_or_move(entry, Path(unique_path(d.parent, d.name)), action=action, follow_symlinks=self._follow_symlinks)
            else:
                _safe_remove(d)
                _copy_or_move(entry, d, action=action, follow_symlinks=self._follow_symlinks)

        if action == "cut":
            try:
                src.rmdir()
            except OSError as e:
                AppLogger.debug(f"cut: source dir not removed: {src} ({e})")


def build_drop_plans(parsed_items: list[ParsedItem], dst_dir: str, op: str) -> list[DropPlanItem]:
    plans = []
    seen_local_sources: set[str] = set()
    for item in parsed_items:
        name = str(getattr(item, "name", "") or "")
        if not name:
            continue
        if getattr(item, "is_local_file", lambda: False)():
            src_key = os.path.abspath(str(getattr(item, "source", "") or ""))
            if src_key and src_key in seen_local_sources:
                AppLogger.warning(f"[drop] duplicate source dropped: {src_key}")
                continue
            if src_key:
                seen_local_sources.add(src_key)
        dst_default = os.path.join(dst_dir, name)
        conflict = safe_exists(dst_default)
        if getattr(item, "is_local_file", lambda: False)():
            src_abs = os.path.abspath(str(getattr(item, "source", "") or ""))
            if not src_abs or not safe_exists(src_abs):
                continue
            plans.append(
                DropPlanItem(
                    index=len(plans),
                    src=Path(src_abs),
                    name=name,
                    is_dir=safe_is_dir(src_abs),
                    action=("cut" if op == "move" else "copy"),
                    dst_default=Path(dst_default),
                    conflict=conflict,
                    suggested_dst=Path(unique_path(dst_dir, name)) if conflict else None,
                    parsed_item=item,
                )
            )
        else:
            plans.append(
                DropPlanItem(
                    index=len(plans),
                    src=None,
                    name=name,
                    is_dir=False,
                    action=("cut" if op == "move" else "copy"),
                    dst_default=Path(dst_default),
                    conflict=conflict,
                    suggested_dst=Path(unique_path(dst_dir, name)) if conflict else None,
                    parsed_item=item,
                )
            )
    return plans


class FileSaver:
    def save(self, item: ParsedItem, target_path: str, move: bool = False) -> OperationResult:
        if getattr(item, "is_local_file", lambda: False)():
            src = Path(str(getattr(item, "source", "")))
            dst = Path(target_path)
            action: Literal["copy", "cut"] = "cut" if move else "copy"
            plan = PastePlanItem(index=0, src=src, is_dir=safe_is_dir(src), action=action, dst_default=dst, conflict=safe_exists(dst), suggested_dst=None)
            results = FileExecutor().execute_plans([plan], {0: PasteDecision(mode="overwrite")})
            return results[0] if results else OperationResult(action="unknown", src=str(src), dst="", status="error")
        return _save_remote_item(item, target_path, move=move)


def delete_to_trash(paths: list[str | Path]) -> list[OperationResult]:
    from ...utils.virtual_paths import is_virtual_path

    physical = [p for p in paths if p and not is_virtual_path(str(p))]
    rejected = len(paths) - len(physical)
    if rejected:
        AppLogger.warning(f"[delete] virtual paths rejected: {rejected} entries (file ops must target source files)")
    raw = [os.path.normpath(os.path.abspath(str(p))) for p in physical]
    norm = list(dict.fromkeys(raw))
    if len(norm) != len(raw):
        AppLogger.warning(f"[delete] duplicate sources dropped: {len(raw)} -> {len(norm)}")
    if not norm:
        return []
    AppLogger.info(f"Deleting {len(norm)} files")
    results: list[OperationResult] = []
    try:
        import send2trash as _s2t

        for p in norm:
            if not os.path.exists(p):
                results.append(OperationResult(action="delete", src=p, dst="", status="skipped"))
                continue
            try:
                _s2t.send2trash(p)
                results.append(OperationResult(action="delete", src=p, dst="", status="ok"))
            except Exception as e:
                AppLogger.warning(f"send2trash failed: {p}", exc=e)
                if os.path.isfile(p):
                    os.remove(p)
                    results.append(OperationResult(action="delete", src=p, dst="", status="ok"))
                else:
                    results.append(OperationResult(action="delete", src=p, dst="", status="error", error=f"send2trash failed for folder: {p}"))
    except ImportError:
        for p in norm:
            if not os.path.exists(p):
                results.append(OperationResult(action="delete", src=p, dst="", status="skipped"))
                continue
            if os.path.isfile(p):
                os.remove(p)
                results.append(OperationResult(action="delete", src=p, dst="", status="ok"))
            else:
                results.append(OperationResult(action="delete", src=p, dst="", status="error", error=f"Cannot delete folder without send2trash: {p}"))
    return results


PasteExecutor = FileExecutor
safe_remove = _safe_remove
save_remote_item = _save_remote_item
