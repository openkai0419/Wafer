from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.core.platform.file_operations import (
    OperationResult,
    PasteCancelledError,
    PasteDecision,
    PastePlanItem,
)


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _process_events_until(predicate, timeout_ms=5000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def _click_cancel(app, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for w in app.topLevelWidgets():
            if isinstance(w, QtWidgets.QProgressDialog) and w.isVisible():
                QtCore.QMetaObject.invokeMethod(w.findChild(QtWidgets.QPushButton), "click", QtCore.Qt.QueuedConnection)
                return
        if threading.current_thread() is threading.main_thread():
            return
        time.sleep(0.01)


class TestRunWithProgress:
    def test_moves_files_in_background(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import _run_with_progress

        src_files = []
        for i in range(3):
            f = tmp_path / f"src_{i}.txt"
            f.write_text(f"content_{i}", encoding="utf-8")
            src_files.append(f)

        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        call_threads = []

        def execute_fn(idx: int) -> OperationResult:
            call_threads.append(threading.current_thread().ident)
            src = src_files[idx]
            dst = dst_dir / src.name
            src.rename(dst)
            return OperationResult(action="move", src=str(src), dst=str(dst), status="ok")

        results = _run_with_progress(None, "Moving...", 3, execute_fn)
        assert len(results) == 3
        assert all(r.status == "ok" for r in results)
        assert all(tid != threading.main_thread().ident for tid in call_threads)
        for i in range(3):
            assert (dst_dir / f"src_{i}.txt").exists()

    def test_empty_list_returns_immediately(self, qapp):
        from wafer.qt.transfer.paste import _run_with_progress

        results = _run_with_progress(None, "Nothing", 0, lambda i: None)
        assert results == []

    def test_cancel_stops_processing(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import _run_with_progress

        total = 10
        cancel_at = 3

        def execute_fn(idx: int) -> OperationResult:
            time.sleep(0.05)
            if idx == cancel_at:
                _click_cancel(qapp)
                time.sleep(0.3)
            return OperationResult(action="move", src=f"s{idx}", dst=f"d{idx}", status="ok")

        results = _run_with_progress(None, "Test cancel", total, execute_fn)
        assert len(results) < total

    def test_error_in_step_does_not_abort(self, qapp):
        from wafer.qt.transfer.paste import _run_with_progress

        def execute_fn(idx: int) -> OperationResult:
            if idx == 1:
                return OperationResult(action="move", src="s1", dst="d1", status="error", error="fail")
            return OperationResult(action="move", src=f"s{idx}", dst=f"d{idx}", status="ok")

        results = _run_with_progress(None, "Test error", 3, execute_fn)
        assert len(results) == 3
        assert results[1].status == "error"
        assert results[0].status == "ok"
        assert results[2].status == "ok"

    def test_failed_items_are_reported_to_the_user(self, qapp, monkeypatch):
        from wafer.qt.transfer import paste

        warnings = []
        monkeypatch.setattr(paste.Notifier, "warning", staticmethod(warnings.append))

        def execute_fn(idx: int) -> OperationResult:
            return OperationResult(action="move", src=f"s{idx}", dst=f"d{idx}", status="error" if idx else "ok", error="in use")

        paste._run_with_progress(None, "Moving", 3, execute_fn)

        assert len(warnings) == 1
        assert "2" in warnings[0]

    def test_progress_starts_indeterminate_then_switches_to_determinate(self, qapp):
        from wafer.qt.transfer.paste import _run_with_progress

        release_provider = threading.Event()
        observed = {}
        ranges = []

        original_set_range = QtWidgets.QProgressDialog.setRange

        def recording_set_range(self, minimum, maximum):
            ranges.append((minimum, maximum))
            return original_set_range(self, minimum, maximum)

        QtWidgets.QProgressDialog.setRange = recording_set_range

        def progress_total_provider(is_cancelled):
            while not release_provider.wait(0.01):
                if is_cancelled():
                    raise PasteCancelledError()
            return 5

        def execute_fn(idx: int) -> OperationResult:
            time.sleep(0.05)
            return OperationResult(action="copy", src=f"s{idx}", dst=f"d{idx}", status="ok")

        def inspect_busy_state():
            for widget in qapp.topLevelWidgets():
                if isinstance(widget, QtWidgets.QProgressDialog):
                    observed["busy_range"] = (widget.minimum(), widget.maximum())
                    release_provider.set()
                    return

        try:
            QtCore.QTimer.singleShot(20, inspect_busy_state)
            results = _run_with_progress(None, "Copying...", 2, execute_fn, progress_total_provider=progress_total_provider)
        finally:
            QtWidgets.QProgressDialog.setRange = original_set_range

        assert len(results) == 2
        assert observed["busy_range"] == (0, 0)
        assert (0, 5) in ranges


class TestExecutePasteItems:
    def test_move_files_with_progress(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import _execute_plans

        src = tmp_path / "b.txt"
        src.write_text("world", encoding="utf-8")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        dst = dst_dir / "b.txt"

        plans = [
            PastePlanItem(
                index=0,
                src=src,
                is_dir=False,
                action="cut",
                dst_default=dst,
                conflict=False,
                suggested_dst=None,
            )
        ]
        decisions = {0: PasteDecision(mode="create")}
        results = _execute_plans(plans, decisions, None, "move")
        assert len(results) == 1
        assert results[0].status == "ok"
        assert dst.exists()
        assert not src.exists()

    def test_skip_decision_skips(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import _execute_plans

        src = tmp_path / "c.txt"
        src.write_text("data", encoding="utf-8")
        dst = tmp_path / "dst" / "c.txt"

        plans = [
            PastePlanItem(
                index=0,
                src=src,
                is_dir=False,
                action="copy",
                dst_default=dst,
                conflict=False,
                suggested_dst=None,
            )
        ]
        decisions = {0: PasteDecision(mode="skip")}
        results = _execute_plans(plans, decisions, None, "copy")
        assert len(results) == 1
        assert results[0].status == "skipped"

    def test_multiple_files(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import _execute_plans

        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()

        plans = []
        decisions = {}
        for i in range(5):
            src = tmp_path / f"file_{i}.txt"
            src.write_text(f"content_{i}", encoding="utf-8")
            dst = dst_dir / f"file_{i}.txt"
            plans.append(
                PastePlanItem(
                    index=i,
                    src=src,
                    is_dir=False,
                    action="copy",
                    dst_default=dst,
                    conflict=False,
                    suggested_dst=None,
                )
            )
            decisions[i] = PasteDecision(mode="create")

        results = _execute_plans(plans, decisions, None, "copy")
        assert len(results) == 5
        assert all(r.status == "ok" for r in results)
        for i in range(5):
            assert (dst_dir / f"file_{i}.txt").read_text(encoding="utf-8") == f"content_{i}"
            assert (tmp_path / f"file_{i}.txt").exists()


class TestDirectoryProgress:
    def test_count_operation_units_honors_cancellation(self, tmp_path):
        from wafer.core.platform.file_operations import count_operation_units

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("a", encoding="utf-8")

        with pytest.raises(PasteCancelledError):
            count_operation_units(src, tmp_path / "dst", "copy", cancel_check=lambda: True)

    def test_directory_copy_advances_per_file(self, tmp_path):
        from wafer.core.platform.file_operations import FileExecutor

        src = tmp_path / "src"
        (src / "nested").mkdir(parents=True)
        (src / "a.txt").write_text("a", encoding="utf-8")
        (src / "nested" / "b.txt").write_text("b", encoding="utf-8")
        dst = tmp_path / "dst"
        advances = []

        result = FileExecutor(progress_callback=lambda n: advances.append(n))._execute_item(src, dst, "copy", PasteDecision(mode="create"))

        assert result.status == "ok"
        assert sum(advances) == 2
        assert (dst / "a.txt").exists()
        assert (dst / "nested" / "b.txt").exists()

    def test_skipped_directory_copy_advances_per_file(self, tmp_path):
        from wafer.core.platform.file_operations import FileExecutor

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("a", encoding="utf-8")
        (src / "b.txt").write_text("b", encoding="utf-8")
        dst = tmp_path / "dst"
        advances = []

        result = FileExecutor(progress_callback=lambda n: advances.append(n))._execute_item(src, dst, "copy", PasteDecision(mode="skip"))

        assert result.status == "skipped"
        assert sum(advances) == 2

    def test_same_device_directory_move_is_atomic_progress(self, tmp_path, monkeypatch):
        from wafer.core.platform import file_operations
        from wafer.core.platform.file_operations import FileExecutor

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("a", encoding="utf-8")
        dst = tmp_path / "dst"
        advances = []
        monkeypatch.setattr(file_operations, "_same_device", lambda src_path, dst_path: True)

        result = FileExecutor(progress_callback=lambda n: advances.append(n))._execute_item(src, dst, "cut", PasteDecision(mode="create"))

        assert result.status == "ok"
        assert sum(advances) == 1
        assert dst.exists()
        assert not src.exists()

    def test_cross_device_directory_move_advances_per_file(self, tmp_path, monkeypatch):
        from wafer.core.platform import file_operations
        from wafer.core.platform.file_operations import FileExecutor

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.txt").write_text("a", encoding="utf-8")
        (src / "b.txt").write_text("b", encoding="utf-8")
        dst = tmp_path / "dst"
        advances = []
        monkeypatch.setattr(file_operations, "_same_device", lambda src_path, dst_path: False)

        result = FileExecutor(progress_callback=lambda n: advances.append(n))._execute_item(src, dst, "cut", PasteDecision(mode="create"))

        assert result.status == "ok"
        assert sum(advances) == 2
        assert dst.exists()
        assert not src.exists()


class TestCancelAndFailure:
    def _wait_for_cancel_and_finish(self, qapp, request_cancel):
        from wafer.qt.transfer.paste import _run_with_progress

        finished = []

        def step(idx, advance, is_cancelled):
            deadline = time.monotonic() + 5
            while not is_cancelled() and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(0.2)
            finished.append(idx)
            return OperationResult(action="move", src=f"s{idx}", dst=f"d{idx}", status="ok")

        QtCore.QTimer.singleShot(100, lambda: request_cancel(qapp))
        results = _run_with_progress(None, "Moving...", 3, step, manual_progress=True)
        return results, finished

    def test_cancel_button_waits_for_the_running_item(self, qapp):
        results, finished = self._wait_for_cancel_and_finish(qapp, _click_cancel)

        assert finished == [0]
        assert [r.status for r in results] == ["ok"]

    def test_closing_the_dialog_waits_for_the_running_item(self, qapp):
        def close_dialog(app):
            for w in app.topLevelWidgets():
                if isinstance(w, QtWidgets.QProgressDialog) and w.isVisible():
                    QtCore.QMetaObject.invokeMethod(w, "close", QtCore.Qt.QueuedConnection)
                    return

        results, finished = self._wait_for_cancel_and_finish(qapp, close_dialog)

        assert finished == [0]
        assert [r.status for r in results] == ["ok"]

    def test_escape_key_waits_for_the_running_item(self, qapp):
        from PySide6.QtTest import QTest

        def press_escape(app):
            for w in app.topLevelWidgets():
                if isinstance(w, QtWidgets.QProgressDialog) and w.isVisible():
                    QTest.keyClick(w, QtCore.Qt.Key_Escape)
                    return

        results, finished = self._wait_for_cancel_and_finish(qapp, press_escape)

        assert finished == [0]
        assert [r.status for r in results] == ["ok"]

    def test_step_exception_becomes_an_error_and_the_rest_still_runs(self, qapp):
        from wafer.qt.transfer.paste import _run_with_progress

        def execute_fn(idx: int) -> OperationResult:
            if idx == 1:
                raise PermissionError("in use")
            return OperationResult(action="copy", src=f"s{idx}", dst=f"d{idx}", status="ok")

        QtCore.QTimer.singleShot(5000, lambda: _click_cancel(qapp))
        results = _run_with_progress(None, "Copying...", 3, execute_fn)

        assert [r.status for r in results] == ["ok", "error", "ok"]
        assert "in use" in results[1].error


class TestClipboardPaste:
    def test_text_keeps_only_absolute_paths_and_leaves_existence_to_the_plan(self, qapp, monkeypatch, tmp_path):
        from wafer.qt.transfer.paste import ClipboardFilePaster

        (tmp_path / "README.md").write_text("x", encoding="utf-8")
        (tmp_path / "extensions").mkdir()
        monkeypatch.chdir(tmp_path)
        paster = object.__new__(ClipboardFilePaster)
        text = "\n".join(["README.md", "extensions", ".", "C:/__wafer_missing__/a.png", r"\\host\share\b.png", "D:relative.png"])

        paths = paster._parse_plain_text_paths(text)

        assert [str(p).replace("\\", "/") for p in paths] == ["C:/__wafer_missing__/a.png", "//host/share/b.png"]

    def test_plan_drops_sources_that_do_not_exist(self, tmp_path):
        from wafer.qt.transfer.paste import ClipboardFilePaster

        real = tmp_path / "a.txt"
        real.write_text("x", encoding="utf-8")

        plans = ClipboardFilePaster.build_paste_plan(tmp_path / "dst", ("copy", [real, tmp_path / "missing.txt", real]))

        assert [p.src for p in plans] == [real]

    def test_paste_builds_the_plan_off_the_main_thread_and_copies(self, qapp, monkeypatch, tmp_path):
        from wafer.qt.transfer import paste

        src = tmp_path / "a.txt"
        src.write_text("x", encoding="utf-8")
        dst_dir = tmp_path / "dst"
        threads = []
        real_build = paste.ClipboardFilePaster.build_paste_plan

        def recording_build(destination_dir, extracted):
            threads.append(threading.current_thread())
            return real_build(destination_dir, extracted)

        monkeypatch.setattr(paste.ClipboardFilePaster, "__init__", lambda self: None)
        monkeypatch.setattr(paste.ClipboardFilePaster, "collect_clipboard_files", lambda self: ("copy", [src]))
        monkeypatch.setattr(paste.ClipboardFilePaster, "build_paste_plan", staticmethod(recording_build))

        paste.paste_clipboard_files(dst_dir, overwrite_mode="skip")
        _process_events_until(lambda: (dst_dir / "a.txt").exists())

        assert (dst_dir / "a.txt").read_text(encoding="utf-8") == "x"
        assert threads and threads[0] is not threading.main_thread()

    def test_a_paste_while_one_is_running_is_ignored_with_a_message(self, qapp, monkeypatch, tmp_path):
        from wafer.qt.transfer import paste

        src = tmp_path / "a.txt"
        src.write_text("x", encoding="utf-8")
        dst_dir = tmp_path / "dst"
        release = threading.Event()
        builds = []
        notices = []
        real_build = paste.ClipboardFilePaster.build_paste_plan

        def blocking_build(destination_dir, extracted):
            builds.append(destination_dir)
            release.wait(5)
            return real_build(destination_dir, extracted)

        monkeypatch.setattr(paste.ClipboardFilePaster, "__init__", lambda self: None)
        monkeypatch.setattr(paste.ClipboardFilePaster, "collect_clipboard_files", lambda self: ("copy", [src]))
        monkeypatch.setattr(paste.ClipboardFilePaster, "build_paste_plan", staticmethod(blocking_build))
        monkeypatch.setattr(paste.Notifier, "info", staticmethod(notices.append))

        paste.paste_clipboard_files(dst_dir, overwrite_mode="skip")
        _process_events_until(lambda: len(builds) == 1)
        paste.paste_clipboard_files(dst_dir, overwrite_mode="skip")
        release.set()
        _process_events_until(lambda: (dst_dir / "a.txt").exists() and not paste.paste_in_progress())

        assert len(builds) == 1
        assert len(notices) >= 1
        assert [p.name for p in dst_dir.iterdir()] == ["a.txt"]

        paste.paste_clipboard_files(dst_dir, overwrite_mode="skip")
        _process_events_until(lambda: len(builds) == 2 and not paste.paste_in_progress())

        assert len(builds) == 2

    def test_a_failed_plan_still_allows_the_next_paste(self, qapp, monkeypatch, tmp_path):
        from wafer.qt.transfer import paste

        builds = []

        def failing_build(destination_dir, extracted):
            builds.append(destination_dir)
            raise OSError("destination is read-only")

        monkeypatch.setattr(paste.ClipboardFilePaster, "__init__", lambda self: None)
        monkeypatch.setattr(paste.ClipboardFilePaster, "collect_clipboard_files", lambda self: ("copy", [tmp_path]))
        monkeypatch.setattr(paste.ClipboardFilePaster, "build_paste_plan", staticmethod(failing_build))

        paste.paste_clipboard_files(tmp_path / "dst")
        _process_events_until(lambda: len(builds) == 1 and not paste.paste_in_progress())
        paste.paste_clipboard_files(tmp_path / "dst")
        _process_events_until(lambda: len(builds) == 2 and not paste.paste_in_progress())

        assert len(builds) == 2


class TestConflictsAskedDuringTheCopy:
    def _conflicting_plans(self, tmp_path, count):
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        plans = []
        for i in range(count):
            src = tmp_path / f"f{i}.txt"
            src.write_text(f"new {i}", encoding="utf-8")
            (dst_dir / src.name).write_text(f"old {i}", encoding="utf-8")
            plans.append(PastePlanItem(index=i, src=src, is_dir=False, action="copy", dst_default=dst_dir / src.name, conflict=True, suggested_dst=None))
        return plans, dst_dir

    def test_a_conflict_is_asked_on_the_main_thread_and_its_answer_is_applied(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import _execute_plans

        plans, dst_dir = self._conflicting_plans(tmp_path, 1)
        on_main = []

        def ask(conflict):
            on_main.append(threading.current_thread() is threading.main_thread())
            return "overwrite"

        results = _execute_plans(plans, {}, None, "copy", ask)

        assert on_main == [True]
        assert results[0].status == "ok"
        assert (dst_dir / "f0.txt").read_text(encoding="utf-8") == "new 0"

    def test_cancelling_a_conflict_stops_the_items_after_it(self, qapp, tmp_path):
        from wafer.core.platform.file_operations import CANCELLED
        from wafer.qt.transfer.paste import _execute_plans

        plans, dst_dir = self._conflicting_plans(tmp_path, 3)

        def ask(conflict):
            raise PasteCancelledError()

        results = _execute_plans(plans, {}, None, "copy", ask)

        assert [r.error for r in results] == [CANCELLED]
        assert [(dst_dir / f"f{i}.txt").read_text(encoding="utf-8") for i in range(3)] == ["old 0", "old 1", "old 2"]

    def test_a_selected_item_already_in_the_destination_is_reported_as_selected(self, qapp, tmp_path):
        from wafer.qt.transfer.paste import ClipboardFilePaster, _execute_plans

        (tmp_path / "S1").mkdir()
        (tmp_path / "S2").mkdir()
        (tmp_path / "S1" / "img.png").write_text("S1", encoding="utf-8")
        (tmp_path / "S2" / "img.png").write_text("S2", encoding="utf-8")
        plans = ClipboardFilePaster.build_paste_plan(tmp_path / "S1", ("copy", [tmp_path / "S1" / "img.png", tmp_path / "S2" / "img.png"]))
        selected = []

        def ask(conflict):
            selected.append(conflict.selected_item)
            return "skip"

        _execute_plans(plans, {plans[0].index: PasteDecision(mode="skip")}, None, "copy", ask)

        assert selected == [True]
        assert (tmp_path / "S1" / "img.png").read_text(encoding="utf-8") == "S1"
