import pytest

from wafer.builtins.commands import folder_files as folder_files_module
from wafer.builtins.commands.folder_files import folder_sources, narrows, query_sources
from wafer.builtins.filters import DirectoryFilter, TextFilter
from wafer.core.common.virtual_paths import build_virtual_path
from wafer.core.db.file_db import FileDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "folders.db")
    file_db = FileDB(db_path)
    file_db.start()
    file_db.initialize_database()
    zip_path = "C:/lib/pack.zip"
    plain = ["C:/lib/a.png", "C:/lib/sub/b.png", "C:/lib/sub/deep/c.png", "C:/other/d.png", "C:/root.png"]
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


def text_entry(keywords, keys=("path",), op=None):
    return (TextFilter, {"keys": list(keys) if keys is not None else None, "keywords": keywords}, op)


def test_only_entries_that_filter_count_as_a_query():
    assert not narrows([])
    assert not narrows([text_entry("")])
    assert not narrows([text_entry(""), text_entry("  ", op="AND")])
    assert narrows([text_entry("cat", ["Comment"])])
    assert narrows([text_entry(""), text_entry("cat", ["Comment"], op="AND")])
    assert narrows([text_entry("", ["Comment"])])
    assert narrows([text_entry("", None)])
    assert narrows([(DirectoryFilter, {"directories": ["C:/lib"]}, None)])


def test_post_filters_count_as_a_query():
    class PostOnly(TextFilter):
        NAME = ""

        @classmethod
        def build_path_query(cls, params, normalize_path):
            return None, []

        @classmethod
        def post_filter(cls, params, rows):
            return rows

    assert narrows([(PostOnly, {}, None)])


def test_without_a_query_sources_come_from_the_sources_table(db, monkeypatch):
    expected_all = sorted(folder_files_module.composed_sources(db, []))
    monkeypatch.setattr(folder_files_module, "composed_sources", lambda *args: pytest.fail("composer used without a query"))
    assert sorted(query_sources(db, [text_entry("")])) == expected_all
    assert sorted(folder_sources(db, ["C:/lib"], False, [text_entry("")])) == ["C:/lib/a.png", "C:/lib/pack.zip"]
    assert sorted(folder_sources(db, ["C:/lib/sub", "C:/lib/sub/deep"], True)) == ["C:/lib/sub/b.png", "C:/lib/sub/deep/c.png"]
    assert folder_sources(db, ["C:/li"], True) == []
    assert folder_sources(db, ["C:/"], False) == ["C:/root.png"]
    assert sorted(folder_sources(db, ["C:/lib", "C:/lib/sub/deep"], False)) == ["C:/lib/a.png", "C:/lib/pack.zip", "C:/lib/sub/deep/c.png"]


def test_a_missing_database_has_no_sources(tmp_path):
    assert folder_sources(str(tmp_path / "missing.db"), ["C:/lib"], True) == []
    assert query_sources(str(tmp_path / "missing.db"), []) == []
