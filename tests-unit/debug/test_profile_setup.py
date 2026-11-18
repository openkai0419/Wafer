import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

import wafer.core.common.paths as paths
from debug import profile_setup
from debug.profile_setup import (
    build_template,
    ensure_profile,
    forget_profile,
    launch_process,
    main,
    main_root_of,
    profile_name_for,
    sample_db_setup,
    schema_hash,
    stop_profile,
    wait_indexed,
)
from wafer.core.common.paths import normalize_path, profile_data_root, scratch_root
from wafer.core.db.path_scope import compile_ignore_patterns, path_in_scope
from wafer.core.db.setting_db import SettingDB
from wafer.core.platform.process import AppProcess
from wafer.core.platform.process_lock import file_lock


def make_checkout(path: Path) -> Path:
    (path / "wafer" / "core" / "db").mkdir(parents=True)
    (path / "main.py").write_text("", encoding="utf-8")
    (path / "wafer" / "core" / "db" / "file_db.py").write_text('_TABLES = ("CREATE TABLE a (x TEXT)",)\n', encoding="utf-8")
    (path / "wafer" / "core" / "db" / "setting_db.py").write_text('SQL = "CREATE TABLE b (y TEXT)"\n', encoding="utf-8")
    return path


def make_sample(root: Path, val_count: int = 30) -> Path:
    for folder in ("archive", "audio", "coco/train2017", "coco/unlabeled2017", "coco/val2017"):
        (root / folder).mkdir(parents=True)
    for i in range(val_count):
        Image.new("RGB", (8, 8), (i * 5 % 256, 0, 0)).save(root / "coco" / "val2017" / f"{i:012d}.jpg")
    Image.new("RGB", (8, 8)).save(root / "coco" / "train2017" / "000000000001.jpg")
    (root / "coco" / "val2017.zip").write_bytes(b"zip")
    Image.new("RGB", (8, 8)).save(root / "elephant.gif")
    return root


class _FakePlatformDirs:
    base = ""

    def __init__(self, appname=None):
        self.user_data_dir = _FakePlatformDirs.base
        self.user_config_dir = _FakePlatformDirs.base


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    base = tmp_path / "appdata"
    base.mkdir()
    monkeypatch.setattr(_FakePlatformDirs, "base", str(base))
    monkeypatch.setattr(paths, "PlatformDirs", _FakePlatformDirs)
    return base


@pytest.fixture
def sample(tmp_path, monkeypatch):
    root = make_sample(tmp_path / "sample")
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(root))
    return root


def test_profile_name_for_checkout(tmp_path):
    main_root = make_checkout(tmp_path / "Repo")
    wt = make_checkout(main_root / ".claude" / "worktrees" / "fm-v2")
    assert profile_name_for(main_root) == "debug-main"
    assert profile_name_for(Path(str(wt).upper() + "\\")) == "debug-fm-v2"
    with pytest.raises(ValueError):
        profile_name_for(wt / "wafer")
    with pytest.raises(ValueError):
        profile_name_for(tmp_path / "elsewhere")
    with pytest.raises(ValueError):
        profile_name_for(make_checkout(main_root / ".claude" / "worktrees" / "a.b"))


def test_main_root_of_worktree_and_nested_worktree(tmp_path):
    main_root = make_checkout(tmp_path / "Repo")
    wt = make_checkout(main_root / ".claude" / "worktrees" / "task")
    nested = make_checkout(wt / ".claude" / "worktrees" / "inner")
    assert os.path.normcase(main_root_of(wt)) == os.path.normcase(os.path.realpath(main_root))
    assert os.path.normcase(main_root_of(main_root)) == os.path.normcase(os.path.realpath(main_root))
    with pytest.raises(ValueError):
        main_root_of(nested)
    with pytest.raises(ValueError):
        profile_name_for(nested)
    plain = main_root / ".claude" / "worktrees" / "plain"
    plain.mkdir()
    with pytest.raises(ValueError):
        profile_name_for(plain)


