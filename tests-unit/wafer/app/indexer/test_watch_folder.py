import py_compile
import time
from unittest.mock import MagicMock, call


def test_compile():
    py_compile.compile("wafer/app/indexer/watch_folder.py")


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def _make_watcher():
    from wafer.app.indexer.watch_folder import FolderWatcher
    from wafer.app.indexer.path_scope import normalize_prefixes

    scheduler = MagicMock()
    writer = MagicMock()
    scanner = MagicMock()
    progress = MagicMock()
    wf = FolderWatcher(scheduler, writer, scanner, progress)
    wf.stop()
    wf._folders = normalize_prefixes(["."])
    return wf, scheduler, writer, scanner, progress


def _set_scope(wf, roots, ignores=()):
    from wafer.app.indexer.path_scope import normalize_prefixes

    wf._folders = normalize_prefixes([str(p) for p in roots])
    wf._ignore_paths = normalize_prefixes([str(p) for p in ignores])


def _collect_exec_calls(scheduler, scanner):
    rename_names = []
    delete_names = []
    update_paths = []
    for c in scheduler.submit.call_args_list:
        task = c[0][0]
        if task.name == "rename_paths":
            rename_names.append(task.name)
        elif task.name == "delete_sources":
            delete_names.append(task.name)
    for c in scanner.request_update.call_args_list:
        update_paths.append(sorted(c[0][0]))
    return rename_names, update_paths, delete_names


def _expire_pending_deletes(wf):
    from wafer.app.indexer.watch_folder import _MOVE_INFER_WINDOW

    if not wf._pending_deletes:
        return
    expired = time.monotonic() - _MOVE_INFER_WINDOW - 0.1
    for norm, (path, _) in list(wf._pending_deletes.items()):
        wf._pending_deletes[norm] = (path, expired)
    wf._flush(set(), set(), {}, created=set())


def test_flush_basic_rename():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), set(), {"A": "B"})
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == "rename_paths"


def test_flush_create_then_rename():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush({"A"}, set(), {"A": "B"})
    rename_names, update_paths, _ = _collect_exec_calls(scheduler, scanner)
    assert len(rename_names) == 1
    assert len(update_paths) == 1
    assert "B" in update_paths[0]


def test_flush_rename_then_delete(tmp_path):
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), {"B"}, {"A": "B"})
    rename_names, _, delete_names = _collect_exec_calls(scheduler, scanner)
    assert len(rename_names) == 1


def test_flush_only_changed():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush({"A", "B"}, set(), {})
    assert scanner.request_update.called
    assert not scheduler.submit.called


def test_flush_only_deleted():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), {"/nonexistent/file.png"}, {})
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == "delete_sources"
    task.run()
    writer.delete_source_trees.assert_called_once()


def test_flush_infers_move_from_delete_create(tmp_path):
    from wafer.app.indexer.watch_folder import _MOVE_INFER_WINDOW
    from wafer.utils.paths import normalize_path

    root = tmp_path / "watched"
    root.mkdir()
    old_path = root / "a.jpg"
    new_path = root / "sub" / "a.jpg"
    new_path.parent.mkdir()
    new_path.write_bytes(b"same")
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root])
    writer.infer_moved_sources.return_value = [(normalize_path(str(old_path)), normalize_path(str(new_path)))]

    wf._flush({str(new_path)}, {str(old_path)}, {}, created={str(new_path)})

    task = scheduler.submit.call_args[0][0]
    assert task.name == "rename_paths"
    task.run()
    writer.rename_paths.assert_called_once_with([(normalize_path(str(old_path)), normalize_path(str(new_path)))])
    assert not scanner.request_update.called
    assert normalize_path(str(old_path)) not in wf._pending_deletes
    assert _MOVE_INFER_WINDOW > 0


def test_flush_buffers_delete_until_move_window_expires(tmp_path):
    from wafer.app.indexer.watch_folder import _MOVE_INFER_WINDOW
    from wafer.utils.paths import normalize_path

    root = tmp_path / "watched"
    root.mkdir()
    old_path = root / "a.jpg"
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root])

    wf._flush(set(), {str(old_path)}, {}, created=set())

    assert not scheduler.submit.called
    assert normalize_path(str(old_path)) in wf._pending_deletes

    wf._pending_deletes[normalize_path(str(old_path))] = (str(old_path), time.monotonic() - _MOVE_INFER_WINDOW - 0.1)
    wf._flush(set(), set(), {}, created=set())

    task = scheduler.submit.call_args[0][0]
    assert task.name == "delete_sources"
    task.run()
    writer.delete_source_trees.assert_called_once()


