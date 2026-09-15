from wafer.plugin import BaseParserPlugin, ParserResult
from wafer.core.common.hashes import HASH_FAILED

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
        file_hash = file_info[2] if len(file_info) > 2 else None
        if not file_hash or file_hash == HASH_FAILED:
            return ParserResult(source=path, status=False)
        tag_key = f"{self.NAME}.{TAG}"
        rows = self.query_db(
            "SELECT (SELECT COUNT(*) FROM sources WHERE file_hash = ?), (SELECT COUNT(*) FROM tags WHERE file_hash = ? AND key = ?)",
            (file_hash, file_hash, tag_key),
        )
        source_count, tagged = rows[0] if rows else (0, 0)
        if source_count > 1:
            if tagged:
                return ParserResult(source=path, status=True)
            return ParserResult(source=path, status=True, tags={TAG: "1"})
        if tagged:
            return ParserResult(source=path, status=True, delete_tag_keys=[tag_key])
        return ParserResult(source=path, status=True)
