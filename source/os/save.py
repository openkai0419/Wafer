from __future__ import annotations

import os
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import requests
from PySide6 import QtCore, QtGui

from ..common.errors import show_warning
from ..common.profiling import logger


def _norm_abs_case(p: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(p))))


def _is_same_path(a: str, b: str) -> bool:
    na = _norm_abs_case(a)
    nb = _norm_abs_case(b)
    if na == nb:
        return True
    try:
        return os.path.samefile(a, b)
    except (FileNotFoundError, PermissionError, OSError):
        return False


def _is_subpath(child: str, parent: str) -> bool:
    c = _norm_abs_case(child)
    p = _norm_abs_case(parent)
    cd, pd = os.path.splitdrive(c)[0].lower(), os.path.splitdrive(p)[0].lower()
    if cd != pd:
        return False
    try:
        return os.path.commonpath([c, p]) == p and c != p
    except ValueError:
        return False


def check_copy_conflict(src: str | Path | None, dst: str | Path | None) -> str | None:
    if not src or not dst:
        return None
    s = str(src)
    d = str(dst)
    if _is_same_path(s, d):
        return "same_path"
    if os.path.isdir(s) and _is_subpath(d, s):
        return "subpath"
    return None


_invalid_name_re = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


def get_os_new_folder_name() -> str:
    if sys.platform != "win32":
        return "New Folder"
    try:
        import ctypes
        from ctypes import wintypes
        shlwapi = ctypes.windll.shlwapi
        SHLoadIndirectString = shlwapi.SHLoadIndirectString
        SHLoadIndirectString.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)]
        SHLoadIndirectString.restype = wintypes.LONG
        buf = ctypes.create_unicode_buffer(256)
        if SHLoadIndirectString("@shell32.dll,-30396", buf, 256, None) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return "New Folder"


def sanitize_filename(name: str | None, *, fallback: str = "download") -> str:
    s = str(name or "").strip()
    s = os.path.basename(s)
    s = _invalid_name_re.sub("_", s)
    s = s.strip(" .")
    return s or fallback


def unique_path(dest_dir: str | Path, name: str) -> str:
    d = Path(dest_dir)
    d.mkdir(parents=True, exist_ok=True)
    n = sanitize_filename(name)
    base = Path(n).stem
    ext = Path(n).suffix
    candidate = d / n
    i = 2
    while candidate.exists():
        candidate = d / f"{base} ({i}){ext}"
        i += 1
    return str(candidate)


def safe_remove(path: str | Path) -> None:
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return
    if p.is_symlink() or p.is_file():
        p.unlink(missing_ok=True)
        return
    if p.is_dir():
        shutil.rmtree(p)


def copy_file(src: Path, dst: Path, follow_symlinks: bool = True) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    return dst


def copy_dir(src: Path, dst: Path, follow_symlinks: bool = True) -> Path:
    if dst.exists():
        raise FileExistsError(f"Destination exists: {dst}")
    shutil.copytree(src, dst, symlinks=not follow_symlinks, dirs_exist_ok=False)
    return dst


