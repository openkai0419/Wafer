from wafer.plugin import BaseParserPlugin, ParserResult
from wafer.core.common.hashes import HASH_FAILED, full_hash

FULL_HASH_LENGTH = 64


class FullHashParser(BaseParserPlugin):
    NAME = "full_hash"
    DISPLAY_NAME = "Full Hash"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("file_hash",)
    BATCH_SIZE = 200
    MAX_WORKERS = 2
    MAX_TIMEOUT = 600.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        current = file_info[2] if len(file_info) > 2 else None
        if current and len(current) >= FULL_HASH_LENGTH:
            return ParserResult(source=path, status=True)
        digest = full_hash(path)
        if digest == HASH_FAILED:
            return ParserResult(source=path, status=False)
        return ParserResult(source=path, status=True, update_hash=digest)
