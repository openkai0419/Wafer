import py_compile

import pytest

from wafer.app.collector.worker import CollectorWorker, _SHUTDOWN_WAIT
from wafer.plugin.collector.handler import collector_resolver


@pytest.fixture
def make_worker():
    workers = []

    def factory(db_name="test_db", plugin_name=None):
        name = plugin_name or next(iter(collector_resolver.names()))
        worker = CollectorWorker(db_name, name)
        workers.append(worker)
        return worker

    yield factory

    for worker in reversed(workers):
        worker._stop.set()
        worker._batch_queue.put(None)
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_compile():
    py_compile.compile("wafer/app/collector/worker.py")


def test_unknown_plugin_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown plugin"):
        CollectorWorker("test_db", "nonexistent_plugin")


def test_all_registered_plugins_constructable(make_worker):
    for name in collector_resolver.names():
        worker = make_worker(plugin_name=name)
        assert worker.plugin_name == name
        assert worker.db_name == "test_db"
        assert worker._max_workers == collector_resolver.max_workers(name)
        assert worker._batch_timeout == collector_resolver.batch_timeout(name)


def test_process_one_error_excludes_from_results(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()

    def always_fail(path, info):
        raise RuntimeError("simulated plugin error")

    worker._plugin.process = always_fail
    worker._process_batch(["/nonexistent/test.jpg"], {"/nonexistent/test.jpg": [0.0, 0]}, "test_db")
    assert worker._node.send_reliable.called
    payload = worker._node.send_reliable.call_args[0][1]
    results = payload["results"]
    assert len(results) == 0


def test_process_batch_partial_failure(make_worker):
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    worker = make_worker()
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


def test_process_batch_uses_db_from_argument(make_worker):
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    worker = make_worker()
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: CollectorResult(source=path, status=True)
    worker._process_batch(["/test/x.jpg"], {"/test/x.jpg": [0.0, 0]}, "other_db")

    call_kwargs = worker._node.send_reliable.call_args[1]
    assert call_kwargs["db"] == "other_db"


def test_non_singleton_node_uses_db_name(make_worker):
    name = next(iter(collector_resolver.per_indexer_names()))
    worker = make_worker(db_name="mydb", plugin_name=name)
    assert worker._singleton is False
    assert worker._node.db == "mydb"


def test_file_hash_auto_injected_when_tags_present(make_worker):
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    worker = make_worker()
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


def test_file_hash_not_injected_without_tags(make_worker):
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    worker = make_worker()
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


def test_explicit_file_hash_is_replaced_by_source_hash(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()

    worker._plugin.process = lambda path, info: {
        "source": path,
        "status": True,
        "file_hash": "explicit_hash",
        "tags": {"wd14.tags": "tag_data"},
    }
    paths = ["/test/a.jpg"]
    file_info = {"/test/a.jpg": [0.0, 100, "from_file_info"]}
    worker._process_batch(paths, file_info, "test_db")

    payload = worker._node.send_reliable.call_args[0][1]
    result = payload["results"][0]
    assert result["file_hash"] == "from_file_info"


def test_file_hash_compat_with_old_file_info(make_worker):
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult

    worker = make_worker()
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


def test_on_notify_calls_plugin(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True


def test_notify_subscribed(make_worker):
    worker = make_worker()
    assert "plugin.notify" in worker._node._handlers
    assert "worker.shutdown" in worker._node._handlers


def test_worker_shutdown_message_sets_stop(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    msg = MagicMock()
    result = worker._on_shutdown(msg)
    assert result is True
    assert worker._stop.is_set()


def test_stop_calls_plugin_shutdown_once(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()
    worker._plugin.shutdown = MagicMock()

    worker.stop()
    worker.stop()

    worker._plugin.shutdown.assert_called_once()


def test_stop_shuts_down_executor_before_join(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()
    worker._plugin.shutdown = MagicMock()
    events = []

    worker._executor.shutdown = lambda **kwargs: events.append(("executor.shutdown", kwargs))
    worker._batch_thread.is_alive = lambda: True
    worker._batch_thread.join = lambda timeout=None: events.append(("batch.join", timeout))

    worker.stop()

    assert events[:2] == [
        ("executor.shutdown", {"wait": True, "cancel_futures": True}),
        ("batch.join", _SHUTDOWN_WAIT),
    ]


def test_stop_continues_when_plugin_shutdown_fails(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()
    worker._plugin.shutdown = MagicMock(side_effect=RuntimeError("boom"))

    worker.stop()

    assert worker._stop.is_set()
    worker._node.stop.assert_called()


def test_constants():
    assert _SHUTDOWN_WAIT > 0


def test_handle_batch_rejects_when_stopped(make_worker):
    from unittest.mock import MagicMock
    from wafer.core.ipc.message import Message

    worker = make_worker()
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


def test_shutdown_cancel_futures(make_worker):
    from unittest.mock import MagicMock

    worker = make_worker()
    worker._node = MagicMock()
    worker._node.stop = MagicMock()
    worker.stop()
    assert worker._stop.is_set()
