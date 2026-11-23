from wafer.plugin import BaseParserPlugin, ParserResult
from wafer.core.common.hashes import HASH_FAILED
from wafer.core.db.path_values import read_in_chunks

TAG = "has_duplicate"


class DuplicateParser(BaseParserPlugin):
    NAME = "duplicate"
    DISPLAY_NAME = "Duplicate"
    PRIORITY = 90
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("file_hash",)
    BATCH_SIZE = 600
    MAX_WORKERS = 1

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        return self.process_batch([path], {path: file_info}, {path: metadata})[0]

    def process_batch(self, paths: list[str], file_info: dict[str, tuple], metadata: dict[str, dict]) -> list[ParserResult]:
        hashes = {path: self.valid_hash(file_info[path]) for path in paths}
        counts, tagged = self.read_db(lambda conn: self.read_hash_state(conn, list(dict.fromkeys(h for h in hashes.values() if h))), ({}, set()))
        results = []
        for path in paths:
            file_hash = hashes[path]
            if not file_hash:
                results.append(ParserResult(source=path, status=False))
            elif counts.get(file_hash, 0) > 1:
                results.append(ParserResult(source=path, status=True, tags=None if file_hash in tagged else {TAG: "1"}))
            elif file_hash in tagged:
                results.append(ParserResult(source=path, status=True, delete_tag_keys=[f"{self.NAME}.{TAG}"]))
            else:
                results.append(ParserResult(source=path, status=True))
        return results

    @staticmethod
    def valid_hash(file_info: tuple) -> str | None:
        file_hash = file_info[2] if len(file_info) > 2 else None
        return None if not file_hash or file_hash == HASH_FAILED else file_hash

    def read_hash_state(self, conn, hashes: list[str]) -> tuple[dict[str, int], set[str]]:
        counts: dict[str, int] = {}
        tagged: set[str] = set()
        tag_key = f"{self.NAME}.{TAG}"

        def read(conn, chunk, placeholders):
            counts.update(conn.execute(f"SELECT file_hash, COUNT(*) FROM sources WHERE file_hash IN ({placeholders}) GROUP BY file_hash", chunk).fetchall())
            tagged.update(row[0] for row in conn.execute(f"SELECT DISTINCT file_hash FROM tags WHERE key = ? AND file_hash IN ({placeholders})", [tag_key, *chunk]))

        read_in_chunks(conn, hashes, read)
        return counts, tagged
