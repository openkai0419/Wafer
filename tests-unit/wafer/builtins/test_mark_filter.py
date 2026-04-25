from wafer.builtins.filters import MarkFilter


def _norm(p):
    return p


def test_mark_filter_empty_returns_none():
    sql, params = MarkFilter.build_path_query({"mark_ids": []}, _norm)
    assert sql is None
    assert params == []


def test_mark_filter_or_single_id():
    sql, params = MarkFilter.build_path_query({"mark_ids": ["1"], "mode": "OR"}, _norm)
    assert sql is not None
    assert "tags" in sql.lower()
    assert "mark.1" in params


def test_mark_filter_or_multi():
    sql, params = MarkFilter.build_path_query({"mark_ids": ["1", "2"], "mode": "OR"}, _norm)
    assert sql is not None
    assert "mark.1" in params and "mark.2" in params
    assert params.count("mark.1") == 1


def test_mark_filter_and_multi():
    sql, params = MarkFilter.build_path_query({"mark_ids": ["1", "2", "3"], "mode": "AND"}, _norm)
    assert sql is not None
    assert "GROUP BY" in sql
    assert "HAVING" in sql
    assert params[-1] == 3


def test_mark_filter_and_single_falls_back():
    sql, params = MarkFilter.build_path_query({"mark_ids": ["1"], "mode": "AND"}, _norm)
    assert sql is not None
    assert "GROUP BY" not in sql
