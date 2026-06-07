import atexit
import json
import os
import sys
import time

import pytest

from wafer.utils.logs import AppLogger
from wafer.utils.logs import debug_non_recursive
from wafer.utils.logs import set_suppress_dialog
from wafer.plugin.loader import load_plugins, get_command_registry
from wafer.plugin.settings import PluginSettings

set_suppress_dialog(True)

_orig_enabled_names = PluginSettings.enabled_names
_orig_enabled_overrides = PluginSettings.enabled_overrides
_orig_has_enabled_overrides = PluginSettings.has_enabled_overrides
PluginSettings.enabled_names = lambda self: None
PluginSettings.enabled_overrides = lambda self: {}
PluginSettings.has_enabled_overrides = lambda self: False

try:
    load_plugins()
    get_command_registry().activate("viewer")
finally:
    PluginSettings.enabled_names = _orig_enabled_names
    PluginSettings.enabled_overrides = _orig_enabled_overrides
    PluginSettings.has_enabled_overrides = _orig_has_enabled_overrides

_vendored_packages = os.path.join("extensions", ".packages")
_vendored_abs = os.path.normpath(os.path.abspath(_vendored_packages))
_vendored_in_path = [p for p in sys.path if os.path.normpath(os.path.abspath(p)) == _vendored_abs]
if _vendored_in_path:
    _vendored_mods = [
        k for k, m in sys.modules.items()
        if m is not None and getattr(m, "__file__", None) and
        os.path.normpath(os.path.abspath(m.__file__)).startswith(_vendored_abs + os.sep)
    ]
    _mod_backup = {k: sys.modules[k] for k in _vendored_mods}
    for _p in _vendored_in_path:
        sys.path.remove(_p)
    for _k in _vendored_mods:
        del sys.modules[_k]
    for _pkg in {_k.split(".")[0] for _k in _vendored_mods}:
        try:
            __import__(_pkg)
        except ImportError:
            for _k, _m in _mod_backup.items():
                if _k == _pkg or _k.startswith(_pkg + "."):
                    sys.modules[_k] = _m
    for _p in _vendored_in_path:
        sys.path.insert(0, _p)

def _drain_pool(pool, timeout_ms=1000):
    pool.clear()
    pool.waitForDone(timeout_ms)


_cleanup_errors: list[str] = []


def _record_cleanup_error(label: str, exc: BaseException) -> None:
    text = f"{label}: {exc}"
    _cleanup_errors.append(text)
    debug_non_recursive(f"[test cleanup] {text}")


@pytest.fixture(autouse=True)
def _close_qt_widgets_after_test():
    yield
    try:
        from wafer.core.qt.thread import grid_thumb_pool, grid_render_pool, utility_pool

        _drain_pool(grid_thumb_pool.pool)
        _drain_pool(grid_render_pool.pool)
        _drain_pool(utility_pool.pool)
    except Exception as e:
        _record_cleanup_error("drain qt pools after test", e)
    try:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception as e:
        _record_cleanup_error("process qt events after test", e)
    try:
        from extensions.animated._common import _driver, _viewer_driver

        if _driver is not None:
            _driver._timer.stop()
            _driver._cells.clear()
        if _viewer_driver is not None:
            _viewer_driver._timer.stop()
            _viewer_driver._cells.clear()
    except Exception as e:
        _record_cleanup_error("reset animated drivers after test", e)
    try:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception as e:
        _record_cleanup_error("process qt events after driver reset", e)


