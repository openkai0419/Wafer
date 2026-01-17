from __future__ import annotations

import os
import re
from pathlib import Path


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
        import shutil

        shutil.rmtree(p)
