from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COPY_FILES = [
    '.gitignore',
    'LICENSE',
    'main.py',
    'main.bat',
    'main.spec',
    'pyproject.toml',
    'requirements.txt',
    'requirements-dev.txt',
    'setup.bat',
    'CHANGELOG.md',
    'README.md',
]

COPY_DIRS: dict[str, set[str]] = {
    'wafer': set(),
    'extensions': {'lib'},
    'tests': set(),
    '_resources': set(),
    'scripts': set(),
}

EXCLUDE_DIRS = {
    '__pycache__', '.pytest_cache', '.prototypes',
    '.packages', '.shared_packages',
    '.venv', 'venv', 'env',
    'build', 'dist', '.eggs',
}

EXCLUDE_EXTS = {'.pyc', '.pyo', '.pyd', '.db', '.db-shm', '.db-wal', '.ini'}


def clean_dst(dst: Path):
    if not dst.exists():
        dst.mkdir(parents=True)
        return
    for child in list(dst.iterdir()):
        if child.name == '.git':
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _should_skip(rel: Path, extra_exclude: set[str]) -> bool:
    parts = set(rel.parts)
    if parts & EXCLUDE_DIRS or parts & extra_exclude:
        return True
    if rel.suffix in EXCLUDE_EXTS:
        return True
    return False


def copy_tree(src: Path, dst: Path, extra_exclude: set[str]):
    for item in src.rglob('*'):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        if _should_skip(rel, extra_exclude):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def copy_clean(dst: Path):
    print(f'Exporting to {dst} ...')
    clean_dst(dst)

    for name in COPY_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, dst / name)

    for dir_name, extra in COPY_DIRS.items():
        src = ROOT / dir_name
        if src.exists():
            copy_tree(src, dst / dir_name, extra)

    print(f'\nExport complete: {dst}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: python {Path(__file__).name} <destination>')
        sys.exit(1)
    copy_clean(Path(sys.argv[1]))
