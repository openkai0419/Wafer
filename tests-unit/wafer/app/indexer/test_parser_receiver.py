import py_compile
from unittest.mock import MagicMock, call

import pytest

from wafer.app.indexer.parser_receiver import (
    trigger_parser_pending,
    _build_source_keys,
)
from wafer.plugin.parser.handler import parser_resolver
from wafer.plugin.parser.base import BaseParser, ParserResult


class _FakeParserA(BaseParser):
    NAME = "_test_det_a"
    PRIORITY = 10
    TRIGGER_KEYS = ("exif.Comment",)

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


class _FakeParserB(BaseParser):
    NAME = "_test_det_b"
    PRIORITY = 10
    TRIGGER_KEYS = ("wd14.general",)

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


@pytest.fixture(autouse=True)
def _register():
    prev_plugins = dict(parser_resolver.registry._plugins)
    prev_instances = dict(parser_resolver.registry._instances)
    parser_resolver.registry._plugins.clear()
    parser_resolver.registry._instances.clear()
    parser_resolver.registry.register(_FakeParserA)
    parser_resolver.registry.register(_FakeParserB)
    yield
    parser_resolver.registry._plugins.clear()
    parser_resolver.registry._instances.clear()
    parser_resolver.registry._plugins.update(prev_plugins)
    parser_resolver.registry._instances.update(prev_instances)


def test_compile():
    py_compile.compile("wafer/app/indexer/parser_receiver.py")


def test_trigger_empty_source_keys():
    writer = MagicMock()
    trigger_parser_pending({}, writer)
    writer.insert_pending.assert_not_called()


def test_trigger_no_matching_keys():
    writer = MagicMock()
    source_keys = {"/a.png": {"exif.Width", "exif.Height"}}
    trigger_parser_pending(source_keys, writer)
    writer.insert_pending.assert_not_called()


def test_trigger_filters_sources_by_key():
    writer = MagicMock()
    source_keys = {
        "/a.png": {"exif.Comment", "exif.Width"},
        "/b.png": {"exif.Width"},
        "/c.png": {"exif.Comment"},
    }
    trigger_parser_pending(source_keys, writer)
    args = writer.insert_pending.call_args[0]
    sources = sorted(args[0])
    assert sources == ["/a.png", "/c.png"]
    assert args[1] == ["_test_det_a"]


def test_trigger_multiple_parsers():
    writer = MagicMock()
    source_keys = {
        "/a.png": {"exif.Comment"},
        "/b.png": {"wd14.general"},
        "/c.png": {"exif.Comment", "wd14.general"},
    }
    trigger_parser_pending(source_keys, writer)
    assert writer.insert_pending.call_count == 2
    calls = writer.insert_pending.call_args_list
    det_a_call = [c for c in calls if c[0][1] == ["_test_det_a"]][0]
    det_b_call = [c for c in calls if c[0][1] == ["_test_det_b"]][0]
    assert sorted(det_a_call[0][0]) == ["/a.png", "/c.png"]
    assert sorted(det_b_call[0][0]) == ["/b.png", "/c.png"]


def test_trigger_calls_request_dispatch():
    writer = MagicMock()
    dispatch = MagicMock()
    source_keys = {"/a.png": {"exif.Comment"}}
    trigger_parser_pending(source_keys, writer, request_dispatch=dispatch)
    dispatch.assert_called_once()


def test_trigger_no_dispatch_when_no_match():
    writer = MagicMock()
    dispatch = MagicMock()
    source_keys = {"/a.png": {"unrelated.key"}}
    trigger_parser_pending(source_keys, writer, request_dispatch=dispatch)
    dispatch.assert_not_called()


def test_build_source_keys_meta_info():
    data = {
        "meta_info_entries": [
            ("/a.png", "exif.Comment", "val", None),
            ("/a.png", "exif.Width", "100", 100.0),
            ("/b.png", "exif.Height", "200", 200.0),
        ],
        "tag_entries": [],
    }
    result = _build_source_keys(data)
    assert result == {
        "/a.png": {"exif.Comment", "exif.Width"},
        "/b.png": {"exif.Height"},
    }


def test_build_source_keys_with_tags():
    data = {
        "meta_info_entries": [
            ("/a.png", "exif.Comment", "val", None),
        ],
        "tag_entries": [
            ("hash1", "wd14.general", "tags", None),
        ],
    }
    result = _build_source_keys(data)
    assert result["/a.png"] == {"exif.Comment"}
    assert result["hash1"] == {"wd14.general"}


def test_build_source_keys_empty():
    data = {"meta_info_entries": [], "tag_entries": []}
    assert _build_source_keys(data) == {}