def test_schema_hash_changes_only_with_table_definitions(tmp_path):
    checkout = make_checkout(tmp_path / "Repo")
    file_db = checkout / "wafer" / "core" / "db" / "file_db.py"
    setting_db = checkout / "wafer" / "core" / "db" / "setting_db.py"
    first = schema_hash(checkout)
    assert len(first) == 12 and all(c in "0123456789abcdef" for c in first)

    file_db.write_text('import os\n\n_TABLES = ("CREATE TABLE a (x TEXT)",)\n\n\ndef f():\n    return "SELECT 1"\n', encoding="utf-8")
    assert schema_hash(checkout) == first

    file_db.write_text('_TABLES = ("CREATE TABLE a (x TEXT, z INTEGER)",)\n', encoding="utf-8")
    second = schema_hash(checkout)
    assert second != first

    setting_db.write_text('SQL = "CREATE TABLE b (y TEXT, w TEXT)"\n', encoding="utf-8")
    assert schema_hash(checkout) not in (first, second)


def test_sample_db_setup_registers_only_sample(tmp_path, sample):
    root = tmp_path / "profile"
    sample_db_setup(root)

    parents, ignores, patterns = SettingDB(str(root / "dirs" / "sample.db")).get_all_folder_settings()
    assert parents == [normalize_path(sample)]
    assert ignores == [normalize_path(sample / "coco" / "train2017"), normalize_path(sample / "coco" / "unlabeled2017")]
    pattern_re = compile_ignore_patterns(patterns)

    def in_scope(path):
        return path_in_scope(normalize_path(path), parents, ignores, pattern_re)

    assert in_scope(sample / "coco" / "val2017" / "000000000000.jpg")
    assert in_scope(sample / "elephant.gif")
    assert not in_scope(sample / "coco" / "train2017" / "000000000001.jpg")
    assert not in_scope(sample / "coco" / "unlabeled2017" / "x.jpg")
    assert not in_scope(sample / "coco" / "val2017.zip")
    assert not in_scope(tmp_path / "elsewhere.jpg")


def _fake_template(template: Path):
    sample_db_setup(template)
    (template / "data").mkdir()
    (template / "data" / "sample.db").write_bytes(b"db")
    (template / "settings.ini").write_text("from-template", encoding="utf-8")


def test_ensure_profile_copies_template_and_prepares_scratch(tmp_path, monkeypatch, app_data, sample):
    main_root = make_checkout(tmp_path / "Repo")
    wt = make_checkout(main_root / ".claude" / "worktrees" / "t1")
    builds = []

    def fake_build(checkout, *, on_progress):
        target = profile_setup.template_dir(schema_hash(checkout))
        _fake_template(target)
        builds.append(checkout)
        return target

    stops = []
    monkeypatch.setattr(profile_setup, "build_template", fake_build)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: stops.append(profile))
    progress = []

    assert ensure_profile(wt, fresh=False, on_progress=progress.append) == "debug-t1"
    root = profile_data_root("debug-t1")
    assert root == app_data / "Wafer-debug" / "debug-t1"
    assert (root / "settings.ini").read_text(encoding="utf-8") == "from-template"
    assert (root / "data" / "sample.db").read_bytes() == b"db"
    scratch = scratch_root("debug-t1")
    expected = sorted(p.name for p in (sample / "coco" / "val2017").iterdir())[:24]
    assert sorted(p.name for p in scratch.iterdir()) == expected
    parents = SettingDB(str(root / "dirs" / "sample.db")).get_all_parent_folders()
    assert parents == [normalize_path(sample), normalize_path(scratch)]
    assert len(builds) == 1 and progress

    (root / "settings.ini").write_text("changed", encoding="utf-8")
    assert ensure_profile(wt, fresh=False, on_progress=progress.append) == "debug-t1"
    assert (root / "settings.ini").read_text(encoding="utf-8") == "changed"
    assert len(builds) == 1

    assert ensure_profile(wt, fresh=True, on_progress=progress.append) == "debug-t1"
    assert (root / "settings.ini").read_text(encoding="utf-8") == "from-template"
    assert len(list(scratch.iterdir())) == 24
    assert SettingDB(str(root / "dirs" / "sample.db")).get_all_parent_folders() == [normalize_path(sample), normalize_path(scratch)]
    assert len(builds) == 1
    assert stops == ["debug-t1"]


