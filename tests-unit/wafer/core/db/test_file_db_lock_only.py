from wafer.core.db.file_db import FileDB


def _make_db(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    return db


def _seed(db, source="src1", file_hash="h1"):
    db.upsert_batches(
        [(source, file_hash, 100, 1.0)],
        [(source, source, 1.5)],
        [],
        [],
    )


def _get(db, fh, key):
    cur = db.read_conn.cursor()
    row = cur.execute(
        "SELECT value, locked FROM tags WHERE file_hash=? AND key=?", (fh, key)
    ).fetchone()
    cur.close()
    return row


def test_lock_only_does_not_change_value(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    db.apply_user_tags("src1", [("rating", "5", 5.0, 0)], [])
    fh, applied, deleted = db.apply_user_tags(
        "src1", [("rating", "ignored", None, 1)], [], lock_only=True
    )
    assert applied == ["rating"]
    val, locked = _get(db, "h1", "rating")
    assert val == "5"
    assert locked == 1
    db.close()


def test_lock_only_skips_missing_keys(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    fh, applied, deleted = db.apply_user_tags(
        "src1", [("ghost", "x", None, 1)], [], lock_only=True
    )
    assert applied == []
    assert _get(db, "h1", "ghost") is None
    db.close()


def test_locked_delete_returns_empty_deleted(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    db.apply_user_tags("src1", [("k1", "v1", None, 1)], [])
    fh, applied, deleted = db.apply_user_tags("src1", [], ["k1"])
    assert deleted == []
    assert _get(db, "h1", "k1") is not None
    db.close()


def test_migration_carries_lock_flag(tmp_path):
    db = _make_db(tmp_path)
    _seed(db)
    db.apply_user_tags("src1", [("user", "U", None, 1), ("free", "F", None, 0)], [])
    db.upsert_batches([("src1", "h2", 100, 2.0)], [("src1", "src1", 1.5)], [], [])
    assert _get(db, "h2", "user") == ("U", 1)
    assert _get(db, "h2", "free") == ("F", 0)
    db.close()
