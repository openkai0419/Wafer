from __future__ import annotations

import hashlib
import os
import sqlite3
import time

import pytest

from wafer.core.db.db_utils import apply_read_pragmas, apply_write_pragmas

from extensions.additional_filters.filter import (
    DateRangeFilter,
    is_date_key,
    _preset_to_epoch,
    _date_str_to_epoch,
    _resolve_date_value,
    _resolve_preset_ref,
)


def _setup_db(tmp_path, files=None, meta_num=None):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    apply_write_pragmas(conn)
    conn.execute("CREATE TABLE hash_index (file_hash TEXT PRIMARY KEY)")
    conn.execute("""CREATE TABLE sources (
        source TEXT PRIMARY KEY, file_hash TEXT NOT NULL,
        size INTEGER, modified REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))""")
    conn.execute("""CREATE TABLE files (
        path TEXT PRIMARY KEY, source TEXT NOT NULL, aspect_ratio REAL,
        FOREIGN KEY(source) REFERENCES sources(source))""")
    conn.execute("""CREATE TABLE meta_info (
        path TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path))""")
    conn.execute("""CREATE TABLE tags (
        file_hash TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))""")
    conn.execute("""CREATE VIEW files_full AS
        SELECT i.path, i.source, i.aspect_ratio,
               s.file_hash, s.size, s.modified
        FROM files i JOIN sources s ON s.source = i.source""")
    conn.executescript("""
        CREATE INDEX idx_meta_key_num ON meta_info(key, value_num);
    """)

    for path in files or []:
        fhash = hashlib.md5(path.encode()).hexdigest()
        source = path
        conn.execute("INSERT OR IGNORE INTO hash_index VALUES (?)", (fhash,))
        conn.execute("INSERT INTO sources VALUES (?,?,?,?)", (source, fhash, 100, 1.0))
        conn.execute("INSERT INTO files VALUES (?,?,?)", (path, source, 1.0))

    for path, key, value_str, value_num in meta_num or []:
        conn.execute("INSERT OR REPLACE INTO meta_info VALUES (?,?,?,?)", (path, key, value_str, value_num))

    conn.commit()
    conn.close()
    return db_path


def _query(db_path, params):
    sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
    if sql is None:
        return set()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    apply_read_pragmas(conn)
    rows = conn.execute(sql, bind).fetchall()
    conn.close()
    return {r[0] for r in rows}


class TestIsDateKey:
    def test_known_keys(self):
        assert is_date_key("modified") is True
        assert is_date_key("created") is True
        assert is_date_key("collected") is True

    def test_exif_datetime(self):
        assert is_date_key("exif.DateTimeOriginal") is True
        assert is_date_key("exif.DateTime") is True
        assert is_date_key("exif.DateTimeDigitized") is True

    def test_gps_date(self):
        assert is_date_key("exif.GPSDateStamp") is True
        assert is_date_key("exif.GPSTimeStamp") is True

    def test_non_date_keys(self):
        assert is_date_key("size") is False
        assert is_date_key("name") is False
        assert is_date_key("path") is False
        assert is_date_key("exif.LensMake") is False
        assert is_date_key("exif.Model") is False


class TestDateStrToEpoch:
    def test_valid_date(self):
        result = _date_str_to_epoch("2024/01/15")
        assert isinstance(result, float)
        assert result > 0

    def test_end_of_day(self):
        start = _date_str_to_epoch("2024/01/15", end_of_day=False)
        end = _date_str_to_epoch("2024/01/15", end_of_day=True)
        assert end > start
        assert end - start == 86399

    def test_empty_string(self):
        assert _date_str_to_epoch("") is None

    def test_none(self):
        assert _date_str_to_epoch(None) is None

    def test_invalid_format(self):
        assert _date_str_to_epoch("not-a-date") is None