def test_ensure_profile_copies_every_image_when_the_sample_has_few(tmp_path, monkeypatch, app_data):
    sample = make_sample(tmp_path / "small", val_count=3)
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
    checkout = make_checkout(tmp_path / "Repo")

    def fake_build(checkout, *, on_progress):
        target = profile_setup.template_dir(schema_hash(checkout))
        _fake_template(target)
        return target

    monkeypatch.setattr(profile_setup, "build_template", fake_build)
    assert ensure_profile(checkout, fresh=False, on_progress=lambda text: None) == "debug-main"
    assert len(list(scratch_root("debug-main").iterdir())) == 3


def test_build_template_copies_the_indexed_profile_without_runtime_state(tmp_path, monkeypatch, app_data, sample):
    checkout = make_checkout(tmp_path / "Repo")
    calls = []

    def fake_launch(checkout_arg, profile):
        calls.append(("launch", profile))
        root = profile_data_root(profile)
        assert SettingDB(str(root / "dirs" / "sample.db")).get_all_parent_folders() == [normalize_path(sample)]
        for rel in (".temp/x.lock", ".log/1.log", "ipc/broker.json", "data/sample.db", ".cache/thumb.bin"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(rel, encoding="utf-8")
        return 1234

    monkeypatch.setattr(profile_setup, "launch_process", fake_launch)
    monkeypatch.setattr(profile_setup, "wait_indexed", lambda profile, timeout: calls.append(("wait", profile)))
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: calls.append(("stop", profile)))
    progress = []

    template = build_template(checkout, on_progress=progress.append)

    assert template == app_data / "Wafer-debug" / "_template" / schema_hash(checkout)
    assert (template / "data" / "sample.db").is_file()
    assert (template / ".cache" / "thumb.bin").is_file()
    assert (template / "dirs" / "sample.db").is_file()
    for excluded in (".temp", ".log", "ipc"):
        assert not (template / excluded).exists()
    assert not profile_data_root("debug-template-build").exists()
    assert ("launch", "debug-template-build") in calls and ("wait", "debug-template-build") in calls
    assert calls[-1] == ("stop", "debug-template-build")
    assert progress

    calls.clear()
    assert build_template(checkout, on_progress=progress.append) == template
    assert calls == []


def test_build_template_stops_the_build_profile_when_indexing_fails(tmp_path, monkeypatch, app_data, sample):
    checkout = make_checkout(tmp_path / "Repo")
    stops = []

    def fail_wait(profile, timeout):
        raise TimeoutError("not indexed")

    monkeypatch.setattr(profile_setup, "launch_process", lambda checkout, profile: 1)
    monkeypatch.setattr(profile_setup, "wait_indexed", fail_wait)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: stops.append(profile))

    with pytest.raises(TimeoutError):
        build_template(checkout, on_progress=lambda text: None)
    assert stops[-1] == "debug-template-build"
    assert not profile_setup.template_dir(schema_hash(checkout)).exists()


