import py_compile

from source.image_collector.worker import CollectorWorker, _MAX_WORKERS
from source.image_collector.plugin import BUILTIN_PLUGINS


def test_compile():
    py_compile.compile('source/image_collector/worker.py')


def test_max_workers_is_reasonable():
    assert _MAX_WORKERS >= 1
    assert _MAX_WORKERS <= 16


def test_unknown_plugin_raises():
    import pytest
    with pytest.raises(ValueError, match='Unknown plugin'):
        CollectorWorker('test_db', 'nonexistent_plugin')


def test_builtin_plugins_all_constructable():
    for name, cls in BUILTIN_PLUGINS.items():
        worker = CollectorWorker('test_db', name)
        assert worker.plugin_name == name
        assert worker.db_name == 'test_db'
