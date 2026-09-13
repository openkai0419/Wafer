import py_compile
from unittest.mock import ANY, MagicMock, call, patch

import pytest

from wafer.app.indexer.receivers.parser_receiver import (
    trigger_parser_pending,
    _parse_batch,
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
    py_compile.compile("wafer/app/indexer/receivers/parser_receiver.py")


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


def test_parse_batch_source_keys_from_meta_info():
    results = [
        {"source": "/a.png", "parser": "exif", "status": True, "meta_info": {"Comment": "val", "Width": "100"}},
        {"source": "/b.png", "parser": "exif", "status": True, "meta_info": {"Height": "200"}},
    ]
    parsed = _parse_batch(results)
    assert parsed["source_keys"] == {
        "/a.png": {"exif.Comment", "exif.Width"},
        "/b.png": {"exif.Height"},
    }


def test_parse_batch_source_keys_of_tags_use_source_not_file_hash():
    results = [
        {"source": "/a.png", "parser": "wd14", "status": True, "file_hash": "hash1", "tags": {"general": "cat"}},
    ]
    parsed = _parse_batch(results)
    assert parsed["tag_entries"] == [("hash1", "wd14.general", "cat", None)]
    assert parsed["source_keys"] == {"/a.png": {"wd14.general"}}


def test_parse_batch_source_keys_use_source_for_virtual_path():
    results = [
        {"source": "/a.zip", "path": "/a.zip::img.png", "parser": "exif", "status": True, "meta_info": {"Comment": "v"}},
    ]
    parsed = _parse_batch(results)
    assert parsed["meta_info_entries"][0][0] == "/a.zip::img.png"
    assert parsed["source_keys"] == {"/a.zip": {"exif.Comment"}}


def test_parse_batch_source_keys_empty():
    assert _parse_batch([])["source_keys"] == {}


def test_parse_batch_blacklist_filters_meta_and_tags(monkeypatch):
    from wafer.plugin.key_filter import KeyFilter

    monkeypatch.setattr(KeyFilter, "_cache", {"sd": ("blacklist", frozenset({"prompt"}))})
    results = [
        {
            "source": "s",
            "file_hash": "h",
            "meta_info": {"seed": "1", "prompt": "x"},
            "tags": {"artist": "a", "prompt": "y"},
            "status": True,
            "parser": "sd",
        }
    ]
    data = _parse_batch(results)
    meta_keys = [e[1] for e in data["meta_info_entries"]]
    tag_keys = [e[1] for e in data["tag_entries"]]
    assert "sd.seed" in meta_keys
    assert "sd.prompt" not in meta_keys
    assert "sd.artist" in tag_keys
    assert "sd.prompt" not in tag_keys


def test_parse_batch_whitelist_keeps_only_selected(monkeypatch):
    from wafer.plugin.key_filter import KeyFilter

    monkeypatch.setattr(KeyFilter, "_cache", {"sd": ("whitelist", frozenset({"seed"}))})
    results = [
        {
            "source": "s",
            "meta_info": {"seed": "1", "prompt": "x"},
            "status": True,
            "parser": "sd",
        }
    ]
    data = _parse_batch(results)
    meta_keys = [e[1] for e in data["meta_info_entries"]]
    assert meta_keys == ["sd.seed"]


def test_parse_batch_collects_update_hash():
    results = [
        {"source": "/a.png", "update_hash": "full1", "status": True, "parser": "full_hash"},
        {"source": "/b.png", "status": True, "parser": "full_hash"},
        {"source": "/c.png", "update_hash": "full3", "status": False, "parser": "full_hash"},
    ]
    data = _parse_batch(results)
    assert data["hash_updates"] == [("/a.png", "full1")]


def test_merge_parsed_merges_hash_updates():
    from wafer.app.indexer.receivers.parser_receiver import _merge_parsed

    first = _parse_batch([{"source": "/a.png", "update_hash": "full1", "status": True, "parser": "p"}])
    second = _parse_batch([{"source": "/b.png", "update_hash": "full2", "status": True, "parser": "p"}])
    merged = _merge_parsed([first, second])
    assert merged["hash_updates"] == [("/a.png", "full1"), ("/b.png", "full2")]


def test_flush_applies_hash_updates_before_writing_and_retriggers():
    from wafer.app.indexer.receivers.parser_receiver import ParserReceiver

    writer = MagicMock()
    writer.update_source_hashes.return_value = ["/a.png"]
    receiver = ParserReceiver(MagicMock(), writer, MagicMock())
    receiver._buffer.append(
        _parse_batch([{"source": "/a.png", "update_hash": "full1", "status": True, "parser": "_test_det_a"}]),
        1,
    )
    with patch("wafer.app.indexer.receivers.parser_receiver.FLUSH_DELAY", 0), patch(
        "wafer.app.indexer.receivers.parser_receiver.trigger_parser_pending"
    ) as trigger:
        receiver._flush()

    writer.update_source_hashes.assert_called_once_with([("/a.png", "full1")])
    assert writer.mock_calls.index(call.update_source_hashes([("/a.png", "full1")])) < writer.mock_calls.index(
        call.upsert_parser_results([], [], [("/a.png", "_test_det_a", "ok", ANY)], [])
    )
    assert trigger.call_args[0][0] == {"/a.png": {"file_hash"}}


def test_parse_batch_unfiltered_prefix_passes_all(monkeypatch):
    from wafer.plugin.key_filter import KeyFilter

    monkeypatch.setattr(KeyFilter, "_cache", {"other": ("whitelist", frozenset())})
    results = [
        {
            "source": "s",
            "meta_info": {"a": "1", "b": "2"},
            "status": True,
            "parser": "sd",
        }
    ]
    data = _parse_batch(results)
    meta_keys = sorted(e[1] for e in data["meta_info_entries"])
    assert meta_keys == ["sd.a", "sd.b"]