def _make_file_db(path: Path, sources: int, statuses: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sources (source TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE collection_status (source TEXT, collector TEXT, status TEXT DEFAULT 'pending')")
    con.executemany("INSERT INTO sources VALUES (?)", [(f"s{i}",) for i in range(sources)])
    con.executemany("INSERT INTO collection_status VALUES (?, 'c', ?)", [(f"s{i}", s) for i, s in enumerate(statuses)])
    con.commit()
    con.close()


@pytest.fixture
def fast_wait(monkeypatch):
    monkeypatch.setattr(profile_setup, "INDEX_SETTLE_SECONDS", 0.3)
    monkeypatch.setattr(profile_setup, "INDEX_POLL_SECONDS", 0.05)
    monkeypatch.setattr(AppProcess, "list_profile_processes", classmethod(lambda cls, profile: [object()]))


def test_wait_indexed_returns_once_sources_are_collected(app_data, fast_wait):
    _make_file_db(profile_data_root("debug-x") / "data" / "sample.db", 2, ["ok", "ok"])
    wait_indexed("debug-x", timeout=5.0)


@pytest.mark.parametrize(
    ("sources", "statuses"),
    [(0, []), (2, ["ok", "pending"]), (2, ["ok", "dispatched"])],
)
def test_wait_indexed_times_out_while_indexing_is_unfinished(app_data, fast_wait, sources, statuses):
    _make_file_db(profile_data_root("debug-x") / "data" / "sample.db", sources, statuses)
    with pytest.raises(TimeoutError):
        wait_indexed("debug-x", timeout=0.6)


def test_wait_indexed_times_out_without_a_database(app_data, fast_wait):
    with pytest.raises(TimeoutError):
        wait_indexed("debug-x", timeout=0.3)


def test_wait_indexed_fails_when_the_profile_exits(app_data, fast_wait, monkeypatch):
    monkeypatch.setattr(AppProcess, "list_profile_processes", classmethod(lambda cls, profile: []))
    with pytest.raises(RuntimeError):
        wait_indexed("debug-x", timeout=5.0)


class _FakeNode:
    instances = []

    def __init__(self, role, db="", *, profile=None):
        self.role, self.profile, self.sent, self.stopped = role, profile, [], False
        _FakeNode.instances.append(self)

    def start(self):
        pass

    def wait_registered(self, timeout=5.0):
        return True

    def send(self, topic, payload=None, *, dst="ALL"):
        self.sent.append((topic, dst))

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_node(monkeypatch):
    _FakeNode.instances = []
    monkeypatch.setattr(profile_setup, "Node", _FakeNode)
    monkeypatch.setattr(profile_setup, "STOP_POLL_SECONDS", 0.01)
    return _FakeNode


def test_stop_profile_asks_the_tray_to_quit_all(monkeypatch, fake_node):
    listings = iter([[object()], [object()], []])
    monkeypatch.setattr(AppProcess, "list_profile_processes", classmethod(lambda cls, profile: next(listings)))
    terminated = []
    monkeypatch.setattr(AppProcess, "terminate_tree", classmethod(lambda cls, procs, **kw: terminated.append(procs)))

    stop_profile("debug-x", timeout=5.0)

    node = fake_node.instances[0]
    assert (node.role, node.profile) == ("debug", "debug-x")
    assert node.sent == [("app.quit_all", "tray")]
    assert node.stopped
    assert terminated == []


def test_stop_profile_terminates_what_is_left(monkeypatch, fake_node):
    survivor = object()
    monkeypatch.setattr(AppProcess, "list_profile_processes", classmethod(lambda cls, profile: [survivor]))
    terminated = []
    monkeypatch.setattr(AppProcess, "terminate_tree", classmethod(lambda cls, procs, **kw: terminated.append(procs)))

    stop_profile("debug-x", timeout=0.1)

    assert terminated == [[survivor]]


def test_stop_profile_does_nothing_when_nothing_runs(monkeypatch, fake_node):
    monkeypatch.setattr(AppProcess, "list_profile_processes", classmethod(lambda cls, profile: []))
    stop_profile("debug-x")
    assert fake_node.instances == []


def test_stop_profile_rejects_a_non_debug_profile():
    with pytest.raises(ValueError):
        stop_profile("normal")


def test_forget_profile_stops_then_deletes_the_profile(monkeypatch, app_data):
    root = profile_data_root("debug-x")
    (root / "data").mkdir(parents=True)
    other = profile_data_root("debug-y")
    other.mkdir(parents=True)
    events = []
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: events.append((profile, root.exists())))

    forget_profile("debug-x")

    assert events == [("debug-x", True)]
    assert not root.exists()
    assert other.exists()


def test_launch_process_runs_the_checkout_main_with_the_profile(tmp_path, monkeypatch):
    checkout = make_checkout(tmp_path / "Repo")
    spawned = {}

    class _Proc:
        pid = 4321

    def fake_spawn(cmd, *, extra_env=None, **popen_kwargs):
        spawned["cmd"], spawned["kwargs"] = cmd, popen_kwargs
        return _Proc()

    monkeypatch.setattr(AppProcess, "spawn", staticmethod(fake_spawn))

    assert launch_process(checkout, "debug-main") == 4321
    cmd = spawned["cmd"]
    assert cmd[0] == AppProcess.base_command()[0]
    assert os.path.isabs(cmd[1]) and os.path.normcase(cmd[1]) == os.path.normcase(os.path.realpath(checkout / "main.py"))
    assert cmd[2:] == ["--profile", "debug-main"]
    assert os.path.normcase(spawned["kwargs"]["cwd"]) == os.path.normcase(os.path.realpath(checkout))


def test_cli_launch_stops_prepares_and_starts_the_profile(tmp_path, monkeypatch):
    checkout = make_checkout(tmp_path / "Repo")
    events = []
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: events.append(("stop", profile)))
    monkeypatch.setattr(profile_setup, "ensure_profile", lambda c, *, fresh, on_progress: events.append(("ensure", fresh)) or "debug-main")
    monkeypatch.setattr(profile_setup, "launch_process", lambda c, profile: events.append(("launch", profile)) or 99)

    assert main(["launch", "--checkout", str(checkout), "--fresh"]) == 0
    assert events == [("stop", "debug-main"), ("ensure", True), ("launch", "debug-main")]