class TestPresetToEpoch:
    def test_days(self):
        now = time.time()
        result = _preset_to_epoch(7, "days")
        expected = now - 7 * 86400
        assert abs(result - expected) < 1.0

    def test_hours(self):
        now = time.time()
        result = _preset_to_epoch(24, "hours")
        expected = now - 24 * 3600
        assert abs(result - expected) < 1.0

    def test_weeks(self):
        now = time.time()
        result = _preset_to_epoch(2, "weeks")
        expected = now - 2 * 604800
        assert abs(result - expected) < 1.0

    def test_months(self):
        result = _preset_to_epoch(1, "months")
        now = time.time()
        assert result < now
        assert now - result > 25 * 86400
        assert now - result < 35 * 86400

    def test_years(self):
        result = _preset_to_epoch(1, "years")
        now = time.time()
        assert result < now
        assert now - result > 360 * 86400
        assert now - result < 370 * 86400

    def test_ref_time_days(self):
        ref = _date_str_to_epoch("2024/06/15", end_of_day=True)
        result = _preset_to_epoch(7, "days", ref_time=ref)
        assert abs(result - (ref - 7 * 86400)) < 1.0

    def test_ref_time_months(self):
        from datetime import datetime, timezone

        ref = datetime(2024, 6, 15, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        result = _preset_to_epoch(1, "months", ref_time=ref)
        expected = datetime(2024, 5, 15, 23, 59, 59, tzinfo=timezone.utc).timestamp()
        assert abs(result - expected) < 1.0


class TestResolveDateValue:
    def test_today(self):
        result = _resolve_date_value("today")
        assert isinstance(result, float)
        assert result > 0

    def test_today_end_of_day(self):
        start = _resolve_date_value("today", end_of_day=False)
        end = _resolve_date_value("today", end_of_day=True)
        assert end > start
        assert end - start == 86399

    def test_date_string(self):
        result = _resolve_date_value("2024/06/15")
        expected = _date_str_to_epoch("2024/06/15")
        assert result == expected

    def test_empty(self):
        assert _resolve_date_value("") is None

    def test_none_str(self):
        assert _resolve_date_value(None) is None


class TestResolvePresetRef:
    def test_today_string(self):
        now = time.time()
        result = _resolve_preset_ref("today")
        assert abs(result - now) < 1.0

    def test_empty_string(self):
        now = time.time()
        result = _resolve_preset_ref("")
        assert abs(result - now) < 1.0

    def test_date_string(self):
        result = _resolve_preset_ref("2024/06/15")
        expected = _date_str_to_epoch("2024/06/15", end_of_day=True)
        assert result == expected

    def test_invalid_string(self):
        now = time.time()
        result = _resolve_preset_ref("not-a-date")
        assert abs(result - now) < 1.0


class TestBuildPathQuery:
    def test_preset_returns_between(self):
        params = {"target_key": "modified", "mode": "preset", "preset_value": 7, "preset_unit": "days"}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is not None
        assert "BETWEEN" in sql
        assert len(bind) == 3
        assert bind[0] == "modified"
        assert bind[1] < bind[2]

    def test_preset_with_date_ref(self):
        params = {
            "target_key": "modified",
            "mode": "preset",
            "preset_value": 7,
            "preset_unit": "days",
            "preset_ref": "2024/06/15",
        }
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is not None
        assert "BETWEEN" in sql
        ref_epoch = _date_str_to_epoch("2024/06/15", end_of_day=True)
        assert abs(bind[2] - ref_epoch) < 1.0

    def test_range_both(self):
        params = {"target_key": "modified", "mode": "range", "range_from": "2024/01/01", "range_to": "2024/12/31"}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is not None
        assert "BETWEEN" in sql
        assert len(bind) == 3

    def test_range_from_only(self):
        params = {"target_key": "modified", "mode": "range", "range_from": "2024/01/01", "range_to": ""}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is not None
        assert "<=" in sql
        assert len(bind) == 2

    def test_range_to_only(self):
        params = {"target_key": "modified", "mode": "range", "range_from": "", "range_to": "2024/12/31"}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is not None
        assert ">=" in sql
        assert len(bind) == 2

    def test_range_both_empty(self):
        params = {"target_key": "modified", "mode": "range", "range_from": "", "range_to": ""}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is None

    def test_preset_zero_value(self):
        params = {"target_key": "modified", "mode": "preset", "preset_value": 0, "preset_unit": "days"}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is None

    def test_invalid_mode(self):
        params = {"target_key": "modified", "mode": "invalid"}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is None

    def test_range_today(self):
        params = {"target_key": "modified", "mode": "range", "range_from": "today", "range_to": ""}
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert sql is not None
        assert "<=" in sql

    def test_range_swaps_min_max(self):
        params = {
            "target_key": "modified",
            "mode": "range",
            "range_from": "2024/12/31",
            "range_to": "2024/01/01",
        }
        sql, bind = DateRangeFilter.build_path_query(params, lambda p: p)
        assert "BETWEEN" in sql
        assert bind[1] < bind[2]


class TestQueryExecution:
    def test_preset_filters_recent(self, tmp_path):
        now = time.time()
        files = ["a.png", "b.png", "c.png"]
        meta = [
            ("a.png", "modified", str(now), now),
            ("b.png", "modified", str(now - 3600), now - 3600),
            ("c.png", "modified", str(now - 86400 * 30), now - 86400 * 30),
        ]
        db = _setup_db(tmp_path, files=files, meta_num=meta)
        result = _query(db, {"target_key": "modified", "mode": "preset", "preset_value": 7, "preset_unit": "days"})
        assert "a.png" in result
        assert "b.png" in result
        assert "c.png" not in result

    def test_range_filters_between(self, tmp_path):
        from datetime import datetime, timezone

        t1 = datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp()
        t2 = datetime(2024, 6, 15, tzinfo=timezone.utc).timestamp()
        t3 = datetime(2024, 12, 1, tzinfo=timezone.utc).timestamp()
        files = ["a.png", "b.png", "c.png"]
        meta = [
            ("a.png", "modified", str(t1), t1),
            ("b.png", "modified", str(t2), t2),
            ("c.png", "modified", str(t3), t3),
        ]
        db = _setup_db(tmp_path, files=files, meta_num=meta)
        result = _query(
            db,
            {
                "target_key": "modified",
                "mode": "range",
                "range_from": "2024/05/01",
                "range_to": "2024/08/01",
            },
        )
        assert "a.png" not in result
        assert "b.png" in result
        assert "c.png" not in result

    def test_exif_datetime_key(self, tmp_path):
        from datetime import datetime, timezone

        t1 = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        t2 = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        files = ["photo1.jpg", "photo2.jpg"]
        meta = [
            ("photo1.jpg", "exif.DateTimeOriginal", "2024:06:15 10:00:00", t1),
            ("photo2.jpg", "exif.DateTimeOriginal", "2023:01:01 10:00:00", t2),
        ]
        db = _setup_db(tmp_path, files=files, meta_num=meta)
        result = _query(
            db,
            {
                "target_key": "exif.DateTimeOriginal",
                "mode": "range",
                "range_from": "2024/01/01",
                "range_to": "2024/12/31",
            },
        )
        assert "photo1.jpg" in result
        assert "photo2.jpg" not in result

    def test_null_value_num_excluded(self, tmp_path):
        files = ["a.png"]
        meta = [("a.png", "exif.LensMake", "Canon", None)]
        db = _setup_db(tmp_path, files=files, meta_num=meta)
        result = _query(
            db,
            {
                "target_key": "exif.LensMake",
                "mode": "preset",
                "preset_value": 7,
                "preset_unit": "days",
            },
        )
        assert len(result) == 0


class TestInheritableParams:
    def test_inherits_target_key(self):
        params = {"target_key": "created", "mode": "preset", "preset_value": 7, "preset_unit": "days"}
        inherited = DateRangeFilter.inheritable_params(params)
        assert inherited == {"target_key": "created"}