@pytest.fixture(autouse=True, scope="session")
def _cleanup_background_resources():
    yield
    try:
        from wafer.app.indexer.dispatch.collector_dispatcher import CollectorDispatcher
        from wafer.app.indexer.dispatch.parser_dispatcher import ParserDispatcher

        CollectorDispatcher.reset_singleton_state()
        ParserDispatcher.reset_singleton_state()
    except Exception as e:
        _record_cleanup_error("reset dispatcher singletons", e)
    try:
        from wafer.core.platform.process import AppProcess

        children = AppProcess.children(recursive=True)
        if children:
            AppProcess.terminate_and_wait(children, timeout=3, kill_timeout=2)
    except Exception as e:
        _record_cleanup_error("terminate child processes", e)
    try:
        from wafer.core.qt.thread import grid_thumb_pool, grid_render_pool, utility_pool

        _drain_pool(grid_thumb_pool.pool)
        _drain_pool(grid_render_pool.pool)
        _drain_pool(utility_pool.pool)
    except Exception as e:
        _record_cleanup_error("drain qt pools at session finish", e)
    try:
        from PySide6 import QtWidgets
        import shiboken6

        app = QtWidgets.QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if shiboken6.isValid(w):
                    w.hide()
                    w.deleteLater()
            app.processEvents()
            app.processEvents()
    except Exception as e:
        _record_cleanup_error("close qt top level widgets", e)
    try:
        from wafer.utils.profiling import profiler

        profiler.stop()
    except Exception as e:
        _record_cleanup_error("stop profiler", e)
    try:
        from wafer.core.app_settings import app_settings

        app_settings.close()
    except Exception as e:
        _record_cleanup_error("close app settings", e)


_SUMMARY_PATH = os.environ.get("WAFER_TEST_SUMMARY_PATH", os.path.join(os.path.dirname(__file__), "tests", "test_summary.txt"))
_test_start_time = 0.0
_test_counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
_category_counts: dict[str, dict[str, int]] = {}
_failed_nodes: list[str] = []
_failed_messages: dict[str, str] = {}
_error_nodes: list[str] = []
_error_messages: dict[str, str] = {}
_summary_written = False


def _category_of(nodeid: str) -> str:
    parts = nodeid.replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[0] == "tests-unit":
        return f"unit/{parts[1]}"
    if len(parts) >= 3 and parts[0] == "tests":
        return parts[1]
    return "root"


def pytest_addoption(parser):
    parser.addoption("--run-unstable", action="store_true", default=False, help="Run tests marked as unstable (may crash the process)")
    parser.addoption("--run-setup", action="store_true", default=False, help="Run extension install/setup smoke tests")
    parser.addoption("--allow-cpu-fallback", action="store_true", default=False, help="Allow GPU tests to pass with CPU fallback (skip GPU assertions)")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-unstable"):
        skip_unstable = pytest.mark.skip(reason="needs --run-unstable option to run")
        for item in items:
            if "unstable" in item.keywords:
                item.add_marker(skip_unstable)
    if not config.getoption("--run-setup"):
        skip_setup = pytest.mark.skip(reason="needs --run-setup option to run")
        for item in items:
            if "setup" in item.keywords:
                item.add_marker(skip_setup)


def pytest_configure(config):
    global _test_start_time, _test_counts, _category_counts
    global _failed_nodes, _failed_messages, _error_nodes, _error_messages
    global _summary_written
    _test_start_time = time.time()
    _test_counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    _category_counts = {}
    _failed_nodes = []
    _failed_messages = {}
    _error_nodes = []
    _error_messages = {}
    _summary_written = False
    atexit.register(_write_summary_atexit)


def pytest_runtest_logreport(report):
    if report.when == "call":
        cat = _category_of(report.nodeid)
        bucket = _category_counts.setdefault(cat, {"passed": 0, "failed": 0, "skipped": 0, "error": 0})
        if report.passed:
            _test_counts["passed"] += 1
            bucket["passed"] += 1
        elif report.failed:
            _test_counts["failed"] += 1
            bucket["failed"] += 1
            _failed_nodes.append(report.nodeid)
            _failed_messages[report.nodeid] = report.longreprtext.split("\n")[-1][:200] if report.longreprtext else ""
        elif report.skipped:
            _test_counts["skipped"] += 1
            bucket["skipped"] += 1
    elif report.when in ("setup", "teardown") and report.failed:
        _test_counts["error"] += 1
        _error_nodes.append(report.nodeid)
        _error_messages[report.nodeid] = report.longreprtext.split("\n")[-1][:200] if report.longreprtext else ""


