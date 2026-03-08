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
