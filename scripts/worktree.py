from __future__ import annotations

import _winapi
import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

BASE_BRANCH = "main_develop"
BRANCH_PREFIX = "wt/"
WORKTREES_DIR = ".worktrees"
SHARED_DIRS = [".venv", ".claude", "docs", ".sample", "extensions/.packages"]
SHARED_GLOBS = ["extensions/*/lib"]
RUNTIME_WRITTEN = ["_resources/translations.json"]


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def main_root() -> Path:
    common_dir = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=Path(__file__).parent)
    return Path(common_dir).parent


def shared_dirs(base: Path) -> list[Path]:
    dirs = [base / d for d in SHARED_DIRS]
    for pattern in SHARED_GLOBS:
        dirs.extend(base.glob(pattern))
    return [d for d in dirs if d.is_dir()]


def is_junction(path: Path) -> bool:
    try:
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:
        return False


def ensure_clean(tree: Path):
    git("checkout", "--", *RUNTIME_WRITTEN, cwd=tree)
    if git("status", "--porcelain", cwd=tree):
        sys.exit(f"{tree} has uncommitted changes.")


def worktree_paths(name: str) -> tuple[Path, Path, str]:
    root = main_root()
    return root, root / WORKTREES_DIR / name, BRANCH_PREFIX + name


def new(name: str):
    root, tree, branch = worktree_paths(name)
    git("worktree", "add", "-b", branch, str(tree), BASE_BRANCH, cwd=root)
    for source in shared_dirs(root):
        link = tree / source.relative_to(root)
        link.parent.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(source), str(link))
    print(tree)


def remove(name: str, force: bool = False):
    root, tree, branch = worktree_paths(name)
    if not force:
        ensure_clean(tree)
    for link in shared_dirs(tree):
        if is_junction(link):
            os.rmdir(link)
    git("worktree", "remove", *(["--force"] if force else []), str(tree), cwd=root)
    git("branch", "-D" if force else "-d", branch, cwd=root)
    print(f"Removed {tree}")


def finish(name: str):
    root, tree, branch = worktree_paths(name)
    ensure_clean(tree)
    current = git("symbolic-ref", "--short", "HEAD", cwd=root)
    if current != BASE_BRANCH:
        sys.exit(f"{root} is on {current}, not {BASE_BRANCH}.")
    git("merge", "--ff-only", branch, cwd=root)
    print(f"Merged {branch} into {BASE_BRANCH}")
    remove(name)


def main():
    parser = argparse.ArgumentParser(description=f"Task worktrees under {WORKTREES_DIR}/ on {BRANCH_PREFIX}<name> branches.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("new", help=f"Create a worktree from {BASE_BRANCH}").add_argument("name")
    commands.add_parser("finish", help=f"Fast-forward {BASE_BRANCH} to the branch, then remove the worktree").add_argument("name")
    remove_parser = commands.add_parser("remove", help="Remove the worktree and its branch without merging")
    remove_parser.add_argument("name")
    remove_parser.add_argument("--force", action="store_true", help="Discard uncommitted changes and unmerged commits")
    args = parser.parse_args()
    if args.command == "new":
        new(args.name)
    elif args.command == "finish":
        finish(args.name)
    else:
        remove(args.name, args.force)


if __name__ == "__main__":
    main()
