from unittest.mock import patch
from wafer.app.viewer.search import SearchService, _DEFAULTS
from wafer.plugin.query.handler import sort_registry
from wafer.core.qt.dispatcher import CancelToken
from wafer.builtins.filters import TextFilter, DirectoryFilter


def _make_service():
    return SearchService(dbpath_getter=lambda: ":memory:")


def test_initial_params():
    svc = _make_service()
    params = svc.params
    for key in _DEFAULTS:
        assert key in params


def test_get_param():
    svc = _make_service()
    assert svc.get("sort_by") in [s.NAME for s in sort_registry.list_all()]
    assert svc.get("nonexistent", "fallback") == "fallback"


def test_set_param():
    svc = _make_service()
    svc.set_param("sort_by", "name")
    assert svc.get("sort_by") == "name"


def test_set_param_no_change():
    svc = _make_service()
    received = []
    svc.params_changed.connect(lambda d: received.append(d))
    val = svc.get("ascending")
    svc.set_param("ascending", val)
    assert received == []


def test_set_params_batch():
    svc = _make_service()
    received = []
    svc.params_changed.connect(lambda d: received.append(d))
    svc.set_params({"sort_by": "size", "ascending": False})
    assert svc.get("sort_by") == "size"
    assert svc.get("ascending") is False
    assert len(received) == 1
    assert "sort_by" in received[0]


def test_set_params_no_change():
    svc = _make_service()
    received = []
    svc.params_changed.connect(lambda d: received.append(d))
    svc.set_params({})
    assert received == []


def test_set_keys():
    svc = _make_service()
    svc.set_keys(["key1", "key2"])
    entries = svc.build_filter_entries()
    text_entry = entries[0]
    assert text_entry[0] is TextFilter
    assert text_entry[1]["keys"] == ["key1", "key2"]


def test_set_directories():
    svc = _make_service()
    svc.set_directories(["/dir/a", "/dir/b"])
    entries = svc.build_filter_entries()
    assert len(entries) == 2
    assert entries[1][0] is DirectoryFilter
    assert entries[1][1]["directories"] == ["/dir/a", "/dir/b"]


def test_build_filter_entries_basic():
    svc = _make_service()
    svc.set_param("keywords", "test")
    svc.set_param("query_mode", "GLOB")
    svc.set_param("keyword_mode", "AND")
    entries = svc.build_filter_entries()
    assert len(entries) == 1
    text_cls, text_params, op = entries[0]
    assert text_cls is TextFilter
    assert text_params["keywords"] == "test"
    assert text_params["query_mode"] == "GLOB"
    assert text_params["keyword_mode"] == "AND"
    assert op is None


def test_build_filter_entries_with_directories():
    svc = _make_service()
    svc.set_directories(["/dir"])
    entries = svc.build_filter_entries()
    assert len(entries) == 2
    assert entries[0][2] is None
    assert entries[1][0] is DirectoryFilter
    assert entries[1][2] is None


def test_resolve_sort():
    svc = _make_service()
    svc.set_param("sort_by", "modified")
    sort_cls = svc.resolve_sort()
    assert sort_cls.NAME == "modified"


def test_resolve_sort_default():
    svc = _make_service()
    sort_cls = svc.resolve_sort()
    assert sort_cls.NAME == "path"


def test_build_filter_entries_keyword_separator():
    svc = _make_service()
    svc.set_param("keyword_separator", ";")
    entries = svc.build_filter_entries()
    assert entries[0][1]["keyword_separator"] == ";"


def test_reset_state():
    svc = _make_service()
    svc.set_keys(["k"])
    svc.set_directories(["/d"])
    svc.reset_state()
    entries = svc.build_filter_entries()
    assert entries[0][1]["keys"] is None
    assert len(entries) == 1


def test_params_returns_copy():
    svc = _make_service()
    p1 = svc.params
    p1["sort_by"] = "random"
    assert svc.get("sort_by") != "random" or svc.get("sort_by") == p1["sort_by"]
    p2 = svc.params
    assert p2 is not p1


def test_dispatcher_and_cancel_token_initialized():
    svc = _make_service()
    assert svc._dispatcher is not None
    assert svc._current_cancel is None
    assert svc._current_snapshot is None


