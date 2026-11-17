import pytest

from wafer.builtins.filters import TextFilter
from wafer.builtins.folder_manager.sources import folder_sources, query_sources
from wafer.core.common.virtual_paths import build_virtual_path
from wafer.core.db.file_db import FileDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "folders.db")
    file_db = FileDB(db_path)
    file_db.start()
    file_db.initialize_database()
    zip_path = "C:/lib/pack.zip"
    plain = ["C:/lib/a.png", "C:/lib/sub/b.png", "C:/lib/sub/deep/c.png", "C:/other/d.png"]
    members = [build_virtual_path(zip_path, "x/1.png"), build_virtual_path(zip_path, "2.png")]
    sources = [(p, f"hash_{i}", 100, 1.0) for i, p in enumerate([*plain, zip_path])]
    images = [(p, p, p.rsplit("/", 1)[1], 1.0, None) for p in [*plain, zip_path]]
    images += [(m, zip_path, m.rsplit("/", 1)[1], 1.0, "zip") for m in members]
    metas = [(p, "Comment", "cat", None) for p in ("C:/lib/a.png", "C:/lib/sub/deep/c.png")]
    file_db.upsert_basic_sources(sources, images, metas)
    file_db.conn.execute("ANALYZE")
    file_db.conn.commit()
    file_db.close()
    return db_path


def test_direct_sources_are_only_the_folder_itself(db):
    assert sorted(folder_sources(db, ["C:/lib"], recursive=False)) == ["C:/lib/a.png", "C:/lib/pack.zip"]


def test_recursive_sources_include_every_subfolder(db):
    assert sorted(folder_sources(db, ["C:/lib"], recursive=True)) == [
        "C:/lib/a.png",
        "C:/lib/pack.zip",
        "C:/lib/sub/b.png",
        "C:/lib/sub/deep/c.png",
    ]


def test_query_narrows_folder_sources(db):
    entries = [(TextFilter, {"keys": ["Comment"], "keywords": "cat"}, None)]
    assert sorted(folder_sources(db, ["C:/lib"], True, entries)) == ["C:/lib/a.png", "C:/lib/sub/deep/c.png"]


def test_virtual_paths_count_as_their_source(db):
    assert query_sources(db, []).count("C:/lib/pack.zip") == 1


def test_several_folders_are_combined_without_duplicates(db):
    assert sorted(folder_sources(db, ["C:/lib/sub", "C:/lib/sub/deep"], True)) == [
        "C:/lib/sub/b.png",
        "C:/lib/sub/deep/c.png",
    ]
