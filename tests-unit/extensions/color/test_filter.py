from __future__ import annotations

import sqlite3


from extensions.color._color import rgb_to_packed
from extensions.color.filter import ColorFilter


def test_color_filter_sql_matches_tolerance():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT, value_num REAL);
            CREATE TABLE sources (source TEXT, file_hash TEXT);
            CREATE TABLE files (path TEXT, source TEXT);
            """
        )
        rows = [
            ("red.jpg", "h1", rgb_to_packed(255, 0, 0)),
            ("mixed.jpg", "h2", rgb_to_packed(230, 20, 20)),
            ("blue.jpg", "h3", rgb_to_packed(0, 0, 255)),
        ]
        for path, file_hash, packed in rows:
            conn.execute("INSERT INTO sources VALUES (?, ?)", (path, file_hash))
            conn.execute("INSERT INTO files VALUES (?, ?)", (path, path))
            conn.execute("INSERT INTO tags VALUES (?, ?, ?, ?)", (file_hash, "color.palette.1", str(packed), packed))
        sql, params = ColorFilter.build_path_query({"colors": [{"hex": "#ff0000", "tolerance": 0.1}], "mode": "OR"}, lambda p: p)
        result = {row[0] for row in conn.execute(sql, params).fetchall()}
        assert result == {"red.jpg", "mixed.jpg"}
    finally:
        conn.close()


def test_color_filter_and_mode_requires_both_colors():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT, value_num REAL);
            CREATE TABLE sources (source TEXT, file_hash TEXT);
            CREATE TABLE files (path TEXT, source TEXT);
            """
        )
        conn.execute("INSERT INTO sources VALUES ('both.jpg', 'h1')")
        conn.execute("INSERT INTO files VALUES ('both.jpg', 'both.jpg')")
        conn.execute("INSERT INTO tags VALUES ('h1', 'color.palette.1', ?, ?)", (str(rgb_to_packed(255, 0, 0)), rgb_to_packed(255, 0, 0)))
        conn.execute("INSERT INTO tags VALUES ('h1', 'color.palette.2', ?, ?)", (str(rgb_to_packed(0, 0, 255)), rgb_to_packed(0, 0, 255)))
        conn.execute("INSERT INTO sources VALUES ('red.jpg', 'h2')")
        conn.execute("INSERT INTO files VALUES ('red.jpg', 'red.jpg')")
        conn.execute("INSERT INTO tags VALUES ('h2', 'color.palette.1', ?, ?)", (str(rgb_to_packed(255, 0, 0)), rgb_to_packed(255, 0, 0)))
        sql, params = ColorFilter.build_path_query(
            {"colors": [{"hex": "#ff0000", "tolerance": 0.01}, {"hex": "#0000ff", "tolerance": 0.01}], "mode": "AND"},
            lambda p: p,
        )
        result = {row[0] for row in conn.execute(sql, params).fetchall()}
        assert result == {"both.jpg"}
    finally:
        conn.close()


def test_color_filter_uses_dynamic_palette_keys(monkeypatch):
    monkeypatch.setattr("extensions.color.filter.palette_keys", lambda: ("palette.1", "palette.2", "palette.3"))
    sql, params = ColorFilter.build_path_query({"colors": [{"hex": "#ff0000", "tolerance": 0.1}], "mode": "OR"}, lambda p: p)
    assert "?,?,?" in sql
    assert params[:3] == ["color.palette.1", "color.palette.2", "color.palette.3"]
