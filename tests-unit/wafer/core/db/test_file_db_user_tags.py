from wafer.core.db.file_db import FileDB


def _make_db(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    return db


def _seed(db, source="src1", file_hash="h1", tag_key="rating", tag_value="5"):
    db.upsert_batches(
        [(source, file_hash, 100, 1.0)],
        [(source, source, 1.5)],
        [],
        [(file_hash, tag_key, tag_value, None)],
    )


def _get_tag(db, file_hash, key):
    cur = db.read_conn.cursor()
    row = cur.execute(
        "SELECT value, locked FROM tags WHERE file_hash=? AND key=?",
        (file_hash, key),
    ).fetchone()
    cur.close()
    return row


def _apply(db, path, upserts, deletes, **kwargs):
    res = db.apply_user_tags([path], upserts, deletes, **kwargs)
    if path not in res:
        return None, [], []
    return res[path]


def test_collector_upsert_respects_lock(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    _apply(db, "src1", [("rating", "9", 9.0, 1)], [])
    db.upsert_batches([], [], [], [("h1", "rating", "3", 3.0)])
    val, locked = _get_tag(db, "h1", "rating")
    assert val == "9"
    assert locked == 1
    db.close()


def test_user_upsert_overwrites_lock(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    _apply(db, "src1", [("rating", "9", 9.0, 1)], [])
    _apply(db, "src1", [("rating", "7", 7.0, 0)], [])
    val, locked = _get_tag(db, "h1", "rating")
    assert val == "7"
    assert locked == 0
    db.close()


def test_apply_user_tags_delete_respects_lock(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    _apply(db, "src1", [("rating", "9", 9.0, 1), ("color", "red", None, 0)], [])
    file_hash, applied, deleted = _apply(db, "src1", [], ["rating", "color"])
    assert file_hash == "h1"
    assert deleted == ["color"]
    assert _get_tag(db, "h1", "rating") is not None
    assert _get_tag(db, "h1", "color") is None
    db.close()


def test_migrate_tags_on_hash_change_preserves_all(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    _apply(db, "src1", [("locked_tag", "L", None, 1), ("free_tag", "F", None, 0)], [])
    db.upsert_batches([("src1", "h2", 100, 2.0)], [("src1", "src1", 1.5)], [], [])
    assert _get_tag(db, "h2", "rating") is not None
    assert _get_tag(db, "h2", "locked_tag") == ("L", 1)
    assert _get_tag(db, "h2", "free_tag") == ("F", 0)
    db.close()


def test_apply_user_tags_unknown_path_returns_empty(tmp_path):
    db = _make_db(tmp_path)
    res = db.apply_user_tags(["missing_path"], [("k", "v", None, 0)], [])
    assert res == {}
    db.close()


def test_rename_preserves_lock_and_value(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    _apply(db, "src1", [("rating", "9", 9.0, 1)], [])
    file_hash, applied, deleted = _apply(
        db, "src1", [], [],
        renames=[("rating", "score", "9", 9.0, 1)],
    )
    assert file_hash == "h1"
    assert applied == ["score"]
    assert deleted == ["rating"]
    assert _get_tag(db, "h1", "rating") is None
    assert _get_tag(db, "h1", "score") == ("9", 1)
    db.close()


def test_rename_with_value_and_lock_change(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    file_hash, applied, deleted = _apply(
        db, "src1", [], [],
        renames=[("rating", "stars", "10", 10.0, 1)],
    )
    assert applied == ["stars"]
    assert deleted == ["rating"]
    assert _get_tag(db, "h1", "stars") == ("10", 1)


def test_rename_collision_skipped(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    _apply(db, "src1", [("color", "red", None, 0)], [])
    file_hash, applied, deleted = _apply(
        db, "src1", [], [],
        renames=[("rating", "color", "5", 5.0, 0)],
    )
    assert applied == []
    assert deleted == []
    assert _get_tag(db, "h1", "rating") == ("5", 0)
    assert _get_tag(db, "h1", "color") == ("red", 0)
    db.close()


def test_rename_unknown_old_key_no_change(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    file_hash, applied, deleted = _apply(
        db, "src1", [], [],
        renames=[("ghost", "stars", "1", 1.0, 0)],
    )
    assert applied == []
    assert deleted == []
    assert _get_tag(db, "h1", "stars") is None
    db.close()


def test_apply_user_tags_multiple_paths(tmp_path):
    db = _make_db(tmp_path)
    db.upsert_batches(
        [('p1', 'h1', 100, 1.0), ('p2', 'h2', 100, 1.0)],
        [('p1', 'p1', 1.5), ('p2', 'p2', 1.5)],
        [], [],
    )
    results = db.apply_user_tags(
        ['p1', 'p2', 'missing'],
        [('mark.1', '1', 1.0, 0)],
        [],
    )
    assert set(results.keys()) == {'p1', 'p2'}
    assert results['p1'][0] == 'h1'
    assert 'mark.1' in results['p1'][1]
    assert _get_tag(db, 'h1', 'mark.1') is not None
    assert _get_tag(db, 'h2', 'mark.1') is not None
    delres = db.apply_user_tags(['p1', 'p2'], [], ['mark.1'])
    assert 'mark.1' in delres['p1'][2]
    assert _get_tag(db, 'h1', 'mark.1') is None
    db.close()