def test_cli_rebuild_template_replaces_the_current_template(tmp_path, monkeypatch, app_data):
    checkout = make_checkout(tmp_path / "Repo")
    old = profile_setup.template_dir(schema_hash(checkout))
    (old / "stale").mkdir(parents=True)
    built = []

    def fake_build(c, *, on_progress):
        built.append(old.exists())
        return old

    monkeypatch.setattr(profile_setup, "build_template", fake_build)

    assert main(["rebuild-template", "--checkout", str(checkout)]) == 0
    assert built == [False]


def test_cli_accepts_the_tooling_profile_before_or_after_the_command(tmp_path, monkeypatch):
    checkout = make_checkout(tmp_path / "Repo")
    events = []
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: events.append(profile))
    monkeypatch.setattr(profile_setup, "ensure_profile", lambda c, *, fresh, on_progress: "debug-main")
    monkeypatch.setattr(profile_setup, "launch_process", lambda c, profile: 99)

    assert main(["--profile", "debug-tools", "launch", "--checkout", str(checkout)]) == 0
    assert main(["launch", "--checkout", str(checkout), "--profile", "debug-tools"]) == 0
    assert main(["stop", "debug-main", "--profile", "debug-tools"]) == 0
    assert events == ["debug-main", "debug-main", "debug-main"]
    with pytest.raises(SystemExit):
        main(["launch", "--checkout", str(checkout), "--profile", "debug-main"])
    assert "--profile debug-tools" in profile_setup._parser().format_help()


def test_ensure_profile_works_from_the_tooling_profile(tmp_path, monkeypatch, app_data, sample):
    from wafer.core.common.profile import current_profile

    checkout = make_checkout(tmp_path / "Repo")
    monkeypatch.setattr(profile_setup, "build_template", _fake_build)
    monkeypatch.setattr(sys, "argv", ["-m", "--profile", "debug-tools"])
    current_profile.cache_clear()
    try:
        assert current_profile() == "debug-tools"
        assert ensure_profile(checkout, fresh=False, on_progress=lambda text: None) == "debug-main"
    finally:
        current_profile.cache_clear()
    parents = SettingDB(str(profile_data_root("debug-main") / "dirs" / "sample.db")).get_all_parent_folders()
    assert normalize_path(scratch_root("debug-main")) in parents


