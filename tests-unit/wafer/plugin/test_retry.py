import threading

import pytest

from wafer.plugin.collector.base import BaseCollectorPlugin, CollectorResult
from wafer.plugin.parser.base import BaseParserPlugin, ParserResult
from wafer.plugin.retry import RetryCounter


class _Collector(BaseCollectorPlugin):
    def process(self, path, file_info):
        return None


class _Parser(BaseParserPlugin):
    def process(self, path, file_info, metadata):
        return None


def test_pause_after_returns_none_and_pauses_on_the_limit():
    counter = RetryCounter("test")

    assert [counter.count_failure("/a", pause_after=3) for _ in range(2)] == [False, False]
    assert not counter.is_paused("/a")
    assert counter.count_failure("/a", pause_after=3) is False
    assert counter.is_paused("/a")


def test_fail_after_gives_up_on_the_limit_without_pausing():
    counter = RetryCounter("test")

    assert [counter.count_failure("/a", fail_after=3) for _ in range(3)] == [False, False, True]
    assert not counter.is_paused("/a")
    assert counter.count_failure("/a", fail_after=3) is False


def test_paths_are_counted_separately():
    counter = RetryCounter("test")

    counter.count_failure("/a", fail_after=2)
    assert counter.count_failure("/b", fail_after=2) is False
    assert counter.count_failure("/a", fail_after=2) is True


def test_forget_starts_the_count_again():
    counter = RetryCounter("test")

    counter.count_failure("/a", fail_after=2)
    counter.forget(["/a"])
    assert counter.count_failure("/a", fail_after=2) is False
    assert counter.count_failure("/a", fail_after=2) is True


def test_forget_keeps_paused_paths():
    counter = RetryCounter("test")

    counter.count_failure("/a", pause_after=1)
    counter.forget(["/a"])
    assert counter.is_paused("/a")


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"pause_after": 2, "fail_after": 2}, {"pause_after": 0}, {"fail_after": -1}, {"fail_after": 2.5}],
)
def test_limit_must_be_exactly_one_positive_int(kwargs):
    with pytest.raises(ValueError):
        RetryCounter("test").count_failure("/a", **kwargs)


def test_concurrent_failures_give_up_exactly_once():
    counter = RetryCounter("test")
    results = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def fail_many():
        start.wait()
        for _ in range(50):
            gave_up = counter.count_failure("/a", fail_after=400)
            with lock:
                results.append(gave_up)

    threads = [threading.Thread(target=fail_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1


@pytest.mark.parametrize(("plugin_class", "result_type"), [(_Collector, CollectorResult), (_Parser, ParserResult)])
def test_retry_later_returns_the_plugins_failure_result(plugin_class, result_type):
    plugin = plugin_class()

    assert plugin.retry_later("/a", fail_after=2) is None
    result = plugin.retry_later("/a", fail_after=2)

    assert type(result) is result_type
    assert (result.source, result.status) == ("/a", False)


@pytest.mark.parametrize("plugin_class", [_Collector, _Parser])
def test_on_error_pauses_on_the_third_error_by_default(plugin_class):
    plugin = plugin_class()
    error = RuntimeError("boom")

    assert [plugin.on_error("/a", error) for _ in range(3)] == [None, None, None]
    assert plugin.retries.is_paused("/a")


def test_each_plugin_instance_has_its_own_counter():
    first, second = _Collector(), _Collector()

    first.retry_later("/a", pause_after=1)

    assert first.retries.is_paused("/a")
    assert not second.retries.is_paused("/a")
    assert first.retries is first.retries
