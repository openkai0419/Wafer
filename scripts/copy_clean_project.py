from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COPY_FILES = [
    ".gitignore",
    "LICENSE",
    "COPYING",
    "COPYING.LESSER",
    "main.py",
    "pyproject.toml",
    "conftest.py",
    "requirements.txt",
    "requirements-dev.txt",
    "setup.bat",
    "cleanup.bat",
    "RELEASE_NOTES.md",
    "CHANGELOG.md",
    "README.md",
    "README.jp.md",
]

COPY_DIRS: dict[str, set[str]] = {
    "wafer": set(),
    "extensions": {"lib"},
    "tests": set(),
    "tests-unit": set(),
    "_resources": set(),
    "_docs": set(),
    "scripts": set(),
}

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".prototypes",
    ".packages",
    ".pip_staging",
    ".pending",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    ".eggs",
}

EXCLUDE_EXTS = {".pyc", ".pyo", ".pyd", ".db", ".db-shm", ".db-wal", ".ini"}


def clean_dst(dst: Path):
    if not dst.exists():
        dst.mkdir(parents=True)
        return
    for child in list(dst.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _should_skip(rel: Path, extra_exclude: set[str]) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS or parts & extra_exclude:
        return True
    return rel.suffix in EXCLUDE_EXTS


def copy_tree(src: Path, dst: Path, extra_exclude: set[str]):
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        if _should_skip(rel, extra_exclude):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _is_overlapping(a: Path, b: Path) -> bool:
    try:
        a.resolve().relative_to(b.resolve())
        return True
    except ValueError:
        pass
    try:
        b.resolve().relative_to(a.resolve())
        return True
    except ValueError:
        return False


def copy_clean(dst: Path):
    dst = dst.resolve()
    if _is_overlapping(dst, ROOT):
        print(f"Error: destination '{dst}' overlaps with source '{ROOT}'")
        sys.exit(1)
    print(f"Exporting to {dst} ...")
    clean_dst(dst)

    for name in COPY_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, dst / name)

    for dir_name, extra in COPY_DIRS.items():
        src = ROOT / dir_name
        if src.exists():
            copy_tree(src, dst / dir_name, extra)

    print(f"\nExport complete: {dst}")


if __name__ == "__main__":
    dst = Path(sys.argv[1]) if len(sys.argv) >= 2 else ROOT.parent / "Wafer_New"
    copy_clean(dst)
