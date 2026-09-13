import pytest
from wafer.plugin.parser.base import (
    BaseParser,
    BaseParserPlugin,
    BaseSingletonParser,
    ParserResult,
)


class DummyParser(BaseParserPlugin):
    NAME = "dummy"
    TRIGGER_KEYS = ("exif.parameters",)
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True, meta_info={"sd.prompt": "test"})


class DummySingleton(BaseSingletonParser):
    NAME = "dummy_s"
    TRIGGER_KEYS = ("exif.Comment",)
    DEFAULT_ENABLED = True

    def process(self, path, file_info, metadata):
        return ParserResult(source=path, status=True)


def test_parser_result_to_dict():
    r = ParserResult(source="/a.png", status=True, meta_info={"k": "v"})
    d = r.to_dict()
    assert d["source"] == "/a.png"
    assert d["status"] is True
    assert d["meta_info"] == {"k": "v"}
    assert "tags" not in d
    assert "delete_meta_keys" not in d
    assert "delete_tag_keys" not in d


def test_parser_result_with_delete_meta_keys():
    r = ParserResult(source="/a.png", status=True, delete_meta_keys=["exif.parameters"])
    d = r.to_dict()
    assert d["delete_meta_keys"] == ["exif.parameters"]
    assert "delete_tag_keys" not in d


def test_parser_result_with_delete_tag_keys():
    r = ParserResult(source="/a.png", status=True, delete_tag_keys=["duplicate.has_duplicate"])
    d = r.to_dict()
    assert d["delete_tag_keys"] == ["duplicate.has_duplicate"]
    assert "delete_meta_keys" not in d


def test_parser_result_fail():
    r = ParserResult(source="/a.png", status=False)
    d = r.to_dict()
    assert d["status"] is False
    assert "meta_info" not in d


def test_base_parser_plugin_batch_size():
    assert DummyParser.BATCH_SIZE == 1200
    assert DummyParser.MAX_WORKERS == 1
    assert DummyParser.MAX_TIMEOUT == 300.0


def test_base_singleton_parser_batch_size():
    assert DummySingleton.BATCH_SIZE == 300
    assert DummySingleton.MAX_WORKERS == 1
    assert DummySingleton.MAX_TIMEOUT == 300.0


def test_trigger_keys():
    assert DummyParser.TRIGGER_KEYS == ("exif.parameters",)
    assert DummySingleton.TRIGGER_KEYS == ("exif.Comment",)


def test_process():
    d = DummyParser()
    result = d.process("/a.png", (0.0, 0), {"exif.parameters": "steps:20"})
    assert result.status is True
    assert result.meta_info == {"sd.prompt": "test"}


def test_inheritance():
    assert issubclass(BaseParserPlugin, BaseParser)
    assert issubclass(BaseSingletonParser, BaseParser)
    assert not issubclass(BaseParserPlugin, BaseSingletonParser)


def test_parser_result_with_update_hash():
    r = ParserResult(source="/a.png", status=True, update_hash="full")
    d = r.to_dict()
    assert d["update_hash"] == "full"
    assert "update_hash" not in ParserResult(source="/a.png", status=True).to_dict()


def test_query_db_without_db_name_raises():
    parser = DummyParser()
    assert parser.db_name == ""
    with pytest.raises(RuntimeError):
        parser.query_db("SELECT 1")


def test_query_db_reads_assigned_database(tmp_path, monkeypatch):
    from wafer.core.db.file_db import FileDB
    import wafer.utils.paths as paths

    db_path = tmp_path / "querydb.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.upsert_batches([("src1", "hash1", 100, 1.0)], [("src1", "src1", 1.0)], [], [])
    db.close()
    monkeypatch.setattr(paths, "data_db_path", lambda name: str(db_path))

    parser = DummyParser()
    parser.db_name = "querydb"
    try:
        assert parser.query_db("SELECT COUNT(*) FROM sources WHERE file_hash = ?", ("hash1",)) == [(1,)]
    finally:
        parser.shutdown()
    assert parser._reader is None