def test_flush_updates_unmatched_create_while_delete_is_buffered(tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    old_path = root / "a.jpg"
    new_path = root / "b.jpg"
    new_path.write_bytes(b"new")
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root])
    writer.infer_moved_sources.return_value = []

    wf._flush({str(new_path)}, {str(old_path)}, {}, created={str(new_path)})

    assert not scheduler.submit.called
    scanner.request_update.assert_called_once_with([str(new_path)])


def test_flush_move_outside_scope_deletes_source(tmp_path):
    root = tmp_path / "watched"
    outside = tmp_path / "outside"
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root])

    wf._flush(set(), set(), {str(root / "a.jpg"): str(outside / "a.jpg")})

    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == "delete_sources"
    task.run()
    writer.delete_source_trees.assert_called_once()
    assert not scanner.request_update.called


def test_flush_move_into_ignored_deletes_source(tmp_path):
    root = tmp_path / "watched"
    ignored = root / "ignored"
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root], [ignored])

    wf._flush(set(), set(), {str(root / "a.jpg"): str(ignored / "a.jpg")})

    task = scheduler.submit.call_args[0][0]
    assert task.name == "delete_sources"
    task.run()
    writer.delete_source_trees.assert_called_once()


def test_flush_folder_move_into_ignored_deletes_tree(tmp_path):
    root = tmp_path / "watched"
    ignored = root / "ignored"
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root], [ignored])

    wf._flush(set(), set(), {}, {str(root / "dir"): str(ignored / "dir")})

    task = scheduler.submit.call_args[0][0]
    assert task.name == "delete_sources"
    task.run()
    writer.delete_source_trees.assert_called_once()


def test_flush_folder_rename_inside_scope_skips_prefix_delete(tmp_path):
    root = tmp_path / "watched"
    wf, scheduler, writer, scanner, _ = _make_watcher()
    _set_scope(wf, [root])

    wf._flush(set(), set(), {}, {str(root / "old"): str(root / "new")})

    assert not scheduler.submit.called


def test_flush_empty():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._flush(set(), set(), {})
    assert not scheduler.submit.called
    assert not scanner.request_update.called


def test_exec_rescan():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._exec("rescan", ["/some/folder"])
    scanner.request_scan.assert_called_once_with(["/some/folder"])


def test_exec_update():
    wf, scheduler, writer, scanner, _ = _make_watcher()
    wf._exec("update", ["/some/file.png"])
    scanner.request_update.assert_called_once_with(["/some/file.png"])


def test_exec_cleanup():
    wf, scheduler, writer, scanner, progress = _make_watcher()
    wf._exec("cleanup")
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == "delete_orphans"


