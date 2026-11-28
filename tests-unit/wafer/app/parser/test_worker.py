import time
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


def test_process_batch_passes_source_key_unchanged(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()
    received = []

    def record(path, file_info, metadata):
        received.append(path)
        return ParserResult(source=path, status=True)

    worker._plugin.process = record
    key = "b:/Data/./image.png"
    worker._process_batch([key], {key: [0.0, 0]}, {}, "test_db")

    assert received == [key]
    assert worker._node.send_reliable.call_args[0][1]["results"][0]["source"] == key


def test_raised_path_and_none_are_retried(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()

    def process(path, file_info, metadata):
        if path == "/raise.png":
            raise RuntimeError("boom")
        if path == "/none.png":
            return None
        return ParserResult(source=path, status=True)

    worker._plugin.process = process
    worker._process_batch(["/ok.png", "/raise.png", "/none.png"], {}, {}, "test_db")

    statuses = {r["source"]: r["status"] for r in worker._node.send_reliable.call_args[0][1]["results"]}
    assert statuses == {"/ok.png": True}


def test_paused_path_is_not_processed_and_stays_dispatched(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()
    received = []

    def process(path, file_info, metadata):
        received.append(path)
        if path == "/busy.png":
            return worker._plugin.retry_later(path, pause_after=2)
        return ParserResult(source=path, status=True)

    worker._plugin.process = process
    for _ in range(3):
        worker._process_batch(["/ok.png", "/busy.png"], {}, {}, "test_db")

    assert received.count("/busy.png") == 2
    assert received.count("/ok.png") == 3
    assert worker._node.send_reliable.call_args[0][1]["results"] == [{"source": "/ok.png", "status": True}]


def test_all_paused_batch_still_reports_back(make_worker):
    worker = make_worker()
    worker._plugin.retries.count_failure("/busy.png", pause_after=1)
    worker._plugin.process = MagicMock()

    worker._process_batch(["/busy.png"], {}, {}, "test_db")

    worker._plugin.process.assert_not_called()
    assert worker._node.send_reliable.call_args[0][1]["results"] == []


def test_rescan_resumes_paused_paths(make_worker):
    worker = make_worker()
    worker._plugin.retries.count_failure("/busy.png", pause_after=1)

    worker._on_rescan(MagicMock())
    worker._process_batch(["/busy.png"], {}, {}, "test_db")

    assert worker._node.send_reliable.call_args[0][1]["results"] == [{"source": "/busy.png", "status": True}]


def test_paused_paths_are_reported_from_the_batch_that_pauses_them(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()

    def process(path, file_info, metadata):
        if path == "/busy.png":
            return worker._plugin.retry_later(path, pause_after=2)
        return ParserResult(source=path, status=True)

    worker._plugin.process = process
    reported = []
    for _ in range(3):
        worker._process_batch(["/ok.png", "/busy.png"], {}, {}, "test_db")
        reported.append(worker._node.send_reliable.call_args[0][1]["paused"])

    assert reported == [[], ["/busy.png"], ["/busy.png"]]


def test_result_resets_the_failure_count(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()
    outcomes = iter(["retry", "ok", "retry", "retry"])
    statuses = []

    def process(path, file_info, metadata):
        if next(outcomes) == "ok":
            return ParserResult(source=path, status=True)
        return worker._plugin.retry_later(path, fail_after=2)

    worker._plugin.process = process
    for _ in range(4):
        worker._process_batch(["/flaky.png"], {}, {}, "test_db")
        statuses.append([r["status"] for r in worker._node.send_reliable.call_args[0][1]["results"]])

    assert statuses == [[], [True], [], [False]]


def test_status_none_keeps_the_failure_count(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()
    outcomes = iter(["retry", "data", "retry"])
    statuses = []

    def process(path, file_info, metadata):
        if next(outcomes) == "data":
            return ParserResult(source=path, status=None, meta_info={"m": "1"})
        return worker._plugin.retry_later(path, fail_after=2)

    worker._plugin.process = process
    for _ in range(3):
        worker._process_batch(["/flaky.png"], {}, {}, "test_db")
        statuses.append([r["status"] for r in worker._node.send_reliable.call_args[0][1]["results"]])

    assert statuses == [[], [None], [False]]


def test_timed_out_batch_leaves_started_and_queued_paths_dispatched(make_worker, monkeypatch):
    import threading

    from wafer.plugin.parser.base import ParserResult

    monkeypatch.setattr(parser_resolver, "max_workers", lambda name: 1)
    worker = make_worker()
    worker._batch_timeout = 0.2
    release = threading.Event()
    started = []

    def process(path, file_info, metadata):
        started.append(path)
        release.wait(5)
        return ParserResult(source=path, status=True)

    worker._plugin.process = process
    try:
        worker._process_batch(["/slow.png", "/queued1.png", "/queued2.png"], {}, {}, "test_db")
    finally:
        release.set()

    statuses = {r["source"]: r["status"] for r in worker._node.send_reliable.call_args[0][1]["results"]}
    assert started == ["/slow.png"]
    assert statuses == {}


def test_stop_ends_a_batch_with_queued_paths_at_once_and_sends_finished_results(make_worker, monkeypatch):
    import threading

    from wafer.plugin.parser.base import ParserResult

    monkeypatch.setattr(parser_resolver, "max_workers", lambda name: 1)
    worker = make_worker()
    worker._batch_timeout = 20
    busy = threading.Event()
    interrupted = threading.Event()

    def process(path, file_info, metadata):
        if path == "/busy.png":
            busy.set()
            if interrupted.wait(10):
                raise RuntimeError("tool killed by shutdown")
        return ParserResult(source=path, status=True)

    worker._plugin.process = process
    worker._plugin.shutdown = interrupted.set
    batch = threading.Thread(target=worker._process_batch, args=(["/ok.png", "/busy.png", "/queued.png"], {}, {}, "test_db"))
    batch.start()
    assert busy.wait(5)
    started = time.monotonic()
    worker.stop()
    batch.join(5)
    stopped_in = time.monotonic() - started

    assert not batch.is_alive()
    assert stopped_in < 2
    statuses = {r["source"]: r["status"] for r in worker._node.send_reliable.call_args[0][1]["results"]}
    assert statuses == {"/ok.png": True}


@pytest.fixture
def batched_worker():
    from wafer.app.parser.worker import ParserWorker
    from wafer.plugin.parser.base import BaseParserPlugin, ParserResult

    class _BatchedParser(BaseParserPlugin):
        NAME = "_test_worker_batched"
        MAX_WORKERS = 4

        def __init__(self):
            self.calls = []
            self.reply = lambda paths: [ParserResult(source=p, status=True) for p in paths]

        def process(self, path, file_info, metadata):
            raise AssertionError("process must not be called for a batched parser")

        def process_batch(self, paths, file_info, metadata):
            self.calls.append((list(paths), dict(file_info), dict(metadata)))
            return self.reply(paths)

    parser_resolver.registry.register(_BatchedParser)
    worker = ParserWorker("test_db", _BatchedParser.NAME)
    worker._node = MagicMock()
    yield worker
    worker._stop.set()
    worker._executor.shutdown(wait=True, cancel_futures=True)
    parser_resolver.registry._plugins.pop(_BatchedParser.NAME, None)
    parser_resolver.registry._instances.pop(_BatchedParser.NAME, None)


def sent_statuses(worker):
    return {r["source"]: r["status"] for r in worker._node.send_reliable.call_args[0][1]["results"]}


def test_batched_parser_receives_the_whole_batch_in_one_call(batched_worker):
    batched_worker._process_batch(["/a.png", "/b.png"], {"/a.png": [1.0, 2, "h"]}, {"/b.png": {"k": "v"}}, "test_db")

    assert batched_worker._plugin.calls == [(["/a.png", "/b.png"], {"/a.png": (1.0, 2, "h"), "/b.png": (0.0, 0)}, {"/a.png": {}, "/b.png": {"k": "v"}})]
    assert sent_statuses(batched_worker) == {"/a.png": True, "/b.png": True}


def test_batched_parser_paths_without_a_result_are_not_sent(batched_worker):
    from wafer.plugin.parser.base import ParserResult

    batched_worker._plugin.reply = lambda paths: [ParserResult(source="/a.png", status=True), None]

    batched_worker._process_batch(["/a.png", "/b.png"], {}, {}, "test_db")

    assert sent_statuses(batched_worker) == {"/a.png": True}


def test_batched_parser_duplicate_path_gets_one_result(batched_worker):
    from wafer.plugin.parser.base import ParserResult

    batched_worker._plugin.reply = lambda paths: [ParserResult(source="/a.png", status=True)]
    batched_worker._process_batch(["/a.png", "/a.png"], {}, {}, "test_db")

    results = batched_worker._node.send_reliable.call_args[0][1]["results"]
    assert [r["status"] for r in results if r["source"] == "/a.png"] == [True]


def test_batched_parser_timeout_sends_nothing(batched_worker):
    import threading

    release = threading.Event()
    batched_worker._batch_timeout = 0.2
    batched_worker._plugin.reply = lambda paths: release.wait(10) and []
    try:
        batched_worker._process_batch(["/a.png", "/b.png"], {}, {}, "test_db")
    finally:
        release.set()

    assert sent_statuses(batched_worker) == {}


def test_batched_parser_returning_none_sends_an_empty_message(batched_worker):
    batched_worker._plugin.reply = lambda paths: None

    batched_worker._process_batch(["/a.png", "/b.png"], {}, {}, "test_db")

    assert batched_worker._node.send_reliable.call_args[0][1]["results"] == []


def test_batched_parser_error_while_stopping_is_not_sent(batched_worker):
    def boom(paths):
        batched_worker._stop.set()
        raise RuntimeError("tool killed by shutdown")

    batched_worker._plugin.reply = boom

    batched_worker._process_batch(["/a.png", "/b.png"], {}, {}, "test_db")

    assert sent_statuses(batched_worker) == {}


def test_batched_error_pauses_every_path_on_the_third_time(batched_worker):
    def boom(paths):
        raise RuntimeError("boom")

    batched_worker._plugin.reply = boom

    for _ in range(3):
        batched_worker._process_batch(["/a.png", "/b.png"], {}, {}, "test_db")
        assert sent_statuses(batched_worker) == {}

    assert batched_worker._plugin.retries.is_paused("/a.png")
    assert batched_worker._plugin.retries.is_paused("/b.png")


def test_on_error_result_is_sent(make_worker):
    from wafer.plugin.parser.base import ParserResult

    worker = make_worker()
    worker._plugin.process = MagicMock(side_effect=RuntimeError("boom"))
    worker._plugin.on_error = lambda path, error: ParserResult(source=path, status=False)

    worker._process_batch(["/a.png"], {}, {}, "test_db")

    assert worker._node.send_reliable.call_args[0][1]["results"] == [{"source": "/a.png", "status": False}]


@pytest.mark.parametrize("failure", ["raises", "none"])
def test_failing_on_error_is_logged_and_retried(make_worker, failure):
    worker = make_worker()
    worker._plugin.process = MagicMock(side_effect=RuntimeError("boom"))

    def on_error(path, error):
        if failure == "raises":
            raise ValueError("on_error broke")

    worker._plugin.on_error = on_error

    worker._process_batch(["/a.png"], {}, {}, "test_db")

    assert worker._node.send_reliable.called
    assert worker._node.send_reliable.call_args[0][1]["results"] == []


def test_error_while_stopping_is_not_counted(make_worker):
    worker = make_worker()

    def process(path, file_info, metadata):
        worker._stop.set()
        raise RuntimeError("tool killed by shutdown")

    worker._plugin.process = process
    worker._plugin.on_error = MagicMock()

    worker._process_batch(["/a.png"], {}, {}, "test_db")

    worker._plugin.on_error.assert_not_called()
    assert worker._node.send_reliable.call_args[0][1]["results"] == []


def test_default_process_batch_calls_process_for_each_path():
    from wafer.plugin.parser.base import BaseParserPlugin, ParserResult

    class _OneByOne(BaseParserPlugin):
        def process(self, path, file_info, metadata):
            return ParserResult(source=path, status=bool(file_info[0]), meta_info=metadata)

    results = _OneByOne().process_batch(["/a.png", "/b.png"], {"/a.png": (1.0, 0), "/b.png": (0.0, 0)}, {"/a.png": {"x": 1}, "/b.png": {}})

    assert [(r.source, r.status, r.meta_info) for r in results] == [("/a.png", True, {"x": 1}), ("/b.png", False, {})]


def test_batch_with_only_none_results_is_still_sent(make_worker):
    worker = make_worker()
    worker._plugin.process = lambda path, file_info, metadata: None

    worker._process_batch(["/none.png"], {}, {}, "test_db")

    assert worker._node.send_reliable.call_args[0][1]["results"] == []
