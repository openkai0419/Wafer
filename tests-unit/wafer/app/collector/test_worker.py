import py_compile

from wafer.app.collector.worker import CollectorWorker, _MAX_WORKERS, _CHUNK_TIMEOUT, _CHUNK_SIZE, _SHUTDOWN_WAIT
from wafer.plugin.collector.handler import collector_resolver


def test_compile():
    py_compile.compile("wafer/app/collector/worker.py")


def test_max_workers_is_reasonable():
    assert _MAX_WORKERS >= 1
    assert _MAX_WORKERS <= 16


def test_unknown_plugin_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown plugin"):
        CollectorWorker("test_db", "nonexistent_plugin")


def test_all_registered_plugins_constructable():
    for name in collector_resolver.names():
        worker = CollectorWorker("test_db", name)
        assert worker.plugin_name == name
        assert worker.db_name == "test_db"


def test_process_one_error_excludes_from_results():
    from unittest.mock import MagicMock

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    def always_fail(path, info):
        raise RuntimeError("simulated plugin error")

    worker._plugin.process = always_fail
    worker._process_batch(["/nonexistent/test.jpg"], {"/nonexistent/test.jpg": [0.0, 0]}, "test_db")
    assert worker._node.send_reliable.called
    payload = worker._node.send_reliable.call_args[0][1]
    results = payload["results"]
    assert len(results) == 0


def test_process_batch_partial_failure():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    original_process = worker._plugin.process
    call_count = 0

    def partial_fail(path, info):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("second file fails")
        return CollectorResult(source=path, status=True)

    worker._plugin.process = partial_fail
    paths = ["/test/a.jpg", "/test/b.jpg", "/test/c.jpg"]
    file_info = {p: [0.0, 0] for p in paths}
    worker._process_batch(paths, file_info, "test_db")

    assert worker._node.send_reliable.called
    payload = worker._node.send_reliable.call_args[0][1]
    results = payload["results"]
    assert len(results) == 2
    assert all(r["status"] is True for r in results)


def test_process_batch_uses_db_from_argument():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: CollectorResult(source=path, status=True)
    worker._process_batch(["/test/x.jpg"], {"/test/x.jpg": [0.0, 0]}, "other_db")

    call_kwargs = worker._node.send_reliable.call_args[1]
    assert call_kwargs["db"] == "other_db"


def test_non_singleton_node_uses_db_name():
    name = next(iter(collector_resolver.per_indexer_names()))
    worker = CollectorWorker("mydb", name)
    assert worker._singleton is False
    assert worker._node.db == "mydb"


def test_file_hash_auto_injected_when_tags_present():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: CollectorResult(
        source=path,
        status=True,
        tags={"wd14.tags": "1girl, blue_hair"},
    )
    paths = ["/test/a.jpg"]
    file_info = {"/test/a.jpg": [0.0, 100, "abc123hash"]}
    worker._process_batch(paths, file_info, "test_db")

    payload = worker._node.send_reliable.call_args[0][1]
    result = payload["results"][0]
    assert result["file_hash"] == "abc123hash"
    assert result["tags"] == {"wd14.tags": "1girl, blue_hair"}


def test_file_hash_not_injected_without_tags():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: CollectorResult(
        source=path,
        status=True,
        meta_info={"exif.camera": "Canon"},
    )
    paths = ["/test/a.jpg"]
    file_info = {"/test/a.jpg": [0.0, 100, "abc123hash"]}
    worker._process_batch(paths, file_info, "test_db")

    payload = worker._node.send_reliable.call_args[0][1]
    result = payload["results"][0]
    assert "file_hash" not in result


def test_explicit_file_hash_not_overwritten():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: CollectorResult(
        source=path,
        status=True,
        file_hash="explicit_hash",
        tags={"wd14.tags": "tag_data"},
    )
    paths = ["/test/a.jpg"]
    file_info = {"/test/a.jpg": [0.0, 100, "from_file_info"]}
    worker._process_batch(paths, file_info, "test_db")

    payload = worker._node.send_reliable.call_args[0][1]
    result = payload["results"][0]
    assert result["file_hash"] == "explicit_hash"


def test_file_hash_compat_with_old_file_info():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: CollectorResult(
        source=path,
        status=True,
        tags={"wd14.tags": "tag_data"},
    )
    paths = ["/test/a.jpg"]
    file_info = {"/test/a.jpg": [0.0, 100]}
    worker._process_batch(paths, file_info, "test_db")

    payload = worker._node.send_reliable.call_args[0][1]
    result = payload["results"][0]
    assert "file_hash" not in result


def test_on_notify_calls_plugin():
    from unittest.mock import MagicMock

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True


def test_notify_subscribed():
    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    assert "plugin.notify" in worker._node._handlers


def test_constants():
    assert _CHUNK_TIMEOUT > 0
    assert _CHUNK_SIZE > 0
    assert _SHUTDOWN_WAIT > 0


def test_handle_batch_rejects_when_stopped():
    from unittest.mock import MagicMock
    from wafer.core.ipc.message import Message

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()
    worker._stop.set()
    msg = Message.build(
        "collect.batch",
        {"paths": ["/test/a.jpg"], "file_info": {}},
        src="test",
        dst="collector",
        db="test_db",
    )
    result = worker._handle_batch(msg)
    assert result is True


def test_shutdown_cancel_futures():
    from unittest.mock import MagicMock

    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker("test_db", name)
    worker._node = MagicMock()
    worker._node.stop = MagicMock()
    worker.stop()
    assert worker._stop.is_set()