class TestExtractStable:
    def test_all_stable(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature, _STABLE_THRESHOLD

        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("x")
        f2.write_text("y")
        sig = _stat_signature(str(f1))
        sig2 = _stat_signature(str(f2))
        old = time.monotonic() - _STABLE_THRESHOLD - 1
        pending = {str(f1): (old, sig), str(f2): (old, sig2)}
        stable = _extract_stable(pending)
        assert stable == {str(f1), str(f2)}
        assert pending == {}

    def test_none_stable(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature

        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("x")
        f2.write_text("y")
        now = time.monotonic()
        sig = _stat_signature(str(f1))
        sig2 = _stat_signature(str(f2))
        pending = {str(f1): (now, sig), str(f2): (now, sig2)}
        stable = _extract_stable(pending)
        assert stable == set()
        assert len(pending) == 2

    def test_partial_stable(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature, _STABLE_THRESHOLD

        f_old = tmp_path / "old.txt"
        f_new = tmp_path / "new.txt"
        f_old.write_text("x")
        f_new.write_text("y")
        now = time.monotonic()
        old_ts = now - _STABLE_THRESHOLD - 1
        pending = {
            str(f_old): (old_ts, _stat_signature(str(f_old))),
            str(f_new): (now, _stat_signature(str(f_new))),
        }
        stable = _extract_stable(pending)
        assert stable == {str(f_old)}
        assert str(f_new) in pending

    def test_empty_pending(self):
        from wafer.app.indexer.watch_folder import _extract_stable

        pending = {}
        stable = _extract_stable(pending)
        assert stable == set()
        assert pending == {}

    def test_file_changed_since_pending_resets_timer(self, tmp_path):
        from wafer.app.indexer.watch_folder import _extract_stable, _stat_signature, _STABLE_THRESHOLD

        f = tmp_path / "dl.bin"
        f.write_bytes(b"part1")
        old_sig = _stat_signature(str(f))
        old_ts = time.monotonic() - _STABLE_THRESHOLD - 1
        f.write_bytes(b"part1part2")
        pending = {str(f): (old_ts, old_sig)}
        stable = _extract_stable(pending)
        assert stable == set()
        assert str(f) in pending
        _, new_sig = pending[str(f)]
        assert new_sig != old_sig

    def test_deleted_file_stabilizes(self):
        from wafer.app.indexer.watch_folder import _extract_stable, _STABLE_THRESHOLD

        old_ts = time.monotonic() - _STABLE_THRESHOLD - 1
        pending = {"/nonexistent/file.tmp": (old_ts, (12345, 100))}
        stable = _extract_stable(pending)
        assert stable == {"/nonexistent/file.tmp"}


class TestEventAccumulator:
    def _make_accumulator(self):
        from wafer.app.indexer.watch_folder import _EventAccumulator

        return _EventAccumulator()

    def _run_and_flush(self, events):
        from wafer.app.indexer.watch_folder import _EventAccumulator

        acc = _EventAccumulator()
        wf, scheduler, writer, scanner, _ = _make_watcher()
        now = time.monotonic()
        for ev in events:
            kind, data = ev[0], ev[1]
            if kind == "created":
                acc.on_created(data)
            elif kind == "changed":
                acc.on_changed(data, now)
            elif kind == "deleted":
                acc.on_deleted(data)
            elif kind == "moved":
                acc.on_moved(*data)
        wf._flush(*acc.drain())
        _expire_pending_deletes(wf)
        return scheduler, scanner

    def test_changed_then_deleted(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("changed", "a.png"),
                ("deleted", "a.png"),
            ]
        )
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "delete_sources" in ops
        assert not scanner.request_update.called

    def test_changed_then_moved(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("changed", "a.png"),
                ("moved", ("a.png", "b.png")),
            ]
        )
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "rename_paths" in ops

    def test_first_modified_is_immediate(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("changed", "new.png"),
            ]
        )
        assert scanner.request_update.called

    def test_second_modified_stays_ready(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("changed", "dl.png"),
                ("changed", "dl.png"),
            ]
        )
        assert scanner.request_update.called

    def test_created_is_immediate(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("created", "new.png"),
            ]
        )
        assert scanner.request_update.called

    def test_created_then_modified_stays_ready(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("created", "dl.png"),
                ("changed", "dl.png"),
            ]
        )
        assert scanner.request_update.called

    def test_modified_does_not_override_ready(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("created", "x.png"),
                ("changed", "x.png"),
                ("changed", "x.png"),
            ]
        )
        assert scanner.request_update.called

    def test_created_then_deleted(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("created", "tmp.png"),
                ("deleted", "tmp.png"),
            ]
        )
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "delete_sources" in ops
        assert not scanner.request_update.called

    def test_folder_dirty(self):
        acc = self._make_accumulator()
        assert not acc.consume_folder_dirty()
        acc.on_folder()
        assert acc.consume_folder_dirty()
        assert not acc.consume_folder_dirty()

    def test_drain_all_includes_pending(self):
        acc = self._make_accumulator()
        now = time.monotonic()
        acc.on_changed("a.png", now)
        acc.drain()
        acc.on_changed("a.png", now)
        changed, *_ = acc.drain_all()
        assert "a.png" in changed

    def test_created_then_moved_triggers_update(self):
        scheduler, scanner = self._run_and_flush(
            [
                ("created", "a.tmp"),
                ("changed", "a.tmp"),
                ("moved", ("a.tmp", "a.png")),
            ]
        )
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "rename_paths" not in ops
        paths = scanner.request_update.call_args[0][0]
        assert any("a.png" in p for p in paths)


