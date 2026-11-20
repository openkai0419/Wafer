import os
import stat
import subprocess

import pytest

from scripts import worktree


def run_git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture()
def root(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    run_git(root, "init", "-b", worktree.BASE_BRANCH)
    run_git(root, "config", "user.name", "test")
    run_git(root, "config", "user.email", "test@example.com")
    (root / ".gitignore").write_text(".worktrees/\n.venv/\ndocs/\n.claude/\n", encoding="utf-8")
    (root / "_resources").mkdir()
    (root / "_resources" / "translations.json").write_text("{}", encoding="utf-8")
    (root / "app.py").write_text("print(1)\n", encoding="utf-8")
    run_git(root, "add", ".gitignore", "_resources/translations.json", "app.py")
    run_git(root, "commit", "-m", "init")
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_text("venv", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "design.md").write_text("design", encoding="utf-8")
    (root / ".claude" / "rules").mkdir(parents=True)
    (root / ".claude" / "rules" / "git.md").write_text("rules", encoding="utf-8")
    return root


def shared_files_are_intact(root):
    return (root / ".venv" / "Scripts" / "python.exe").read_text(encoding="utf-8") == "venv" and (root / "docs" / "design.md").exists() and (root / ".claude" / "rules" / "git.md").exists()


def test_new_links_shared_folders_and_copies_rules_read_only(root):
    tree = worktree.new(root, "task")
    assert worktree.is_junction(tree / ".venv") and worktree.is_junction(tree / "docs")
    rule = tree / ".claude" / "rules" / "git.md"
    assert rule.read_text(encoding="utf-8") == "rules" and not rule.stat().st_mode & stat.S_IWRITE
    assert worktree.missing_links(root, tree) == []


def test_remove_deletes_the_worktree_and_branch_but_not_the_shared_folders(root):
    tree = worktree.new(root, "task")
    worktree.remove(root, "task")
    assert not tree.exists() and shared_files_are_intact(root)
    assert "wt/task" not in subprocess.run(["git", "branch"], cwd=root, capture_output=True, text=True).stdout
    assert worktree.leftovers(root) == []


def test_remove_touches_nothing_while_a_file_inside_is_open(root):
    tree = worktree.new(root, "task")
    with open(tree / "app.py", encoding="utf-8"):
        with pytest.raises(SystemExit, match="in use"):
            worktree.remove(root, "task")
    assert worktree.missing_links(root, tree) == [] and not worktree.removing_marker(root, "task").exists()
    worktree.remove(root, "task")
    assert not tree.exists() and shared_files_are_intact(root)


def test_failed_git_removal_puts_the_links_back_and_is_reported_until_it_is_removed(root, monkeypatch):
    tree = worktree.new(root, "task")
    real_git = worktree.git

    def failing_git(*args, cwd):
        if args[:2] == ("worktree", "remove"):
            raise worktree.GitError("git worktree remove failed:\nPermission denied")
        return real_git(*args, cwd=cwd)

    monkeypatch.setattr(worktree, "git", failing_git)
    with pytest.raises(SystemExit, match="links were put back"):
        worktree.remove(root, "task")
    monkeypatch.setattr(worktree, "git", real_git)
    assert worktree.missing_links(root, tree) == [] and shared_files_are_intact(root)
    assert worktree.leftovers(root) == ["task: removal did not finish. Close what uses it, then run `worktree.py remove task`."]
    worktree.remove(root, "task")
    assert not tree.exists() and worktree.leftovers(root) == [] and shared_files_are_intact(root)


def test_missing_links_are_reported_and_repaired(root, capsys):
    tree = worktree.new(root, "task")
    os.rmdir(tree / ".venv")
    assert worktree.leftovers(root) == ["task: missing .venv. Run `worktree.py repair task`."]
    worktree.new(root, "other")
    assert "WARNING: task: missing .venv" in capsys.readouterr().out
    worktree.repair(root, "task")
    assert worktree.leftovers(root) == []


def test_a_folder_that_is_no_longer_a_worktree_is_reported(root):
    (root / worktree.WORKTREES_DIR / "stale").mkdir(parents=True)
    assert worktree.leftovers(root) == ["stale: the folder is no longer a git worktree. Check it and delete it by hand."]


def test_a_worktree_in_another_folder_is_found_by_its_branch(root):
    tree = root / ".worktrees" / "old"
    run_git(root, "worktree", "add", "-b", "wt/old", str(tree), worktree.BASE_BRANCH)
    assert worktree.leftovers(root) == ["old: missing .venv, docs, .claude/rules. Run `worktree.py repair old`."]
    worktree.repair(root, "old")
    assert worktree.leftovers(root) == []
    worktree.remove(root, "old")
    assert not tree.exists() and shared_files_are_intact(root)


def test_a_deleted_folder_is_reported_and_remove_cleans_it_up(root):
    tree = worktree.new(root, "task")
    worktree.unlink_shared(tree)
    worktree.delete_copy(tree)
    assert worktree.leftovers(root) == ["task: the folder is gone. Run `worktree.py remove task`."]
    worktree.remove(root, "task")
    assert worktree.leftovers(root) == [] and "task" not in worktree.task_worktrees(root)


def test_finish_fast_forwards_and_removes(root):
    tree = worktree.new(root, "task")
    (tree / "app.py").write_text("print(2)\n", encoding="utf-8")
    run_git(tree, "commit", "-am", "change")
    worktree.finish(root, "task")
    assert (root / "app.py").read_text(encoding="utf-8") == "print(2)\n"
    assert not tree.exists() and shared_files_are_intact(root)


def test_remove_forgets_debug_profile_first(root, monkeypatch):
    tree = worktree.new(root, "task")
    (root / "debug").mkdir()
    (root / "debug" / "profile_setup.py").write_text("", encoding="utf-8")
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            return real_run(cmd, **kwargs)
        calls.append((cmd, kwargs.get("cwd"), tree.exists()))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(worktree.subprocess, "run", fake_run)
    worktree.remove(root, "task")
    assert calls == [([worktree.sys.executable, "-m", "debug.profile_setup", "--profile", "debug-tools", "forget", "debug-task"], root, True)]
    assert not tree.exists()


def test_remove_stops_when_forgetting_the_debug_profile_fails(root, monkeypatch):
    tree = worktree.new(root, "task")
    (root / "debug").mkdir()
    (root / "debug" / "profile_setup.py").write_text("", encoding="utf-8")
    real_run = subprocess.run
    monkeypatch.setattr(worktree.subprocess, "run", lambda cmd, **kwargs: real_run(cmd, **kwargs) if cmd[0] == "git" else subprocess.CompletedProcess(cmd, 1))
    with pytest.raises(SystemExit, match="debug profile"):
        worktree.remove(root, "task")
    assert tree.exists() and worktree.missing_links(root, tree) == []


@pytest.mark.parametrize("name", ["fix-v1.2", "tools", "Main", "template-build"])
def test_remove_skips_forget_for_names_that_never_have_a_debug_profile(root, monkeypatch, name):
    tree = worktree.new(root, name)
    (root / "debug").mkdir()
    (root / "debug" / "profile_setup.py").write_text("", encoding="utf-8")
    real_run = subprocess.run
    monkeypatch.setattr(worktree.subprocess, "run", lambda cmd, **kwargs: real_run(cmd, **kwargs) if cmd[0] == "git" else pytest.fail(f"unexpected subprocess {cmd}"))
    worktree.remove(root, name)
    assert not tree.exists()


def test_debug_profile_names_match_the_profile_rules():
    from debug.profile_setup import RESERVED_WORKTREE_NAMES
    from wafer.core.common.profile import PROFILE_PREFIX, same_profile, validate_profile_name

    assert worktree.RESERVED_DEBUG_NAMES == set(RESERVED_WORKTREE_NAMES)
    for name in ["task", "fix-v1.2", "a b", "x_y-Z9", "tools", "Tools", "MAIN", "Template-Build", ""]:
        try:
            profile = validate_profile_name(f"{PROFILE_PREFIX}{name}")
            reserved = any(same_profile(profile, f"{PROFILE_PREFIX}{r}") for r in RESERVED_WORKTREE_NAMES)
        except ValueError:
            profile, reserved = None, False
        assert worktree.has_debug_profile(name) == (profile is not None and not reserved), name


def test_finish_skips_forget_for_a_name_that_is_not_a_profile_suffix(root, monkeypatch):
    tree = worktree.new(root, "fix-v1.2")
    (tree / "app.py").write_text("print(2)\n", encoding="utf-8")
    run_git(tree, "commit", "-am", "change")
    (root / "debug").mkdir()
    (root / "debug" / "profile_setup.py").write_text("", encoding="utf-8")
    real_run = subprocess.run
    monkeypatch.setattr(worktree.subprocess, "run", lambda cmd, **kwargs: real_run(cmd, **kwargs) if cmd[0] == "git" else pytest.fail(f"unexpected subprocess {cmd}"))
    worktree.finish(root, "fix-v1.2")
    assert (root / "app.py").read_text(encoding="utf-8") == "print(2)\n"
    assert not tree.exists()


def test_remove_skips_forget_without_debug_tooling(root, monkeypatch):
    worktree.new(root, "task")
    real_run = subprocess.run
    monkeypatch.setattr(worktree.subprocess, "run", lambda cmd, **kwargs: real_run(cmd, **kwargs) if cmd[0] == "git" else pytest.fail("unexpected subprocess"))
    worktree.remove(root, "task")
