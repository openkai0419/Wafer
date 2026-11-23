import pytest
from wafer.plugin.parser.base import (
    BaseParser,
    BaseParserPlugin,
    BaseSingletonParser,
    ParserResult,
    ReaderClosed,
    required_collectors,
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


def test_shutdown_is_safe_when_reader_never_opened():
    parser = DummyParser()
    parser.shutdown()
    assert parser._reader is None


def test_shutdown_waits_for_in_flight_query_lock_before_closing(tmp_path, monkeypatch):
    import threading
    from wafer.core.db.file_db import FileDB
    import wafer.core.common.paths as paths

    db_path = tmp_path / "querydb_shutdown_race.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.close()
    monkeypatch.setattr(paths, "data_db_path", lambda name: str(db_path))

    parser = DummyParser()
    parser.db_name = "querydb_shutdown_race"
    parser.query_db("SELECT 1")  # establishes _reader/_reader_lock

    errors = []
    lock_held = threading.Event()
    release_lock = threading.Event()

    def hold_query_lock():
        try:
            with parser._reader_lock:
                lock_held.set()
                release_lock.wait(timeout=5)
        except Exception as e:
            errors.append(e)

    holder = threading.Thread(target=hold_query_lock)
    holder.start()
    assert lock_held.wait(timeout=5)

    shutdown_thread = threading.Thread(target=parser.shutdown)
    shutdown_thread.start()

    release_lock.set()
    holder.join(timeout=5)
    shutdown_thread.join(timeout=5)

    assert not errors
    assert parser._reader is None


def test_query_db_reads_assigned_database(tmp_path, monkeypatch):
    from wafer.core.db.file_db import FileDB
    import wafer.core.common.paths as paths

    db_path = tmp_path / "querydb.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.upsert_basic_sources([("src1", "hash1", 100, 1.0)], [("src1", "src1", 1.0)])
    db.close()
    monkeypatch.setattr(paths, "data_db_path", lambda name: str(db_path))

    parser = DummyParser()
    parser.db_name = "querydb"
    try:
        assert parser.query_db("SELECT COUNT(*) FROM sources WHERE file_hash = ?", ("hash1",)) == [(1,)]
        connections = [parser.read_db(lambda conn: conn), parser.read_db(lambda conn: conn)]
        assert connections[0] is connections[1] is parser._reader
    finally:
        parser.shutdown()
    assert parser._reader is None


def reader_parser(tmp_path, monkeypatch, name):
    from wafer.core.db.file_db import FileDB
    import wafer.core.common.paths as paths

    db_path = tmp_path / f"{name}.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    db.close()
    monkeypatch.setattr(paths, "data_db_path", lambda _name: str(db_path))
    parser = DummyParser()
    parser.db_name = name
    parser.query_db("SELECT 1")
    return parser


def test_read_after_shutdown_raises_instead_of_reopening(tmp_path, monkeypatch):
    parser = reader_parser(tmp_path, monkeypatch, "closed_reader")
    parser.shutdown()
    with pytest.raises(ReaderClosed):
        parser.query_db("SELECT 1")
    assert parser._reader is None


def test_read_waiting_while_the_reader_closes_raises(tmp_path, monkeypatch):
    import threading

    parser = reader_parser(tmp_path, monkeypatch, "closing_reader")
    reader = parser._reader
    outcome = []
    waiting = threading.Event()
    lock = threading.Lock()

    class WaitingLock:
        def __enter__(self):
            waiting.set()
            lock.acquire()

        def __exit__(self, *exc):
            lock.release()

    parser._reader_lock = WaitingLock()
    lock.acquire()

    def read():
        try:
            outcome.append(parser.read_db(lambda conn: "read"))
        except ReaderClosed as e:
            outcome.append(e)

    thread = threading.Thread(target=read)
    thread.start()
    assert waiting.wait(5)
    parser._reader = None
    lock.release()
    thread.join(5)
    reader.close()
    assert len(outcome) == 1 and isinstance(outcome[0], ReaderClosed)


def test_base_classes_are_abstract():
    for base in (BaseParser, BaseParserPlugin, BaseSingletonParser):
        with pytest.raises(TypeError):
            base()


def test_notify_to_sends_ipc():
    from unittest.mock import MagicMock, patch

    mock_node = MagicMock()
    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = mock_node

    with patch("wafer.qt.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseParserPlugin.notify_to("novelai")

    mock_node.send.assert_called_once_with("plugin.notify", None, dst="parser-novelai", db="")


def test_notify_to_reaches_the_parser_of_the_given_database():
    from unittest.mock import MagicMock, patch

    mock_node = MagicMock()
    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = mock_node

    with patch("wafer.qt.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseParserPlugin.notify_to("mapping", db="work")

    mock_node.send.assert_called_once_with("plugin.notify", None, dst="parser-mapping", db="work")


def test_notify_to_no_node():
    from unittest.mock import MagicMock, patch

    mock_registry = MagicMock()
    mock_registry.resolve_node.return_value = None

    with patch("wafer.qt.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
        BaseParserPlugin.notify_to("novelai")


def test_required_collectors_groups_keys_by_collector():
    assert required_collectors(("exiftool.PNG:Comment", "exiftool.EXIF:Make", "ffmpeg.format")) == {
        "exiftool": ["PNG:Comment", "EXIF:Make"],
        "ffmpeg": ["format"],
    }


def test_required_collectors_meta_key_with_dot():
    assert required_collectors(("exiftool.a.b",)) == {"exiftool": ["a.b"]}


def test_required_collectors_ignores_malformed():
    assert required_collectors(()) == {}
    assert required_collectors(("nodot", ".key", "collector.")) == {}
