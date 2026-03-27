import py_compile

from wafer.app.collector.worker import CollectorWorker, _MAX_WORKERS
from wafer.plugin.collector.handler import collector_resolver


def test_compile():
    py_compile.compile('wafer/app/collector/worker.py')


def test_max_workers_is_reasonable():
    assert _MAX_WORKERS >= 1
    assert _MAX_WORKERS <= 16


def test_unknown_plugin_raises():
    import pytest
    with pytest.raises(ValueError, match='Unknown plugin'):
        CollectorWorker('test_db', 'nonexistent_plugin')


def test_all_registered_plugins_constructable():
    for name in collector_resolver.names():
        worker = CollectorWorker('test_db', name)
        assert worker.plugin_name == name
        assert worker.db_name == 'test_db'


def test_process_one_error_excludes_from_results():
    from unittest.mock import MagicMock
    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker('test_db', name)
    worker._node = MagicMock()

    def always_fail(path, info):
        raise RuntimeError('simulated plugin error')

    worker._plugin.process = always_fail
    worker._process_batch(['/nonexistent/test.jpg'], {'/nonexistent/test.jpg': [0.0, 0]})
    assert worker._node.send_reliable.called
    payload = worker._node.send_reliable.call_args[0][1]
    results = payload['results']
    assert len(results) == 0


def test_process_batch_partial_failure():
    from unittest.mock import MagicMock
    from wafer.plugin.collector.base import CollectorResult
    name = next(iter(collector_resolver.names()))
    worker = CollectorWorker('test_db', name)
    worker._node = MagicMock()

    original_process = worker._plugin.process
    call_count = 0

    def partial_fail(path, info):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError('second file fails')
        return CollectorResult(source=path, status=True)

    worker._plugin.process = partial_fail
    paths = ['/test/a.jpg', '/test/b.jpg', '/test/c.jpg']
    file_info = {p: [0.0, 0] for p in paths}
    worker._process_batch(paths, file_info)

    assert worker._node.send_reliable.called
    payload = worker._node.send_reliable.call_args[0][1]
    results = payload['results']
    assert len(results) == 2
    assert all(r['status'] is True for r in results)
