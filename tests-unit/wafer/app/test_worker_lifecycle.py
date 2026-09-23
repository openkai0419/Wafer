import concurrent.futures
import py_compile
from unittest.mock import MagicMock

from wafer.app.worker_lifecycle import PluginWorkerLifecycle


def test_compile():
    py_compile.compile("wafer/app/worker_lifecycle.py")


def _make_lifecycle(get_plugin, registry=None, executor=None):
    return PluginWorkerLifecycle(
        get_plugin,
        registry or MagicMock(),
        "test_plugin",
        executor or MagicMock(spec=concurrent.futures.ThreadPoolExecutor),
        "Test",
    )


def test_shutdown_plugin_calls_plugin_shutdown_once():
    plugin = MagicMock()
    lifecycle = _make_lifecycle(lambda: plugin)

    lifecycle.shutdown_plugin()
    lifecycle.shutdown_plugin()

    plugin.shutdown.assert_called_once()


def test_shutdown_plugin_discards_registry_instance():
    plugin = MagicMock()
    registry = MagicMock()
    lifecycle = _make_lifecycle(lambda: plugin, registry=registry)

    lifecycle.shutdown_plugin()

    registry.discard_instance.assert_called_once_with("test_plugin")


def test_shutdown_plugin_swallows_exception_and_still_discards():
    plugin = MagicMock()
    plugin.shutdown.side_effect = RuntimeError("boom")
    registry = MagicMock()
    lifecycle = _make_lifecycle(lambda: plugin, registry=registry)

    lifecycle.shutdown_plugin()

    registry.discard_instance.assert_called_once_with("test_plugin")


def test_shutdown_plugin_resolves_plugin_lazily():
    holder = {"plugin": MagicMock()}
    lifecycle = _make_lifecycle(lambda: holder["plugin"])

    replaced = MagicMock()
    holder["plugin"] = replaced
    lifecycle.shutdown_plugin()

    replaced.shutdown.assert_called_once()


def test_stop_shuts_down_plugin_before_executor():
    plugin = MagicMock()
    executor = MagicMock(spec=concurrent.futures.ThreadPoolExecutor)
    events = []
    plugin.shutdown.side_effect = lambda: events.append("plugin")
    executor.shutdown.side_effect = lambda **kw: events.append("executor")
    lifecycle = _make_lifecycle(lambda: plugin, executor=executor)

    lifecycle.stop()

    assert events == ["plugin", "executor"]
    executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)
