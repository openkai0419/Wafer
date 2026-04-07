from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.core.platform.file_operations import (
    OperationResult,
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


class TestRunWithProgress:
    def test_moves_files_in_background(self, qapp, tmp_path):
        from wafer.core.platform.paste import _run_with_progress

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
        from wafer.core.platform.paste import _run_with_progress

        results = _run_with_progress(None, "Nothing", 0, lambda i: None)
        assert results == []

    def test_cancel_stops_processing(self, qapp, tmp_path):
        from wafer.core.platform.paste import _run_with_progress

        total = 10
        cancel_at = 3

        def execute_fn(idx: int) -> OperationResult:
            time.sleep(0.05)
            if idx == cancel_at:
                for w in qapp.topLevelWidgets():
                    if isinstance(w, QtWidgets.QProgressDialog):
                        QtCore.QMetaObject.invokeMethod(w, "cancel", QtCore.Qt.QueuedConnection)
                        break
                time.sleep(0.3)
            return OperationResult(action="move", src=f"s{idx}", dst=f"d{idx}", status="ok")

        results = _run_with_progress(None, "Test cancel", total, execute_fn)
        assert len(results) < total

    def test_error_in_step_does_not_abort(self, qapp):
        from wafer.core.platform.paste import _run_with_progress

        def execute_fn(idx: int) -> OperationResult:
            if idx == 1:
                return OperationResult(action="move", src="s1", dst="d1", status="error", error="fail")
            return OperationResult(action="move", src=f"s{idx}", dst=f"d{idx}", status="ok")

        results = _run_with_progress(None, "Test error", 3, execute_fn)
        assert len(results) == 3
        assert results[1].status == "error"
        assert results[0].status == "ok"
        assert results[2].status == "ok"


class TestExecutePasteItems:
    def test_copy_files_with_progress(self, qapp, tmp_path):
        from wafer.core.platform.paste import _execute_paste_items

        src = tmp_path / "a.txt"
        src.write_text("hello", encoding="utf-8")
        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        dst = dst_dir / "a.txt"

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
        decisions = {0: PasteDecision(mode="overwrite")}
        results = _execute_paste_items(plans, decisions, None, "copy")
        assert len(results) == 1
        assert results[0].status == "ok"
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == "hello"
        assert src.exists()

    def test_move_files_with_progress(self, qapp, tmp_path):
        from wafer.core.platform.paste import _execute_paste_items

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
        decisions = {0: PasteDecision(mode="overwrite")}
        results = _execute_paste_items(plans, decisions, None, "move")
        assert len(results) == 1
        assert results[0].status == "ok"
        assert dst.exists()
        assert not src.exists()

    def test_skip_decision_skips(self, qapp, tmp_path):
        from wafer.core.platform.paste import _execute_paste_items

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
        results = _execute_paste_items(plans, decisions, None, "copy")
        assert len(results) == 1
        assert results[0].status == "skipped"

    def test_multiple_files(self, qapp, tmp_path):
        from wafer.core.platform.paste import _execute_paste_items

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
            decisions[i] = PasteDecision(mode="overwrite")

        results = _execute_paste_items(plans, decisions, None, "copy")
        assert len(results) == 5
        assert all(r.status == "ok" for r in results)
        for i in range(5):
            assert (dst_dir / f"file_{i}.txt").read_text(encoding="utf-8") == f"content_{i}"
