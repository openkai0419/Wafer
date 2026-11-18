from __future__ import annotations

import zipfile
from collections.abc import Callable
from contextlib import closing
from pathlib import PurePosixPath
from typing import BinaryIO

from PIL import Image

from wafer.plugin import BaseSingletonCollector, CollectorResult
from wafer.core.logs import AppLogger
from wafer.core.common.virtual_paths import build_virtual_path

from .archive import ZipEntry, ZipMemberRecord, get_archive_index, list_entries, open_member_records
from .cache import zip_cache


class ZipCollectorPlugin(BaseSingletonCollector):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    PRIORITY = 80
    DEFAULT_ENABLED = True
    BATCH_SIZE = 1
    MAX_WORKERS = 1
    MAX_TIMEOUT = 600.0

    def shutdown(self):
        zip_cache.stop_idle_sweep()

    def process(self, path: str, file_info: tuple) -> list[CollectorResult]:
        try:
            entries = list_entries(path)
        except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as e:
            AppLogger.warning(f"[zip] Failed to enumerate archive: {path}", exc=e)
            return [CollectorResult(source=path, status=False)]

        readable = [entry for entry in entries if not (entry.record and entry.record.encrypted)]
        if skipped := len(entries) - len(readable):
            AppLogger.warning(f"[zip] Skipped {skipped} password-protected entries (extract the archive to view them): {path}")
        entries = readable

        results = [CollectorResult(source=path, status=True, meta_info={"entries": len(entries)})]
        image_extensions = Image.registered_extensions()
        with open_member_records(path, get_archive_index(path).metadata_encoding) as open_member:
            for entry in entries:
                logical_path = build_virtual_path(path, entry.member)
                is_image = PurePosixPath(entry.name).suffix.lower() in image_extensions
                aspect = self._probe_aspect(open_member, entry, logical_path) if is_image else 1.0
                results.append(
                    CollectorResult(
                        source=path,
                        path=logical_path,
                        name=entry.name,
                        status=True,
                        aspect=aspect,
                    )
                )
        return results

    def _probe_aspect(self, open_member: Callable[[ZipMemberRecord], BinaryIO], entry: ZipEntry, logical_path: str) -> float:
        try:
            with closing(open_member(entry.record)) as src, Image.open(src) as image:
                width, height = image.size
        except Exception as e:
            AppLogger.warning(f"[zip] Aspect probe failed: {logical_path} ({e})", exc=e)
            return 1.0
        return max(width / height, 0.001) if height > 0 else 1.0
