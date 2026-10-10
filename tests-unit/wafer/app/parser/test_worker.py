from unittest.mock import MagicMock

import pytest

from wafer.plugin.parser.handler import parser_resolver


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


@pytest.fixture
def make_worker():
    from wafer.app.parser.worker import ParserWorker
    from wafer.plugin.parser.base import BaseParserPlugin, ParserResult

    class _StubParser(BaseParserPlugin):
        NAME = "_test_worker_stub"

        def process(self, path, file_info, metadata):
            return ParserResult(source=path, status=True)

    parser_resolver.registry.register(_StubParser)
    workers = []

    def factory():
        worker = ParserWorker("test_db", _StubParser.NAME)
        worker._node = MagicMock()
        workers.append(worker)
        return worker

    yield factory

    for worker in workers:
        worker._stop.set()
        worker._executor.shutdown(wait=True, cancel_futures=True)
    parser_resolver.registry._plugins.pop(_StubParser.NAME, None)
    parser_resolver.registry._instances.pop(_StubParser.NAME, None)


def test_on_notify_calls_plugin(make_worker):
    worker = make_worker()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True


def test_worker_shutdown_message_sets_stop(make_worker):
    worker = make_worker()
    mock_msg = MagicMock()
    result = worker._on_shutdown(mock_msg)
    assert result is True
    assert worker._stop.is_set()


def test_handle_batch_rejects_when_stopped(make_worker):
    from wafer.core.ipc.message import Message

    worker = make_worker()
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


def test_handle_batch_enqueues_without_spawning_threads(make_worker):
    import threading

    from wafer.core.ipc.message import Message

    worker = make_worker()
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


def test_stop_continues_when_plugin_shutdown_fails(make_worker):
    worker = make_worker()
    worker._plugin.shutdown = MagicMock(side_effect=RuntimeError("boom"))
    worker.stop()
    assert worker._stop.is_set()
    worker._node.stop.assert_called()
