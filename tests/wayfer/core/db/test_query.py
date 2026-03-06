import os
import sqlite3
import time
import pytest
from pathlib import Path
from wayfer.core.db.query import SearchQuery, FileSearchEngine
from wayfer.core.db.file_db import FileDB
from wayfer.utils.paths import normalize_path


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def populated_db(db_path):
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    sources, images, metas, tags = [], [], [], []
    for i in range(200):
        d = "C:/photos/vacation" if i < 100 else "C:/photos/work"
        path = f"{d}/img_{i:04d}.jpg"
        source = path
        fhash = f"hash_{i:04d}"
        sources.append((source, fhash, 1000 + i, float(1700000000 + i), float(1700000000 + i), float(1700000000 + i), None))
        images.append((path, source, f"img_{i:04d}.jpg", 1.5))
        metas.append((path, "dpi", f"{72 + (i % 4) * 24}"))
        metas.append((path, "Comment", f"photo number {i}"))
        if i % 3 == 0:
            metas.append((path, "Artist", f"photographer_{i % 5}"))
        tags.append((fhash, "rating", f"{(i % 5) + 1}"))
        if i % 2 == 0:
            tags.append((fhash, "category", "landscape" if i < 100 else "office"))
    db.upsert_batches(sources, images, metas, tags)
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path


def np(p):
    return normalize_path(p)


class TestSearchQuerySubquery:

    def test_keys_meta_info(self, populated_db):
        q = SearchQuery(keys=["dpi"])
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "meta_info" in sql
        assert "kv_meta" not in sql

    def test_keys_filepath(self, populated_db):
        q = SearchQuery(keys=["__filepath__"])
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "files" in sql
        assert "meta_info" not in sql.split("UNION")[0]

    def test_no_keys_require_keys_true(self):
        q = SearchQuery(keys=None, require_keys=True)
        sql, params = q._make_subquery(np)
        assert sql is None

    def test_no_keys_require_keys_false(self, populated_db):
        q = SearchQuery(keys=None, require_keys=False)
        sql, params = q._make_subquery(np, require_keys_override=False)
        assert sql is not None
        assert "files" in sql
        assert "meta_info" in sql
        assert "tags" in sql

    def test_keyword_include(self, populated_db):
        q = SearchQuery(keys=["Comment"], keywords="photo", query_mode="LIKE")
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "LIKE" in sql

    def test_keyword_exclude(self, populated_db):
        q = SearchQuery(keys=["Comment"], keywords="-badword", keyword_separator=",")
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "NOT IN" in sql

    def test_directory_filter(self, populated_db):
        q = SearchQuery(keys=["dpi"], directories=["C:/photos/vacation"])
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "LIKE" in sql

    def test_directory_no_subfolders(self, populated_db):
        q = SearchQuery(keys=["dpi"], directories=["C:/photos/vacation"], include_subfolders=False)
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "NOT LIKE" in sql

    def test_empty_keyword_filtered(self):
        q = SearchQuery(keys=["__filepath__"], keywords="", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == []

    def test_dash_only_keyword_filtered(self):
        q = SearchQuery(keys=["__filepath__"], keywords="-", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == []

    def test_mixed_empty_keywords(self):
        q = SearchQuery(keys=["__filepath__"], keywords="a,,b,-,-c", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == ["a", "b"]
        assert exclude == ["c"]


class TestSearchQueryDataclass:

    def test_frozen_immutable(self):
        q = SearchQuery(keys=["dpi"])
        import pytest
        with pytest.raises(AttributeError):
            q.keys = ("other",)

    def test_list_args_converted_to_tuple(self):
        q = SearchQuery(keys=["a", "b"], keywords=["c"], directories=["D:/x"])
        assert isinstance(q.keys, tuple)
        assert isinstance(q.keywords, tuple)
        assert isinstance(q.directories, tuple)
        assert q.keys == ("a", "b")

    def test_none_args_stay_none(self):
        q = SearchQuery()
        assert q.keys is None
        assert q.keywords is None
        assert q.directories is None

    def test_string_args_stay_string(self):
        q = SearchQuery(keys="single_key", keywords="word")
        assert isinstance(q.keys, str)
        assert isinstance(q.keywords, str)

    def test_equality(self):
        q1 = SearchQuery(keys=["dpi"], keywords="test")
        q2 = SearchQuery(keys=["dpi"], keywords="test")
        assert q1 == q2

    def test_inequality(self):
        q1 = SearchQuery(keys=["dpi"])
        q2 = SearchQuery(keys=["Artist"])
        assert q1 != q2

    def test_hashable(self):
        q1 = SearchQuery(keys=["dpi"], keywords="test")
        q2 = SearchQuery(keys=["dpi"], keywords="test")
        assert hash(q1) == hash(q2)
        s = {q1, q2}
        assert len(s) == 1

    def test_hash_differs(self):
        q1 = SearchQuery(keys=["dpi"])
        q2 = SearchQuery(keys=["Artist"])
        assert hash(q1) != hash(q2)


class TestFileSearchEngineGet:

    def test_get_by_meta_key(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["dpi"]))
        assert len(paths) == 200

    def test_get_by_filepath_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["__filepath__"], keywords="vacation"))
        assert all("vacation" in p for p in paths)
        assert len(paths) == 100

    def test_get_by_meta_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["Comment"], keywords="photo number 5", query_mode="LIKE"))
        assert len(paths) > 0

    def test_get_with_directory(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["dpi"], directories=["C:/photos/vacation"]))
        assert all("vacation" in p for p in paths)
        assert len(paths) == 100

    def test_get_with_directory_no_subfolders(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(
            SearchQuery(keys=["dpi"], directories=["C:/photos"], include_subfolders=False)
        )
        assert len(paths) == 0

    def test_get_with_exclude(self, populated_db):
        engine = FileSearchEngine(populated_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["Comment"]))
        excluded_paths, _, _ = engine.search(SearchQuery(keys=["Comment"], keywords="-number 0,", keyword_separator=","))
        assert len(excluded_paths) < len(all_paths)

    def test_get_sort_by_name(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="name", ascending=True))
        names = [os.path.basename(p) for p in paths]
        assert names == sorted(names)

    def test_get_sort_by_name_desc(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="name", ascending=False))
        names = [os.path.basename(p) for p in paths]
        assert names == sorted(names, reverse=True)

    def test_get_random(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="random"))
        assert len(paths) == 200

    def test_get_no_results(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["nonexistent_key"]))
        assert paths == []

    def test_get_glob_mode(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["__filepath__"], keywords="*vacation*", query_mode="GLOB"))
        assert len(paths) == 100