class TestZipWatchScenarios:
    """zip解凍・zip圧縮のWatchFolder検出テスト"""

    def _run_and_flush(self, events):
        from wafer.app.indexer.watch_folder import _EventAccumulator

        acc = _EventAccumulator()
        wf, scheduler, writer, scanner, _ = _make_watcher()
        now = time.monotonic()
        for ev in events:
            kind, data = ev[0], ev[1]
            if kind == "created":
                acc.on_created(data)
            elif kind == "changed":
                acc.on_changed(data, now)
            elif kind == "deleted":
                acc.on_deleted(data)
            elif kind == "moved":
                acc.on_moved(*data)
            elif kind == "folder":
                acc.on_folder()
        wf._flush(*acc.drain())
        _expire_pending_deletes(wf)
        return scheduler, scanner

    def test_zip_created_triggers_update(self):
        """新しい.zipファイルが作成された場合 → request_updateが呼ばれる"""
        scheduler, scanner = self._run_and_flush([
            ("created", "archive.zip"),
        ])
        assert scanner.request_update.called
        paths = scanner.request_update.call_args[0][0]
        assert "archive.zip" in paths

    def test_zip_created_with_multiple_changes_triggers_update(self):
        """zipファイルが作成後に複数回変更されても → request_updateが呼ばれる（多重書き込みシナリオ）"""
        scheduler, scanner = self._run_and_flush([
            ("created", "archive.zip"),
            ("changed", "archive.zip"),
            ("changed", "archive.zip"),
            ("changed", "archive.zip"),
        ])
        assert scanner.request_update.called
        paths = scanner.request_update.call_args[0][0]
        assert "archive.zip" in paths

    def test_zip_deleted_triggers_delete(self):
        """zipファイルが削除された場合 → delete_sourcesが呼ばれる"""
        scheduler, scanner = self._run_and_flush([
            ("deleted", "/nonexistent/archive.zip"),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "delete_sources" in ops
        assert not scanner.request_update.called

    def test_zip_modified_triggers_update(self):
        """既存のzipファイルが更新された場合 → request_updateが呼ばれる"""
        scheduler, scanner = self._run_and_flush([
            ("changed", "archive.zip"),
        ])
        assert scanner.request_update.called
        paths = scanner.request_update.call_args[0][0]
        assert "archive.zip" in paths

    def test_extraction_scenario_zip_deleted_files_appear(self):
        """zip解凍シナリオ: zipが削除され、展開されたファイルが出現する場合
        期待: 展開されたファイルのupdate + zipのdelete"""
        scheduler, scanner = self._run_and_flush([
            ("created", "image1.jpg"),
            ("created", "image2.jpg"),
            ("created", "image3.jpg"),
            ("deleted", "/nonexistent/archive.zip"),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "delete_sources" in ops
        assert scanner.request_update.called
        all_updated = []
        for c in scanner.request_update.call_args_list:
            all_updated.extend(c[0][0])
        assert "image1.jpg" in all_updated
        assert "image2.jpg" in all_updated
        assert "image3.jpg" in all_updated

    def test_compression_scenario_files_deleted_zip_appears(self):
        """zip圧縮シナリオ: 複数ファイルが削除され、新しいzipが作成される場合
        期待: zipのupdate + 元ファイルのdelete"""
        scheduler, scanner = self._run_and_flush([
            ("created", "archive.zip"),
            ("deleted", "/nonexistent/image1.jpg"),
            ("deleted", "/nonexistent/image2.jpg"),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "delete_sources" in ops
        assert scanner.request_update.called
        paths = scanner.request_update.call_args[0][0]
        assert "archive.zip" in paths

    def test_zip_created_via_temp_rename(self):
        """圧縮ツールがtempファイル→zipへのリネームで作成するシナリオ
        期待: archive.zipへのrequest_update（renameではなくnew file扱い）"""
        scheduler, scanner = self._run_and_flush([
            ("created", "archive.tmp"),
            ("changed", "archive.tmp"),
            ("moved", ("archive.tmp", "archive.zip")),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "rename_paths" not in ops
        assert scanner.request_update.called
        paths = scanner.request_update.call_args[0][0]
        assert any("archive.zip" in p for p in paths)

    def test_zip_replaced_triggers_update(self):
        """既存zipが新しい内容に置き換えられるシナリオ（再圧縮）
        期待: request_updateが呼ばれる"""
        scheduler, scanner = self._run_and_flush([
            ("deleted", "/nonexistent/archive.zip"),
            ("created", "archive.zip"),
        ])
        assert scanner.request_update.called
        paths = scanner.request_update.call_args[0][0]
        assert "archive.zip" in paths

    def test_extraction_keeps_zip_intact(self):
        """zip解凍してzipを残すシナリオ（zipは変更なし、展開ファイルのみ出現）
        期待: 展開ファイルのupdateのみ（zipのdeleteなし）"""
        scheduler, scanner = self._run_and_flush([
            ("created", "extracted/image1.jpg"),
            ("created", "extracted/image2.jpg"),
        ])
        ops = [c[0][0].name for c in scheduler.submit.call_args_list]
        assert "delete_sources" not in ops
        assert scanner.request_update.called
        all_updated = []
        for c in scanner.request_update.call_args_list:
            all_updated.extend(c[0][0])
        assert "extracted/image1.jpg" in all_updated
        assert "extracted/image2.jpg" in all_updated