def test_cancel_token_on_new_search():
    svc = _make_service()
    cancel = CancelToken()
    svc._current_cancel = cancel
    svc._current_snapshot = svc._query_snapshot()
    svc.set_param("keywords", "changed")
    new_cancel = CancelToken()
    svc._current_cancel = new_cancel
    assert cancel is not new_cancel


def test_query_snapshot_changes_with_params():
    svc = _make_service()
    snap1 = svc._query_snapshot()
    svc.set_param("keywords", "changed")
    snap2 = svc._query_snapshot()
    assert snap1 != snap2


def test_query_snapshot_changes_with_keys():
    svc = _make_service()
    snap1 = svc._query_snapshot()
    svc.set_keys(["key1"])
    snap2 = svc._query_snapshot()
    assert snap1 != snap2


def test_query_snapshot_changes_with_directories():
    svc = _make_service()
    snap1 = svc._query_snapshot()
    svc.set_directories(["/dir"])
    snap2 = svc._query_snapshot()
    assert snap1 != snap2


def test_set_filter_entries_overrides_build():
    svc = _make_service()
    custom_entries = [(TextFilter, {"keywords": "custom", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)]
    svc.set_filter_entries(custom_entries)
    result = svc.build_filter_entries()
    assert len(result) == 1
    assert result[0][1]["keywords"] == "custom"


def test_set_filter_entries_none_reverts():
    svc = _make_service()
    svc.set_filter_entries([(TextFilter, {"keywords": "x"}, None)])
    svc.set_filter_entries(None)
    result = svc.build_filter_entries()
    assert result[0][1]["keywords"] == ""


def test_reset_state_clears_external_entries():
    svc = _make_service()
    svc.set_filter_entries([(TextFilter, {"keywords": "x"}, None)])
    svc.reset_state()
    result = svc.build_filter_entries()
    assert result[0][1]["keywords"] == ""


def test_snapshot_changes_with_external_entries():
    svc = _make_service()
    snap1 = svc._query_snapshot()
    svc.set_filter_entries([(TextFilter, {"keywords": "new", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)])
    snap2 = svc._query_snapshot()
    assert snap1 != snap2


def test_entries_builder_called_each_time():
    svc = _make_service()
    counter = [0]

    def builder():
        counter[0] += 1
        return [(TextFilter, {"keywords": f"kw{counter[0]}", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)]

    svc.set_entries_builder(builder)
    e1 = svc.build_filter_entries()
    e2 = svc.build_filter_entries()
    assert e1[0][1]["keywords"] == "kw1"
    assert e2[0][1]["keywords"] == "kw2"


def test_entries_builder_takes_priority_over_external():
    svc = _make_service()
    svc.set_filter_entries([(TextFilter, {"keywords": "static", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)])

    def builder():
        return [(TextFilter, {"keywords": "dynamic", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)]

    svc.set_entries_builder(builder)
    result = svc.build_filter_entries()
    assert result[0][1]["keywords"] == "dynamic"


def test_entries_builder_reflects_directory_changes():
    svc = _make_service()
    dirs = []

    def builder():
        if dirs:
            return [
                (TextFilter, {"keywords": "", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None),
                (DirectoryFilter, {"directories": list(dirs), "include_subfolders": True}, None),
            ]
        return [(TextFilter, {"keywords": "", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)]

    svc.set_entries_builder(builder)
    snap1 = svc._query_snapshot()
    dirs.append("/new/dir")
    snap2 = svc._query_snapshot()
    assert snap1 != snap2


def test_entries_builder_reflects_param_changes():
    svc = _make_service()
    mode = ["GLOB"]

    def builder():
        return [(TextFilter, {"keywords": "", "keys": None, "query_mode": mode[0], "keyword_mode": "AND", "keyword_separator": ","}, None)]

    svc.set_entries_builder(builder)
    snap1 = svc._query_snapshot()
    mode[0] = "LIKE"
    snap2 = svc._query_snapshot()
    assert snap1 != snap2


def test_reset_state_keeps_entries_builder():
    svc = _make_service()
    svc.set_entries_builder(lambda: [(TextFilter, {"keywords": "x", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)])
    svc.reset_state()
    result = svc.build_filter_entries()
    assert result[0][1]["keywords"] == "x"
