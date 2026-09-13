import py_compile
from unittest.mock import MagicMock, patch

from wafer.plugin.parser.handler import parser_resolver


def test_compile():
    py_compile.compile("wafer/app/parser/worker.py")


def test_attach_file_hash_uses_file_info_for_tags():
    from wafer.app.parser.worker import _attach_file_hash

    result = {"source": "/a.png", "status": True, "tags": {"k": "v"}}
    _attach_file_hash(result, (1.0, 100, "fast1"))
    assert result["file_hash"] == "fast1"


def test_attach_file_hash_prefers_update_hash():
    from wafer.app.parser.worker import _attach_file_hash

    result = {"source": "/a.png", "status": True, "tags": {"k": "v"}, "update_hash": "full1"}
    _attach_file_hash(result, (1.0, 100, "fast1"))
    assert result["file_hash"] == "full1"


def test_attach_file_hash_applies_to_delete_tag_keys():
    from wafer.app.parser.worker import _attach_file_hash

    result = {"source": "/a.png", "status": True, "delete_tag_keys": ["x.y"]}
    _attach_file_hash(result, (1.0, 100, "fast1"))
    assert result["file_hash"] == "fast1"


def test_attach_file_hash_skipped_for_delete_meta_keys():
    from wafer.app.parser.worker import _attach_file_hash

    result = {"source": "/a.png", "status": True, "delete_meta_keys": ["exiftool.PNG:Comment"]}
    _attach_file_hash(result, (1.0, 100, "fast1"))
    assert "file_hash" not in result


def test_attach_file_hash_skipped_without_hash_scoped_payload():
    from wafer.app.parser.worker import _attach_file_hash

    result = {"source": "/a.png", "status": True, "meta_info": {"k": "v"}}
    _attach_file_hash(result, (1.0, 100, "fast1"))
    assert "file_hash" not in result


def test_attach_file_hash_skipped_without_file_info_hash():
    from wafer.app.parser.worker import _attach_file_hash

    result = {"source": "/a.png", "status": True, "tags": {"k": "v"}}
    _attach_file_hash(result, (1.0, 100))
    assert "file_hash" not in result


def test_db_name_injected_only_for_per_indexer_parser():
    from wafer.app.parser.worker import ParserWorker
    from wafer.plugin.parser.base import BaseParserPlugin, BaseSingletonParser, ParserResult

    class _PerIndexer(BaseParserPlugin):
        NAME = "_test_db_name_per_indexer"

        def process(self, path, file_info, metadata):
            return ParserResult(source=path, status=True)

    class _Singleton(BaseSingletonParser):
        NAME = "_test_db_name_singleton"

        def process(self, path, file_info, metadata):
            return ParserResult(source=path, status=True)

    parser_resolver.registry.register(_PerIndexer)
    parser_resolver.registry.register(_Singleton)
    try:
        assert ParserWorker("test_db", _PerIndexer.NAME)._plugin.db_name == "test_db"
        assert ParserWorker("test_db", _Singleton.NAME)._plugin.db_name == ""
    finally:
        for name in (_PerIndexer.NAME, _Singleton.NAME):
            parser_resolver.registry._plugins.pop(name, None)
            parser_resolver.registry._instances.pop(name, None)


def _make_worker():
    from wafer.app.parser.worker import ParserWorker

    names = parser_resolver.names()
    if not names:
        import pytest

        pytest.skip("No parser plugins registered")
    name = next(iter(names))
    worker = ParserWorker("test_db", name)
    worker._node = MagicMock()
    return worker


def test_notify_subscribed():
    from wafer.app.parser.worker import ParserWorker

    names = parser_resolver.names()
    if not names:
        import pytest

        pytest.skip("No parser plugins registered")
    name = next(iter(names))
    worker = ParserWorker("test_db", name)
    assert "plugin.notify" in worker._node._handlers
    assert "worker.shutdown" in worker._node._handlers


def test_on_notify_calls_plugin():
    worker = _make_worker()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True


def test_worker_shutdown_message_sets_stop():
    worker = _make_worker()
    mock_msg = MagicMock()
    result = worker._on_shutdown(mock_msg)
    assert result is True
    assert worker._stop.is_set()


def test_handle_batch_rejects_when_stopped():
    from wafer.core.ipc.message import Message

    worker = _make_worker()
    worker._stop.set()
    msg = Message.build(
        "parse.batch",
        {"paths": ["/test/a.jpg"], "file_info": {}, "metadata": {}},
        src="test",
        dst="parser",
        db="test_db",
    )
    result = worker._handle_batch(msg)
    assert result is True


def test_handle_batch_enqueues_without_spawning_threads():
    import threading

    from wafer.core.ipc.message import Message

    worker = _make_worker()
    before = threading.active_count()
    for i in range(20):
        msg = Message.build(
            "parse.batch",
            {"paths": [f"/test/{i}.jpg"], "file_info": {}, "metadata": {}},
            src="test",
            dst="parser",
            db="test_db",
        )
        assert worker._handle_batch(msg) is True
    assert threading.active_count() == before
    assert worker._batch_queue.qsize() == 20


def test_shutdown_cancel_futures():
    worker = _make_worker()
    worker._node.stop = MagicMock()
    worker.stop()
    assert worker._stop.is_set()


def test_stop_calls_plugin_shutdown_once():
    worker = _make_worker()
    worker._plugin.shutdown = MagicMock()
    worker.stop()
    worker.stop()
    worker._plugin.shutdown.assert_called_once()


def test_stop_continues_when_plugin_shutdown_fails():
    worker = _make_worker()
    worker._plugin.shutdown = MagicMock(side_effect=RuntimeError("boom"))
    worker.stop()
    assert worker._stop.is_set()
    worker._node.stop.assert_called()


def test_constants():
    from wafer.app.parser.worker import _SHUTDOWN_WAIT

    assert _SHUTDOWN_WAIT > 0


def test_worker_uses_parser_execution_settings():
    worker = _make_worker()
    assert worker._max_workers == parser_resolver.max_workers(worker.plugin_name)
    assert worker._batch_timeout == parser_resolver.batch_timeout(worker.plugin_name)