def move_any(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    return Path(shutil.move(str(src), str(dst)))


def copy_or_move(src: Path, dst: Path, *, action: Literal["copy", "cut"], follow_symlinks: bool = True) -> Path:
    if action == "cut":
        return move_any(src, dst)
    if src.is_dir():
        return copy_dir(src, dst, follow_symlinks)
    return copy_file(src, dst, follow_symlinks)



def save_remote_item(item, target_path: str, *, move: bool = False) -> Dict[str, str]:
    d = os.path.dirname(target_path)
    if d:
        os.makedirs(d, exist_ok=True)

    src_info = str(getattr(item, "source", ""))

    if getattr(item, "is_binary", False) and isinstance(getattr(item, "source", None), (bytes, bytearray)):
        try:
            with open(target_path, "wb") as f:
                f.write(item.source)
            logger.info(f"Saved binary data to {target_path}")
            return {"action": "save", "src": "(binary)", "dst": target_path, "status": "ok"}
        except Exception as e:
            return {"action": "save", "src": "(binary)", "dst": target_path, "status": "error", "error": repr(e)}

    if isinstance(src_info, str) and _is_http_url(src_info):
        try:
            with requests.get(src_info, timeout=10, stream=True) as resp:
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                with open(target_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            logger.info(f"Downloaded: {src_info} → {target_path}")
            return {"action": "download", "src": src_info, "dst": target_path, "status": "ok"}
        except Exception as e:
            logger.warning(f"Failed to download {src_info}: {e}")
            return {"action": "download", "src": src_info, "dst": target_path, "status": "error", "error": repr(e)}

    return {"action": "unknown", "src": src_info, "dst": target_path, "status": "error", "error": "Invalid item type"}


def _is_http_url(s: str) -> bool:
    v = (s or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


CutCopy = Tuple[Literal["copy", "cut"], List[Path]]


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
    new_name_or_path: Optional[str] = None
    merge_decisions: Optional[Dict[str, "PasteDecision"]] = None


class PasteCancelledError(Exception):
    pass


@dataclass
class MergeConflictItem:
    src: Path
    dst: Path
    rel_path: str
    is_dir: bool


def _scan_merge_recursive(src: Path, dst: Path, root: Path, out: List[MergeConflictItem]) -> None:
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
            out.append(MergeConflictItem(
                src=entry, dst=d,
                rel_path=str(entry.relative_to(root)),
                is_dir=entry.is_dir(),
            ))


def scan_merge_conflicts(src_dir: Path, dst_dir: Path) -> List[MergeConflictItem]:
    out: List[MergeConflictItem] = []
    if src_dir.is_dir() and dst_dir.is_dir():
        _scan_merge_recursive(src_dir, dst_dir, src_dir, out)
    return out


class PasteExecutor:
    def __init__(self, *, follow_symlinks: bool = True):
        self._follow_symlinks = follow_symlinks

    def execute_plans(
        self,
        plans: List[PastePlanItem],
        decisions: Dict[int, PasteDecision],
    ) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for item in plans:
            dec = decisions.get(item.index)
            if dec is None:
                dec = PasteDecision(mode="skip")
            result = self._execute_item(item.src, item.dst_default, item.action, dec)
            results.append(result)
        return results

    def execute_drop_plans(
        self,
        plans: List[DropPlanItem],
        decisions: Dict[int, PasteDecision],
        *,
        op: str,
    ) -> List[Dict[str, str]]:
        action: Literal["copy", "cut"] = "cut" if op == "move" else "copy"
        results: List[Dict[str, str]] = []
        for plan in plans:
            dec = decisions.get(plan.index)
            if dec is None or dec.mode == "skip":
                results.append({"action": "skip", "src": str(plan.src or ""), "dst": "", "status": "skipped"})
                continue
            if plan.src is not None:
                result = self._execute_item(plan.src, plan.dst_default, action, dec)
                results.append(result)
            else:
                dst_path = str(plan.dst_default)
                if dec.mode == "rename" and plan.suggested_dst:
                    dst_path = str(plan.suggested_dst)
                elif dec.mode == "overwrite" and plan.conflict:
                    safe_remove(dst_path)
                result = save_remote_item(plan.parsed_item, dst_path, move=(op == "move"))
                results.append(result)
        return results

    def _execute_item(
        self,
        src: Path,
        dst: Path,
        action: Literal["copy", "cut"],
        decision: PasteDecision,
    ) -> Dict[str, str]:
        is_dir = src.is_dir()
        if decision.mode == "skip":
            return {"action": "skip", "src": str(src), "dst": "", "status": "skipped"}

        final_dst = self._resolve_dst(dst, decision)
        if final_dst is None:
            return {"action": "unknown", "src": str(src), "dst": "", "status": "error", "error": f"unknown mode: {decision.mode}"}

        conflict = check_copy_conflict(src, final_dst)
        if conflict == "same_path":
            if decision.mode in ("overwrite", "merge"):
                return {"action": "skip", "src": str(src), "dst": str(final_dst), "status": "skipped"}
            final_dst = Path(unique_path(final_dst.parent, final_dst.name))

        if action == "cut" and is_dir and conflict in ("same_path", "subpath"):
            return {"action": "move", "src": str(src), "dst": str(final_dst), "status": "skipped", "error": "cannot move into itself"}
        if is_dir and conflict == "subpath":
            return {"action": "skip", "src": str(src), "dst": str(final_dst), "status": "skipped", "error": "cannot copy into itself"}

        try:
            if decision.mode == "overwrite" and final_dst.exists():
                safe_remove(final_dst)
            if is_dir and decision.mode == "merge" and final_dst.exists():
                self._merge_dir(src, final_dst, action=action, merge_decisions=decision.merge_decisions or {}, root_src=src)
                return {"action": "move" if action == "cut" else "copy", "src": str(src), "dst": str(final_dst), "status": "ok"}
            done = copy_or_move(src, final_dst, action=action, follow_symlinks=self._follow_symlinks)
            return {"action": "move" if action == "cut" else "copy", "src": str(src), "dst": str(done), "status": "ok"}
        except Exception as e:
            return {"action": "move" if action == "cut" else "copy", "src": str(src), "dst": str(final_dst), "status": "error", "error": repr(e)}

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
        merge_decisions: Dict[str, PasteDecision],
        root_src: Path,
    ) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        for entry in src.iterdir():
            d = dst / entry.name
            is_dir = entry.is_dir()

            if not d.exists() and not d.is_symlink():
                copy_or_move(entry, d, action=action, follow_symlinks=self._follow_symlinks)
                continue

            if is_dir and d.is_dir():
                self._merge_dir(entry, d, action=action, merge_decisions=merge_decisions, root_src=root_src)
                continue

            rel = str(entry.relative_to(root_src))
            dec = merge_decisions.get(rel, PasteDecision(mode="overwrite"))

            if dec.mode == "skip":
                continue
            if dec.mode == "rename":
                copy_or_move(entry, Path(unique_path(d.parent, d.name)), action=action, follow_symlinks=self._follow_symlinks)
            else:
                safe_remove(d)
                copy_or_move(entry, d, action=action, follow_symlinks=self._follow_symlinks)

        if action == "cut":
            try:
                src.rmdir()
            except OSError:
                pass


def build_drop_plans(parsed_items: List, dst_dir: str, op: str) -> List[DropPlanItem]:
    plans = []
    for item in parsed_items:
        name = str(getattr(item, "name", "") or "")
        if not name:
            continue
        dst_default = os.path.join(dst_dir, name)
        conflict = os.path.exists(dst_default)
        if getattr(item, "is_local_file", lambda: False)():
            src_abs = os.path.abspath(str(getattr(item, "source", "") or ""))
            if not src_abs or not os.path.exists(src_abs):
                continue
            plans.append(
                DropPlanItem(
                    index=len(plans),
                    src=Path(src_abs),
                    name=name,
                    is_dir=os.path.isdir(src_abs),
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
    def save(self, item, target_path: str, move: bool = False) -> Dict[str, str]:
        if getattr(item, "is_local_file", lambda: False)():
            src = Path(str(getattr(item, "source", "")))
            dst = Path(target_path)
            action: Literal["copy", "cut"] = "cut" if move else "copy"
            plan = PastePlanItem(index=0, src=src, is_dir=src.is_dir(), action=action, dst_default=dst, conflict=dst.exists(), suggested_dst=None)
            results = PasteExecutor().execute_plans([plan], {0: PasteDecision(mode="overwrite")})
            return results[0] if results else {"action": "unknown", "src": str(src), "dst": "", "status": "error"}
        return save_remote_item(item, target_path, move=move)


class ClipboardFilePaster:
    def __init__(self):
        self.clipboard = QtGui.QGuiApplication.clipboard()

    def _extract_windows_drop_effect(self, md: QtCore.QMimeData) -> Optional[str]:
        if not sys.platform.startswith("win"):
            return None
        keys = [
            "Preferred DropEffect",
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
        ]
        for k in keys:
            if md.hasFormat(k):
                try:
                    data = bytes(md.data(k))
                    (effect,) = struct.unpack("<I", data[:4])
                    return "cut" if effect == 2 else "copy"
                except (TypeError, ValueError, struct.error):
                    continue
        return None

    def _extract_from_gnome_clipboard(self, md: QtCore.QMimeData) -> Optional[CutCopy]:
        fmt = "x-special/gnome-copied-files"
        if not md.hasFormat(fmt):
            return None
        try:
            raw = bytes(md.data(fmt)).decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return None
            op = lines[0].lower()
            action = "cut" if op == "cut" else "copy"
            paths: List[Path] = []
            for ln in lines[1:]:
                url = QtCore.QUrl(ln)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            return (action, paths) if paths else None
        except Exception:
            return None

    def _extract_from_nautilus_clipboard(self, md: QtCore.QMimeData) -> Optional[CutCopy]:
        fmt = "x-special/nautilus-clipboard"
        if not md.hasFormat(fmt):
            return None
        try:
            raw = bytes(md.data(fmt)).decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return None
            mode = lines[0].lower()
            action = "cut" if mode == "cut" else "copy"
            paths: List[Path] = []
            for ln in lines[1:]:
                url = QtCore.QUrl(ln)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            return (action, paths) if paths else None
        except Exception:
            return None

    def _parse_uri_list_text(self, text: str) -> List[Path]:
        paths: List[Path] = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                url = QtCore.QUrl(line)
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
            except (OSError, ValueError) as e:
                show_warning(None, f"_parse_uri_list_text failed: {line}", exc=e)
        return paths

    def _parse_plain_text_paths(self, text: str) -> List[Path]:
        cand: List[str] = []
        cand.extend([s.strip('"') for s in re.split(r"[\r\n]+", text) if s.strip()])
        cand.extend(re.findall(r'"([^"]+)"', text))
        cand.extend(re.findall(r'(?:(?:[A-Za-z]:)?[\\/][^\s"\'<>|]+)', text))
        paths: List[Path] = []
        for s in cand:
            try:
                p = Path(s)
                if p.exists():
                    paths.append(p)
            except (OSError, ValueError) as e:
                show_warning(None, f"_parse_plain_text_paths failed: {s}", exc=e)
        return list(dict.fromkeys(paths))

    def collect_clipboard_files(self) -> Optional[CutCopy]:
        md = self.clipboard.mimeData()
        if md is None:
            return None

        res = self._extract_from_gnome_clipboard(md)
        if res:
            return res

        res = self._extract_from_nautilus_clipboard(md)
        if res:
            return res

        paths: List[Path] = []
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.exists():
                        paths.append(p)
        if not paths and md.hasFormat("text/uri-list"):
            try:
                text = bytes(md.data("text/uri-list")).decode("utf-8", errors="replace")
                paths = self._parse_uri_list_text(text)
            except Exception as e:
                show_warning(None, "clipboard uri-list decode failed", exc=e)
        if not paths and md.hasText():
            paths = self._parse_plain_text_paths(md.text())

        if not paths:
            return None

        action = self._extract_windows_drop_effect(md) or "copy"
        return (action, paths)

    def build_paste_plan(self, destination_dir: Path | str) -> List[PastePlanItem]:
        dest_dir = Path(destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        extracted = self.collect_clipboard_files()
        if not extracted:
            return []

        action, paths = extracted
        plan: List[PastePlanItem] = []
        for i, src in enumerate(paths):
            dst_default = dest_dir / src.name
            conflict = dst_default.exists()
            suggested = Path(unique_path(dest_dir, src.name)) if conflict else None
            plan.append(
                PastePlanItem(
                    index=i,
                    src=src,
                    is_dir=src.is_dir(),
                    action=action,
                    dst_default=dst_default,
                    conflict=conflict,
                    suggested_dst=suggested,
                )
            )
        return plan


def _resolve_conflicts_with_ui(
    plans: List,
    *,
    op: str,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "同名フォルダが存在します。ペーストしますか？",
) -> Dict[int, PasteDecision]:
    if overwrite_mode not in ("ask", "overwrite", "skip", "rename"):
        raise ValueError(f"Invalid overwrite_mode: {overwrite_mode}")

    from ..qt.file_conflict_resolver import resolve_paste_plans_with_ui

    return resolve_paste_plans_with_ui(
        plans=plans,
        overwrite_mode=overwrite_mode,
        parent=parent,
        op=op,
        folder_message=folder_message,
    )


def paste_clipboard_files(
    destination_dir: Path | str,
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "同名フォルダが存在します。ペーストしますか？",
) -> List[Dict[str, str]]:
    plans = ClipboardFilePaster().build_paste_plan(destination_dir)
    if not plans:
        return []
    op = "move" if plans[0].action == "cut" else "copy"
    try:
        decisions = _resolve_conflicts_with_ui(
            plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message
        )
    except PasteCancelledError:
        return []
    return PasteExecutor().execute_plans(plans, decisions)


def execute_paste_plans_with_ui(
    plans: List[PastePlanItem],
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "同名フォルダが存在します。ペーストしますか？",
) -> List[Dict[str, str]]:
    if not plans:
        return []
    op = "move" if plans[0].action == "cut" else "copy"
    try:
        decisions = _resolve_conflicts_with_ui(
            plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message
        )
    except PasteCancelledError:
        return []
    return PasteExecutor().execute_plans(plans, decisions)


def drop_files_with_ui(
    parsed_items: List,
    destination_dir: str,
    op: str,
    *,
    overwrite_mode: str = "ask",
    parent: object | None = None,
    folder_message: str = "同名フォルダが存在します。ドロップしますか？",
) -> List[Dict[str, str]]:
    if op not in ("copy", "move"):
        raise ValueError(f"Invalid op: {op}")
    if overwrite_mode not in ("overwrite", "rename", "skip", "ask"):
        raise ValueError(f"Invalid overwrite_mode: {overwrite_mode}")
    plans = build_drop_plans(parsed_items, destination_dir, op)
    if not plans:
        return []
    try:
        decisions = _resolve_conflicts_with_ui(
            plans=plans, op=op, overwrite_mode=overwrite_mode, parent=parent, folder_message=folder_message
        )
    except PasteCancelledError:
        return []
    return PasteExecutor().execute_drop_plans(plans, decisions, op=op)
