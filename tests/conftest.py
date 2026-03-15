import os
import sys
import time

import pytest

from wafer.utils.logs import set_suppress_dialog
from wafer.plugin.loader import load_plugins, PluginLoader

set_suppress_dialog(True)

_pre_load_modules = set(sys.modules.keys())
load_plugins(skip_install=True)
PluginLoader.register_extension_commands()

for mod_name in list(sys.modules.keys()):
    if mod_name not in _pre_load_modules and mod_name.split('.')[0] == 'numpy':
        del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _close_qt_widgets_after_test():
    yield
    try:
        from PySide6 import QtWidgets
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        for w in app.topLevelWidgets():
            w.close()
        app.processEvents()
    except ImportError:
        pass


@pytest.fixture(autouse=True, scope='session')
def _cleanup_background_resources():
    yield
    try:
        from wafer.utils.profiling import profiler
        profiler.stop()
    except Exception:
        pass
    try:
        from wafer.app.viewer.viewer_settings import app_settings
        app_settings.close()
    except Exception:
        pass


_SUMMARY_PATH = os.path.join(os.path.dirname(__file__), '..', '.temp', 'test_summary.txt')
_test_start_time = 0.0
_test_counts = {'passed': 0, 'failed': 0, 'skipped': 0, 'error': 0}
_failed_nodes: list[str] = []
_error_nodes: list[str] = []


def pytest_configure(config):
    global _test_start_time, _test_counts, _failed_nodes, _error_nodes
    _test_start_time = time.time()
    _test_counts = {'passed': 0, 'failed': 0, 'skipped': 0, 'error': 0}
    _failed_nodes = []
    _error_nodes = []


def pytest_runtest_logreport(report):
    if report.when == 'call':
        if report.passed:
            _test_counts['passed'] += 1
        elif report.failed:
            _test_counts['failed'] += 1
            _failed_nodes.append(report.nodeid)
        elif report.skipped:
            _test_counts['skipped'] += 1
    elif report.when in ('setup', 'teardown') and report.failed:
        _test_counts['error'] += 1
        _error_nodes.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    elapsed = time.time() - _test_start_time
    total = sum(_test_counts.values())
    minutes, seconds = divmod(elapsed, 60)

    os.makedirs(os.path.dirname(_SUMMARY_PATH), exist_ok=True)
    with open(_SUMMARY_PATH, 'w', encoding='utf-8') as f:
        f.write(f"total: {total}\n")
        f.write(f"passed: {_test_counts['passed']}\n")
        f.write(f"failed: {_test_counts['failed']}\n")
        f.write(f"skipped: {_test_counts['skipped']}\n")
        f.write(f"error: {_test_counts['error']}\n")
        f.write(f"exitstatus: {exitstatus}\n")
        f.write(f"duration: {int(minutes)}m {seconds:.1f}s\n")
        if _failed_nodes:
            f.write("\n--- FAILED ---\n")
            for node in _failed_nodes:
                f.write(f"  {node}\n")
        if _error_nodes:
            f.write("\n--- ERROR ---\n")
            for node in _error_nodes:
                f.write(f"  {node}\n")