def test_cli_reports_an_invalid_checkout(tmp_path):
    assert main(["launch", "--checkout", str(tmp_path / "missing")]) != 0
    assert main(["stop", "normal"]) != 0


@pytest.mark.parametrize("name", ["main", "Main", "template-build", "tools", "Tools"])
def test_profile_name_for_rejects_reserved_worktree_names(tmp_path, name):
    main_root = make_checkout(tmp_path / "Repo")
    wt = make_checkout(main_root / ".claude" / "worktrees" / name)
    with pytest.raises(ValueError, match="reserved"):
        profile_name_for(wt)


def test_sample_db_setup_prunes_ignored_folders_from_the_scan(tmp_path, monkeypatch, sample):
    import wafer.app.indexer.scanner as scanner_module
    from wafer.app.indexer.scanner import DirectoryScanner
    from wafer.core.db.file_db import FileDB

    root = tmp_path / "profile"
    sample_db_setup(root)
    parents, ignores, patterns = SettingDB(str(root / "dirs" / "sample.db")).get_all_folder_settings()
    db_path = tmp_path / "file.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.close()
    scanner = DirectoryScanner(db_path, MagicMock(), MagicMock(), MagicMock(), None)
    scanner.set_exclusions(ignores, patterns)
    scanned = []
    real_scandir = os.scandir

    def recording_scandir(path):
        scanned.append(normalize_path(path))
        return real_scandir(path)

    monkeypatch.setattr(scanner_module.os, "scandir", recording_scandir)
    found = {path for path, _ in scanner._scan_directory(parents[0])}

    assert normalize_path(sample / "coco") in scanned
    assert not any("/coco/train2017" in path or "/coco/unlabeled2017" in path for path in scanned)
    assert normalize_path(sample / "coco" / "val2017" / "000000000000.jpg") in found
    assert normalize_path(sample / "elephant.gif") in found
    assert normalize_path(sample / "coco" / "val2017.zip") not in found


def _fake_build(checkout, *, on_progress):
    target = profile_setup.template_dir(schema_hash(checkout))
    _fake_template(target)
    return target


def _fail_prepare(profile, staging):
    raise OSError("disk full")


def test_interrupted_ensure_profile_is_rebuilt_by_the_next_launch(tmp_path, monkeypatch, app_data, sample):
    checkout = make_checkout(tmp_path / "Repo")
    monkeypatch.setattr(profile_setup, "build_template", _fake_build)
    real_prepare = profile_setup._prepare_scratch
    monkeypatch.setattr(profile_setup, "_prepare_scratch", _fail_prepare)
    with pytest.raises(OSError):
        ensure_profile(checkout, fresh=False, on_progress=lambda text: None)

    monkeypatch.setattr(profile_setup, "_prepare_scratch", real_prepare)
    assert ensure_profile(checkout, fresh=False, on_progress=lambda text: None) == "debug-main"
    root = profile_data_root("debug-main")
    scratch = scratch_root("debug-main")
    assert len(list(scratch.iterdir())) == 24
    assert SettingDB(str(root / "dirs" / "sample.db")).get_all_parent_folders() == [normalize_path(sample), normalize_path(scratch)]


def test_interrupted_fresh_ensure_profile_keeps_the_previous_profile(tmp_path, monkeypatch, app_data, sample):
    checkout = make_checkout(tmp_path / "Repo")
    monkeypatch.setattr(profile_setup, "build_template", _fake_build)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: None)
    ensure_profile(checkout, fresh=False, on_progress=lambda text: None)
    root = profile_data_root("debug-main")
    (root / "settings.ini").write_text("in use", encoding="utf-8")

    monkeypatch.setattr(profile_setup, "_prepare_scratch", _fail_prepare)
    with pytest.raises(OSError):
        ensure_profile(checkout, fresh=True, on_progress=lambda text: None)

    assert (root / "settings.ini").read_text(encoding="utf-8") == "in use"
    assert len(list(scratch_root("debug-main").iterdir())) == 24
    assert ensure_profile(checkout, fresh=False, on_progress=lambda text: None) == "debug-main"
    assert (root / "settings.ini").read_text(encoding="utf-8") == "in use"


