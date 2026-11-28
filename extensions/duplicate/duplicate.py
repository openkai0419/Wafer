import ntpath
from collections import Counter

from wafer.plugin import BaseParserPlugin, ParserResult
from wafer.core.common.hashes import HASH_FAILED
from wafer.core.db.path_values import read_in_chunks

TAG = "has_duplicate"
SAME_NAME = "has_same_name"


def file_name(source: str) -> str:
    return ntpath.basename(source).casefold()


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
        valid_paths = [path for path in paths if hashes[path]]
        members, tagged, named = self.read_db(lambda conn: self.read_hash_state(conn, list(dict.fromkeys(hashes[p] for p in valid_paths)), valid_paths))
        name_counts = {file_hash: Counter(map(file_name, sources)) for file_hash, sources in members.items()}
        return [self.result_for(path, hashes[path], members, tagged, named, name_counts) for path in paths]

    def result_for(self, path, file_hash, members, tagged, named, name_counts) -> ParserResult:
        if not file_hash:
            return ParserResult(source=path, status=False)
        result = ParserResult(source=path, status=True)
        shared = len(members.get(file_hash, ())) > 1
        if shared and file_hash not in tagged:
            result.tags = {TAG: "1"}
        elif not shared and file_hash in tagged:
            result.delete_tag_keys = [f"{self.NAME}.{TAG}"]
        same_name = name_counts.get(file_hash, Counter())[file_name(path)] > 1
        if same_name and path not in named:
            result.meta_info = {SAME_NAME: "1"}
        elif not same_name and path in named:
            result.delete_meta_keys = [f"{self.NAME}.{SAME_NAME}"]
        return result

    @staticmethod
    def valid_hash(file_info: tuple) -> str | None:
        file_hash = file_info[2] if len(file_info) > 2 else None
        return None if not file_hash or file_hash == HASH_FAILED else file_hash

    def read_hash_state(self, conn, hashes: list[str], paths: list[str]) -> tuple[dict[str, list[str]], set[str], set[str]]:
        members: dict[str, list[str]] = {}
        tagged: set[str] = set()
        named: set[str] = set()
        tag_key = f"{self.NAME}.{TAG}"
        meta_key = f"{self.NAME}.{SAME_NAME}"

        def read_hashes(conn, chunk, placeholders):
            for file_hash, source in conn.execute(f"SELECT file_hash, source FROM sources WHERE file_hash IN ({placeholders})", chunk):
                members.setdefault(file_hash, []).append(source)
            tagged.update(row[0] for row in conn.execute(f"SELECT DISTINCT file_hash FROM tags WHERE key = ? AND file_hash IN ({placeholders})", [tag_key, *chunk]))

        def read_paths(conn, chunk, placeholders):
            named.update(row[0] for row in conn.execute(f"SELECT path FROM meta_info WHERE key = ? AND path IN ({placeholders})", [meta_key, *chunk]))

        read_in_chunks(conn, hashes, read_hashes)
        read_in_chunks(conn, paths, read_paths)
        return members, tagged, named
