from unittest.mock import patch
from wafer.app.viewer.search import SearchService
from wafer.builtins.filters import TextFilter, DirectoryFilter, ContainedFilesFilter


def _make_service():
    return SearchService(dbpath_getter=lambda: ":memory:")


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
    assert svc.build_filter_entries()[0][1]["trim_keywords"] is True
    svc.set_param("keywords", "test")
    svc.set_param("query_mode", "GLOB")
    svc.set_param("keyword_mode", "AND")
    svc.set_param("keyword_separator", ";")
    svc.set_param("trim_keywords", False)
    entries = svc.build_filter_entries()
    assert len(entries) == 1
    text_cls, text_params, op = entries[0]
    assert text_cls is TextFilter
    assert text_params["keywords"] == "test"
    assert text_params["query_mode"] == "GLOB"
    assert text_params["keyword_mode"] == "AND"
    assert text_params["keyword_separator"] == ";"
    assert text_params["trim_keywords"] is False
    assert op is None


def test_build_filter_entries_excludes_contained_files_when_disabled():
    svc = _make_service()
    svc.set_param("include_contained_files", False)
    entries = svc.build_filter_entries()
    assert entries[-1][0] is ContainedFilesFilter
    assert entries[-1][1] == {"include": False}


def test_resolve_sort():
    svc = _make_service()
    svc.set_param("sort_by", "modified")
    sort_cls = svc.resolve_sort()
    assert sort_cls.NAME == "modified"


def test_resolve_sort_default():
    svc = _make_service()
    sort_cls = svc.resolve_sort()
    assert sort_cls.NAME == "none"


def test_reset_state():
    svc = _make_service()
    svc.set_keys(["k"])
    svc.set_directories(["/d"])
    svc.reset_state()
    entries = svc.build_filter_entries()
    assert entries[0][1]["keys"] is None
    assert len(entries) == 1


def test_query_snapshot_changes_with_params():
    mutations = (
        lambda svc: svc.set_param("keywords", "changed"),
        lambda svc: svc.set_keys(["key1"]),
        lambda svc: svc.set_directories(["/dir"]),
        lambda svc: svc.set_param("include_contained_files", False),
    )
    for mutate in mutations:
        svc = _make_service()
        snap1 = svc._query_snapshot()
        mutate(svc)
        assert svc._query_snapshot() != snap1


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


def test_reset_state_keeps_entries_builder():
    svc = _make_service()
    svc.set_entries_builder(lambda: [(TextFilter, {"keywords": "x", "keys": None, "query_mode": "GLOB", "keyword_mode": "AND", "keyword_separator": ","}, None)])
    svc.reset_state()
    result = svc.build_filter_entries()
    assert result[0][1]["keywords"] == "x"


def _run_search_inline(svc, monkeypatch, execute):
    monkeypatch.setattr(svc._dispatcher, "post", lambda fn, **kwargs: fn())
    monkeypatch.setattr(svc._dispatcher, "invoke", lambda fn: fn())
    monkeypatch.setattr(svc._composer, "execute", execute)
    svc._start_search(("none", True, ()), [], None, True)


def test_a_failed_search_clears_its_state_and_runs_the_pending_search(monkeypatch):
    svc = _make_service()
    failed, finished = [], []
    svc.search_failed.connect(lambda: failed.append(True))
    svc.search_finished.connect(lambda *a: finished.append(a))
    svc._pending_snapshot = ("name", True, ())
    rerun = []
    monkeypatch.setattr(svc, "execute", lambda force=False: rerun.append(force))

    def broken(*args):
        raise RuntimeError("database is locked")

    _run_search_inline(svc, monkeypatch, broken)

    assert failed == [True]
    assert finished == []
    assert svc._current_cancel is None
    assert svc._query_start_time is None
    assert svc._last_snapshot is None
    assert svc._pending_snapshot is None
    assert rerun == [True]


def test_a_search_closes_its_engine(monkeypatch):
    svc = _make_service()
    closed = []
    monkeypatch.setattr("wafer.app.viewer.search.FileSearchEngine.close", lambda self: closed.append(self))

    _run_search_inline(svc, monkeypatch, lambda *a: ([], [], []))

    assert len(closed) == 1


def test_a_search_sends_the_path_index_built_off_main(monkeypatch):
    svc = _make_service()
    finished = []
    svc.search_finished.connect(lambda *a: finished.append(a))

    _run_search_inline(svc, monkeypatch, lambda *a: (["a", "b"], ["sa", "sb"], [1.0, 2.0]))

    assert finished == [(["a", "b"], ["sa", "sb"], [1.0, 2.0], {"a": 0, "b": 1})]
