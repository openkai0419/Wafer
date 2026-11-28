import pytest

from wafer.app.indexer.db_writer import DatabaseWriter


class CollectionDB:
    def __init__(self, writer: DatabaseWriter):
        self.writer = writer

    def add_source(self, source: str, file_hash: str):
        self.writer.upsert_sources([(source, file_hash, 1, 1.0)], [(source, source, 1.0)])

    def dispatch(self, source: str, plugin: str):
        self.writer.insert_pending([source], [plugin])
        self.writer.mark_dispatched([source], plugin)

    def status(self, source: str, plugin: str) -> str | None:
        row = self._query("SELECT status FROM collection_status WHERE source = ? AND collector = ?", source, plugin)
        return row[0][0] if row else None

    def meta(self, path: str) -> dict[str, str]:
        return dict(self._query("SELECT key, value FROM meta_info WHERE path = ?", path))

    def tags(self, file_hash: str) -> dict[str, str]:
        return dict(self._query("SELECT key, value FROM tags WHERE file_hash = ?", file_hash))

    def _query(self, sql: str, *params) -> list[tuple]:
        return self.writer._db.conn.execute(sql, params).fetchall()


@pytest.fixture
def collection_db(tmp_path):
    writer = DatabaseWriter(tmp_path / "test.db")
    writer.start()
    writer.initialize()
    yield CollectionDB(writer)
    writer.close()
