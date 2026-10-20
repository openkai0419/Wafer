from __future__ import annotations

import _winapi
import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

BASE_BRANCH = "main_develop"
BRANCH_PREFIX = "wt/"
WORKTREES_DIR = ".claude/worktrees"
SHARED_DIRS = [".venv", ".claude/commands", "docs", ".sample", "extensions/.packages"]
SHARED_GLOBS = ["extensions/*/lib"]
READ_ONLY_COPIES = [".claude/rules", ".claude/structure.md"]
RUNTIME_WRITTEN = ["_resources/translations.json"]
REMOVING_SUFFIX = ".removing"


class GitError(Exception):
    pass


def git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed:\n{(result.stderr or result.stdout).strip()}")
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


def files_under(path: Path) -> list[Path]:
    return [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]


def copy_read_only(source: Path, target: Path):
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for file in files_under(target):
        file.chmod(stat.S_IREAD)


def delete_copy(path: Path):
    if not path.exists():
        return
    for file in files_under(path):
        file.chmod(stat.S_IWRITE)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def link_shared(root: Path, tree: Path):
    for source in shared_dirs(root):
        link = tree / source.relative_to(root)
        if not is_junction(link):
            link.parent.mkdir(parents=True, exist_ok=True)
            _winapi.CreateJunction(str(source), str(link))
    for relative in READ_ONLY_COPIES:
        if (root / relative).exists() and not (tree / relative).exists():
            copy_read_only(root / relative, tree / relative)


def unlink_shared(tree: Path):
    for relative in READ_ONLY_COPIES:
        delete_copy(tree / relative)
    for link in shared_dirs(tree):
        if is_junction(link):
            os.rmdir(link)


def missing_links(root: Path, tree: Path) -> list[str]:
    links = [source.relative_to(root) for source in shared_dirs(root) if not is_junction(tree / source.relative_to(root))]
    copies = [Path(relative) for relative in READ_ONLY_COPIES if (root / relative).exists() and not (tree / relative).exists()]
    return [path.as_posix() for path in links + copies]


def ensure_unused(tree: Path):
    probe = tree.with_name(tree.name + ".probe")
    try:
        tree.rename(probe)
    except OSError as error:
        sys.exit(f"{tree} is in use ({error.strerror}). Close the apps, terminals and editors that use it, then run again. Nothing was removed.")
    probe.rename(tree)


def ensure_clean(tree: Path):
    git("checkout", "--", *RUNTIME_WRITTEN, cwd=tree)
    if git("status", "--porcelain", cwd=tree):
        sys.exit(f"{tree} has uncommitted changes.")


def worktrees(root: Path) -> list[tuple[Path, str]]:
    found = []
    for entry in git("worktree", "list", "--porcelain", cwd=root).split("\n\n"):
        fields = dict(line.split(" ", 1) for line in entry.splitlines() if " " in line)
        if "worktree" in fields:
            found.append((Path(fields["worktree"]), fields.get("branch", "").removeprefix("refs/heads/")))
    return found


def task_worktrees(root: Path) -> dict[str, Path]:
    return {branch.removeprefix(BRANCH_PREFIX): tree for tree, branch in worktrees(root) if branch.startswith(BRANCH_PREFIX)}


def existing_worktree(root: Path, name: str) -> Path:
    tree = task_worktrees(root).get(name)
    if tree is None:
        sys.exit(f"No worktree is on {BRANCH_PREFIX}{name}.")
    return tree


def removing_marker(root: Path, name: str) -> Path:
    return root / WORKTREES_DIR / (name + REMOVING_SUFFIX)


def leftovers(root: Path) -> list[str]:
    base = root / WORKTREES_DIR
    unfinished = {marker.name.removesuffix(REMOVING_SUFFIX) for marker in base.glob("*" + REMOVING_SUFFIX)}
    problems = [f"{name}: removal did not finish. Close what uses it, then run `worktree.py remove {name}`." for name in sorted(unfinished)]
    for name, tree in sorted(task_worktrees(root).items()):
        if name in unfinished:
            continue
        if not tree.exists():
            problems.append(f"{name}: the folder is gone. Run `worktree.py remove {name}`.")
        elif missing := missing_links(root, tree):
            problems.append(f"{name}: missing {', '.join(missing)}. Run `worktree.py repair {name}`.")
    registered = {tree.resolve() for tree, _ in worktrees(root)}
    if base.is_dir():
        for folder in sorted(path for path in base.iterdir() if path.is_dir() and path.name not in unfinished and path.resolve() not in registered):
            problems.append(f"{folder.name}: the folder is no longer a git worktree. Check it and delete it by hand.")
    return problems


def new(root: Path, name: str) -> Path:
    for problem in leftovers(root):
        print(f"WARNING: {problem}")
    tree = root / WORKTREES_DIR / name
    git("worktree", "add", "-b", BRANCH_PREFIX + name, str(tree), BASE_BRANCH, cwd=root)
    link_shared(root, tree)
    print(tree)
    return tree


def repair(root: Path, name: str):
    tree = existing_worktree(root, name)
    link_shared(root, tree)
    print(f"Repaired {tree}")


def remove(root: Path, name: str, force: bool = False):
    tree, branch, marker = task_worktrees(root).get(name), BRANCH_PREFIX + name, removing_marker(root, name)
    if tree is not None and tree.exists():
        if not force:
            ensure_clean(tree)
        ensure_unused(tree)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"worktree.py remove {name}\n", encoding="utf-8")
        unlink_shared(tree)
        try:
            git("worktree", "remove", *(["--force"] if force else []), str(tree), cwd=root)
        except GitError as error:
            if tree.exists():
                link_shared(root, tree)
            sys.exit(f"{error}\nThe links were put back. Close what uses {tree}, then run `worktree.py remove {name}` again (--force if it reports changes).")
    elif tree is not None:
        git("worktree", "prune", cwd=root)
    elif not marker.exists():
        sys.exit(f"No worktree is on {branch}.")
    git("branch", "-D" if force else "-d", branch, cwd=root)
    marker.unlink(missing_ok=True)
    print(f"Removed {tree or name}")


def finish(root: Path, name: str):
    tree = existing_worktree(root, name)
    ensure_clean(tree)
    current = git("symbolic-ref", "--short", "HEAD", cwd=root)
    if current != BASE_BRANCH:
        sys.exit(f"{root} is on {current}, not {BASE_BRANCH}.")
    git("merge", "--ff-only", BRANCH_PREFIX + name, cwd=root)
    print(f"Merged {BRANCH_PREFIX + name} into {BASE_BRANCH}")
    remove(root, name)


def main():
    parser = argparse.ArgumentParser(description=f"Task worktrees under {WORKTREES_DIR}/ on {BRANCH_PREFIX}<name> branches.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("new", help=f"Create a worktree from {BASE_BRANCH}").add_argument("name")
    commands.add_parser("finish", help=f"Fast-forward {BASE_BRANCH} to the branch, then remove the worktree").add_argument("name")
    remove_parser = commands.add_parser("remove", help="Remove the worktree and its branch without merging")
    remove_parser.add_argument("name")
    remove_parser.add_argument("--force", action="store_true", help="Discard uncommitted changes and unmerged commits")
    commands.add_parser("repair", help="Put back the links and read-only copies of a worktree").add_argument("name")
    args = parser.parse_args()
    try:
        root = main_root()
        if args.command == "new":
            new(root, args.name)
        elif args.command == "finish":
            finish(root, args.name)
        elif args.command == "repair":
            repair(root, args.name)
        else:
            remove(root, args.name, args.force)
    except GitError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
