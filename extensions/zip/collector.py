from __future__ import annotations

import zipfile

from wafer.plugin import BaseSingletonCollector, CollectorResult
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.utils.logs import AppLogger
from wafer.utils.virtual_paths import build_virtual_path

from .archive import ZipEntry, list_entries
from .cache import zip_cache

_ASPECT_PROBE_SIZE = 512


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

        results = [CollectorResult(source=path, status=True, meta_info={"entries": len(entries)})]
        for entry in entries:
            logical_path = build_virtual_path(path, entry.member)
            aspect = self._probe_aspect(path, entry, logical_path)
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

    def _probe_aspect(self, source: str, entry: ZipEntry, logical_path: str) -> float:
        try:
            if entry.record:
                real_path = zip_cache.materialize_member(source, entry.record, purpose="aspect", name=entry.name)
            else:
                real_path = zip_cache.materialize(logical_path, purpose="aspect")
            image = image_loader_resolver.load_pil(real_path, size=_ASPECT_PROBE_SIZE)
            if image is None or image.height <= 0:
                return 1.0
            return max(image.width / image.height, 0.001)
        except Exception as e:
            AppLogger.warning(f"[zip] Aspect probe failed: {logical_path} ({e})", exc=e)
            return 1.0
