from wafer.plugin import BaseParserPlugin, ParserResult
from wafer.core.common.hashes import FULL_HASH_LENGTH, read_full_hash
from wafer.core.logs import AppLogger


class FullHashParser(BaseParserPlugin):
    NAME = "full_hash"
    DISPLAY_NAME = "Full Hash"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("file_hash",)
    BATCH_SIZE = 200
    MAX_WORKERS = 2
    MAX_TIMEOUT = 600.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult | None:
        current = file_info[2] if len(file_info) > 2 else None
        if current and len(current) >= FULL_HASH_LENGTH:
            return ParserResult(source=path, status=True)
        try:
            digest = read_full_hash(path)
        except PermissionError as e:
            AppLogger.warning(f"[full_hash] File is in use; collected again later: {path}", exc=e)
            return self.retry_later(path, pause_after=5)
        except (OSError, ValueError) as e:
            AppLogger.warning(f"[full_hash] Cannot read the file: {path}", exc=e)
            return ParserResult(source=path, status=False)
        return ParserResult(source=path, status=True, update_hash=digest)
