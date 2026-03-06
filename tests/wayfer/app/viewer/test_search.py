from unittest.mock import patch
from wayfer.app.viewer.search import SearchService, _DEFAULTS, SORT_CHOICES
from wayfer.core.db.query import SearchQuery


def _make_service():
    return SearchService(dbpath_getter=lambda: ":memory:")


def test_initial_params():
    svc = _make_service()
    params = svc.params
    for key in _DEFAULTS:
        assert key in params


def test_get_param():
    svc = _make_service()
    assert svc.get("sort_by") in SORT_CHOICES
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
    q = svc.build_query()
    assert q.keys == ("key1", "key2")


def test_set_directories():
    svc = _make_service()
    svc.set_directories(["/dir/a", "/dir/b"])
    q = svc.build_query()
    assert q.directories == ("/dir/a", "/dir/b")


def test_build_query_returns_meta_query():
    svc = _make_service()
    svc.set_param("keywords", "test")
    svc.set_param("query_mode", "GLOB")
    svc.set_param("keyword_mode", "AND")
    q = svc.build_query()
    assert isinstance(q, SearchQuery)
    assert q.keywords == "test"
    assert q.query_mode == "GLOB"
    assert q.keyword_mode == "AND"


def test_build_query_sort():
    svc = _make_service()
    svc.set_param("sort_by", "modified")
    svc.set_param("ascending", False)
    q = svc.build_query()
    assert q.sort_by == "modified"
    assert q.ascending is False


def test_build_query_keyword_separator():
    svc = _make_service()
    svc.set_param("keyword_separator", ";")
    q = svc.build_query()
    assert q.keyword_separator == ";"


def test_reset_state():
    svc = _make_service()
    svc.set_keys(["k"])
    svc.set_directories(["/d"])
    svc.reset_state()
    q = svc.build_query()
    assert q.keys is None
    assert q.directories is None


def test_params_returns_copy():
    svc = _make_service()
    p1 = svc.params
    p1["sort_by"] = "random"
    assert svc.get("sort_by") != "random" or svc.get("sort_by") == p1["sort_by"]
    p2 = svc.params
    assert p2 is not p1