class TestFileSearchEngineListKeys:

    def test_list_all_keys(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery(directories=["C:/photos/vacation"])
        keys = engine.list_all_keys(q, sort_by_freq=True)
        key_names = [k[0] for k in keys]
        assert "__filepath__" in key_names
        assert "dpi" in key_names
        assert "Comment" in key_names

    def test_list_all_keys_no_filter(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery()
        keys = engine.list_all_keys(q)
        key_names = [k[0] for k in keys]
        assert "rating" in key_names
        assert "dpi" in key_names

    def test_list_all_keys_dedup(self, db_path):
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources = [("src1", "hash1", 100, 1.0, 1.0, 1.0, None)]
        images = [("c:/test/img.jpg", "src1", "img.jpg", 1.5)]
        metas = [("c:/test/img.jpg", "shared_key", "meta_val")]
        tags = [("hash1", "shared_key", "tag_val")]
        db.upsert_batches(sources, images, metas, tags)
        db.conn.commit()
        db.close()
        engine = FileSearchEngine(db_path)
        q = SearchQuery()
        keys = engine.list_all_keys(q, sort_by_freq=True)
        shared = [k for k in keys if k[0] == "shared_key"]
        assert len(shared) == 1
        assert shared[0][1] == 1


class TestFileSearchEngineCombined:

    def test_get_combined_union(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["__filepath__"], keywords="vacation", append_mode="OR")
        q2 = SearchQuery(keys=["__filepath__"], keywords="work", append_mode="OR")
        paths, aspects = engine.search_multi([q1, q2])
        assert len(paths) == 200

    def test_get_combined_intersect(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["dpi"], append_mode="OR")
        q2 = SearchQuery(keys=["__filepath__"], keywords="vacation", append_mode="AND")
        paths, aspects = engine.search_multi([q1, q2])
        assert all("vacation" in p for p in paths)

    def test_skipped_middle_query_preserves_intersect(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["dpi"], append_mode="OR")
        q2 = SearchQuery(keys=["nonexistent_key_xyz"], keywords="nope", append_mode="OR")
        q3 = SearchQuery(keys=["__filepath__"], keywords="vacation", append_mode="AND")
        paths, aspects = engine.search_multi([q1, q2, q3])
        assert all("vacation" in p for p in paths)
        assert len(paths) == 100


class TestExplainQueryPlan:

    def _plan_text(self, conn, sql, params=()):
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return "\n".join(r["detail"] for r in rows)

    def test_no_kv_meta_in_plan(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["dpi"])
        subq, params = q._make_subquery(np)
        sql = f"SELECT DISTINCT path FROM ({subq}) s0"
        plan = self._plan_text(engine.conn, sql, params)
        assert "kv_meta" not in plan.lower()
        assert "kv_all" not in plan.lower()

    def test_filepath_uses_files_directly(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["__filepath__"], keywords="vacation")
        subq, params = q._make_subquery(np)
        sql = f"SELECT DISTINCT path FROM ({subq}) s0"
        plan = self._plan_text(engine.conn, sql, params)
        assert "files" in plan.lower()

    def test_meta_key_uses_index(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["dpi"])
        subq, params = q._make_subquery(np)
        sql = f"SELECT DISTINCT path FROM ({subq}) s0"
        plan = self._plan_text(engine.conn, sql, params)
        assert "idx_meta_info_key_fid" in plan or "meta_info" in plan.lower()

    def test_full_get_plan(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["dpi"])
        subq, params = q._make_subquery(np)
        distinct_paths = f"SELECT DISTINCT path FROM ({subq}) s0"
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN ({distinct_paths}) AS s USING(path)
            ORDER BY m.name ASC
        """
        plan = self._plan_text(engine.conn, sql, params)
        assert "kv_meta" not in plan.lower()
        assert "kv_all" not in plan.lower()


class TestExplainQueryPlanRealDB:

    REAL_DB = os.environ.get("TEST_REAL_DB", "")

    @pytest.fixture
    def real_engine(self):
        if not self.REAL_DB or not os.path.exists(self.REAL_DB):
            pytest.skip("Set TEST_REAL_DB env var to a real .db path")
        return FileSearchEngine(self.REAL_DB)

    def _plan_and_time(self, engine, label, sql, params=()):
        assert engine._connect_if_needed()
        conn = engine.conn
        plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        plan = "\n".join(f"  [{r['id']}] {r['detail']}" for r in plan_rows)
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            rows = conn.execute(sql, params).fetchall()
            times.append(time.perf_counter() - t0)
        avg_ms = sum(times) / len(times) * 1000
        best_ms = min(times) * 1000
        print(f"\n{'='*60}")
        print(f"[{label}]")
        print(plan)
        print(f"  ROWS: {len(rows)}  AVG: {avg_ms:.1f}ms  BEST: {best_ms:.1f}ms")
        return plan, rows, avg_ms

    def test_meta_key_query(self, real_engine):
        assert real_engine._connect_if_needed()
        cur = real_engine.conn.cursor()
        top_key = cur.execute(
            "SELECT key FROM meta_info GROUP BY key ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()
        if not top_key:
            pytest.skip("No meta_info data")
        key = top_key[0]
        q = SearchQuery(keys=[key])
        subq, params = q._make_subquery(np)
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN (SELECT DISTINCT path FROM ({subq}) s0) AS s USING(path)
            ORDER BY m.name ASC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, f"meta key='{key}'", sql, params)
        assert "kv_meta" not in plan.lower()

    def test_filepath_query(self, real_engine):
        q = SearchQuery(keys=["__filepath__"], keywords="img")
        subq, params = q._make_subquery(np)
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN (SELECT DISTINCT path FROM ({subq}) s0) AS s USING(path)
            ORDER BY m.name ASC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, "__filepath__ keyword='img'", sql, params)
        assert "kv_meta" not in plan.lower()

    def test_directory_query(self, real_engine):
        assert real_engine._connect_if_needed()
        sample = real_engine.conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        if not sample:
            pytest.skip("No image data")
        parts = sample[0].replace("\\", "/").split("/")
        sample_dir = "/".join(parts[:4])
        q = SearchQuery(keys=["__filepath__"], directories=[sample_dir])
        subq, params = q._make_subquery(np)
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN (SELECT DISTINCT path FROM ({subq}) s0) AS s USING(path)
            ORDER BY m.name ASC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, f"directory='{sample_dir}'", sql, params)
        assert "kv_meta" not in plan.lower()

    def test_list_all_keys_query(self, real_engine):
        assert real_engine._connect_if_needed()
        sample = real_engine.conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        if not sample:
            pytest.skip("No image data")
        parts = sample[0].replace("\\", "/").split("/")
        sample_dir = "/".join(parts[:4])
        q = SearchQuery(directories=[sample_dir])
        subq, params = q._make_subquery(np, require_keys_override=False)
        sql = f"""
            SELECT key, COUNT(*) AS freq
            FROM ({subq}) AS items
            GROUP BY key
            ORDER BY freq DESC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, f"list_all_keys dir='{sample_dir}'", sql, params)
        assert "kv_meta" not in plan.lower()
