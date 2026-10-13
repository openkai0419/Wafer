import sqlite3

from wafer.core.db import path_values
from wafer.core.db.file_db import FileDB
from wafer.core.db.path_values import PathValue, fetch_path_values, fetch_sources


def _make_db(tmp_path, count=1):
    db_path = tmp_path / "values.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [(f"c:/{i}.jpg", f"hash-{i}", 100 + i, 1700000000.0 + i, 1600000000.0, 1800000000.0) for i in range(count)],
        [(f"c:/{i}.jpg", f"c:/{i}.jpg", f"{i}.jpg", 1.0, None) for i in range(count)],
        [(f"c:/{i}.jpg", "exif.width", str(10 * i), 10.0 * i) for i in range(count)]
        + [(f"c:/{i}.jpg", "rating", "1", 1.0) for i in range(count)],
    )
    db.upsert_collection_results(
        [],
        [],
        [(f"c:/{i}.jpg", "wd14.tags", f"tag{i}, common", None) for i in range(count)]
        + [(f"c:/{i}.jpg", "rating", "5", 5.0) for i in range(count)],
        [],
    )
    db.close()
    return db_path


def test_missing_db_returns_empty():
    assert fetch_path_values(None, ["c:/0.jpg"]) == {}
    assert fetch_path_values("/nonexistent/db.sqlite", ["c:/0.jpg"]) == {}
    assert fetch_sources(None, ["c:/0.jpg"]) == {}


def test_empty_paths_returns_empty(tmp_path):
    assert fetch_path_values(_make_db(tmp_path), []) == {}


def test_reads_meta_tags_and_standard_columns(tmp_path):
    values = fetch_path_values(_make_db(tmp_path, 2), ["c:/1.jpg"])["c:/1.jpg"]
    assert values["exif.width"] == PathValue("10", 10.0)
    assert values["wd14.tags"] == PathValue("tag1, common", None)
    assert values["name"] == PathValue("1.jpg")
    assert values["path"] == PathValue("c:/1.jpg")
    assert values["size"] == PathValue("101", 101.0)
    assert values["modified"] == PathValue("1700000001.0", 1700000001.0)


def test_tags_win_over_meta(tmp_path):
    values = fetch_path_values(_make_db(tmp_path), ["c:/0.jpg"])["c:/0.jpg"]
    assert values["rating"] == PathValue("5", 5.0)


def test_chunk_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(path_values, "SQL_CHUNK_SIZE", 2)
    paths = [f"c:/{i}.jpg" for i in range(5)]
    values = fetch_path_values(_make_db(tmp_path, 5), paths)
    assert sorted(values) == paths
    assert all(values[p]["name"].text == p[3:] for p in paths)


def test_non_numeric_source_column_keeps_text_without_number(tmp_path):
    db_path = _make_db(tmp_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sources SET size = 'broken' WHERE source = 'c:/0.jpg'")
    conn.commit()
    conn.close()
    values = fetch_path_values(db_path, ["c:/0.jpg"])["c:/0.jpg"]
    assert values["size"] == PathValue("broken", None)
    assert values["name"] == PathValue("0.jpg")


def test_fetch_sources(tmp_path):
    assert fetch_sources(_make_db(tmp_path, 2), ["c:/0.jpg", "c:/1.jpg"]) == {"c:/0.jpg": "c:/0.jpg", "c:/1.jpg": "c:/1.jpg"}