def test_fresh_ensure_profile_keeps_a_profile_it_cannot_move_away(tmp_path, monkeypatch, app_data, sample):
    checkout = make_checkout(tmp_path / "Repo")
    monkeypatch.setattr(profile_setup, "build_template", _fake_build)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile, timeout=15.0: None)
    ensure_profile(checkout, fresh=False, on_progress=lambda text: None)
    root = profile_data_root("debug-main")
    (root / "settings.ini").write_text("in use", encoding="utf-8")
    real_rename = Path.rename

    def held_rename(self, target):
        if self == root:
            raise PermissionError("a file in the profile is open")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", held_rename)
    with pytest.raises(PermissionError):
        ensure_profile(checkout, fresh=True, on_progress=lambda text: None)

    monkeypatch.setattr(Path, "rename", real_rename)
    assert (root / "settings.ini").read_text(encoding="utf-8") == "in use"
    assert ensure_profile(checkout, fresh=False, on_progress=lambda text: None) == "debug-main"
    assert (root / "settings.ini").read_text(encoding="utf-8") == "in use"


def test_ensure_profile_waits_for_another_session_preparing_the_profile(tmp_path, monkeypatch, app_data, sample):
    checkout = make_checkout(tmp_path / "Repo")
    monkeypatch.setattr(profile_setup, "build_template", _fake_build)
    monkeypatch.setattr(profile_setup, "PROFILE_LOCK_TIMEOUT", 0.2)
    with file_lock(str(app_data / "Wafer-debug" / "debug-main.lock")):
        with pytest.raises(TimeoutError):
            ensure_profile(checkout, fresh=False, on_progress=lambda text: None)
    assert not profile_data_root("debug-main").exists()


def _write_template(target: Path):
    (target / "data").mkdir(parents=True)
    for name in ("a.bin", "b.bin", "c.bin"):
        (target / "data" / name).write_bytes(b"x")


def test_rebuild_template_never_leaves_a_half_deleted_template(tmp_path, monkeypatch, app_data):
    checkout = make_checkout(tmp_path / "Repo")
    target = profile_setup.template_dir(schema_hash(checkout))
    _write_template(target)

    def partial_rmtree(path, *args, **kwargs):
        next(Path(path).rglob("*.bin")).unlink()
        raise PermissionError("a file is open in another session")

    built = []

    def fake_build(c, *, on_progress):
        built.append(target.exists())
        return target

    monkeypatch.setattr(profile_setup, "build_template", fake_build)
    monkeypatch.setattr(profile_setup.shutil, "rmtree", partial_rmtree)

    profile_setup.rebuild_template(checkout, on_progress=lambda text: None)

    assert built == [False]
    assert not target.exists()


def test_rebuild_template_keeps_the_template_it_cannot_move_away(tmp_path, monkeypatch, app_data):
    checkout = make_checkout(tmp_path / "Repo")
    target = profile_setup.template_dir(schema_hash(checkout))
    _write_template(target)
    real_rename = Path.rename

    def held_rename(self, new):
        if self == target:
            raise PermissionError("a file in the template is open")
        return real_rename(self, new)

    def must_not_build(c, *, on_progress):
        raise AssertionError("must not rebuild while the old template is still in place")

    monkeypatch.setattr(Path, "rename", held_rename)
    monkeypatch.setattr(profile_setup, "build_template", must_not_build)

    with pytest.raises(PermissionError):
        profile_setup.rebuild_template(checkout, on_progress=lambda text: None)

    assert sorted(p.name for p in (target / "data").iterdir()) == ["a.bin", "b.bin", "c.bin"]