def _write_summary(exitstatus=None):
    global _summary_written
    elapsed = time.time() - _test_start_time
    total = sum(_test_counts.values())
    minutes, seconds = divmod(elapsed, 60)

    try:
        os.makedirs(os.path.dirname(_SUMMARY_PATH), exist_ok=True)
        with open(_SUMMARY_PATH, "w", encoding="utf-8") as f:
            f.write(f"total: {total}\n")
            f.write(f"passed: {_test_counts['passed']}\n")
            f.write(f"failed: {_test_counts['failed']}\n")
            f.write(f"skipped: {_test_counts['skipped']}\n")
            f.write(f"error: {_test_counts['error']}\n")
            f.write(f"exitstatus: {exitstatus if exitstatus is not None else 'unknown'}\n")
            f.write(f"duration: {int(minutes)}m {seconds:.1f}s\n")
            if _category_counts:
                f.write("\n--- BY CATEGORY ---\n")
                for cat in sorted(_category_counts):
                    c = _category_counts[cat]
                    cat_total = sum(c.values())
                    parts = [f"{cat_total} total"]
                    if c["passed"]:
                        parts.append(f"{c['passed']} passed")
                    if c["failed"]:
                        parts.append(f"{c['failed']} failed")
                    if c["skipped"]:
                        parts.append(f"{c['skipped']} skipped")
                    if c["error"]:
                        parts.append(f"{c['error']} error")
                    f.write(f"  {cat}: {', '.join(parts)}\n")
            if _failed_nodes:
                f.write("\n--- FAILED ---\n")
                for node in _failed_nodes:
                    msg = _failed_messages.get(node, "")
                    f.write(f"  {node}\n")
                    if msg:
                        f.write(f"    {msg}\n")
            if _error_nodes:
                f.write("\n--- ERROR ---\n")
                for node in _error_nodes:
                    msg = _error_messages.get(node, "")
                    f.write(f"  {node}\n")
                    if msg:
                        f.write(f"    {msg}\n")
        if exitstatus != "running":
            _summary_written = True
    except Exception as e:
        AppLogger.warning(f"[test summary] Failed to write summary: {e}", exc=e)


def _write_summary_atexit():
    if not _summary_written:
        _write_summary(exitstatus="crashed")


def pytest_sessionfinish(session, exitstatus):
    _write_summary(exitstatus=exitstatus)


from pathlib import Path

_SAMPLE_DIR = Path(__file__).parent / ".sample"
_SAMPLE_MANIFEST = _SAMPLE_DIR / "manifest.json"


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    if not _SAMPLE_MANIFEST.exists():
        pytest.skip("Sample dataset not available. Run: python tests/dataset_downloader.py download")
    return _SAMPLE_DIR


@pytest.fixture(scope="session")
def sample_manifest(sample_dir: Path) -> dict:
    with open(sample_dir / "manifest.json", encoding="utf-8") as f:
        return json.load(f)


def _sample_paths(sample_dir: Path, file_type: str) -> list[Path]:
    manifest = json.loads((sample_dir / "manifest.json").read_text("utf-8"))
    return [sample_dir / e["path"] for e in manifest["files"] if e.get("type") == file_type and (sample_dir / e["path"]).exists()]


@pytest.fixture(scope="session")
def sample_images(sample_dir: Path) -> list[Path]:
    return _sample_paths(sample_dir, "image")


@pytest.fixture(scope="session")
def sample_videos(sample_dir: Path) -> list[Path]:
    return _sample_paths(sample_dir, "video")


@pytest.fixture(scope="session")
def sample_animated(sample_dir: Path) -> list[Path]:
    return _sample_paths(sample_dir, "animated")
