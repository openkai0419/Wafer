from __future__ import annotations

import zipfile

from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.utils.logs import AppLogger
from wafer.utils.virtual_paths import build_virtual_path

from .archive import list_entries
from .cache import zip_cache

_ASPECT_PROBE_SIZE = 512


class ZipCollectorPlugin(BaseCollectorPlugin):
    NAME = "zip"
    EXTENSIONS = (".zip",)
    IS_OWNER = True
    PRIORITY = 80
    DEFAULT_ENABLED = True
    BATCH_SIZE = 1

    def process(self, path: str, file_info: tuple) -> list[CollectorResult]:
        try:
            entries = list_entries(path)
        except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as e:
            AppLogger.warning(f"[zip] Failed to enumerate archive: {path}", exc=e)
            return [CollectorResult(source=path, status=False)]

        results = [CollectorResult(source=path, status=True, meta_info={"entries": len(entries)})]
        for entry in entries:
            logical_path = build_virtual_path(path, entry.member)
            aspect = self._probe_aspect(logical_path)
            results.append(
                CollectorResult(
                    source=path,
                    path=logical_path,
                    name=entry.name,
                    size=entry.size,
                    modified=entry.modified,
                    status=True,
                    aspect=aspect,
                )
            )
        return results

    def _probe_aspect(self, logical_path: str) -> float:
        try:
            real_path = zip_cache.materialize(logical_path, purpose="aspect")
            image = image_loader_resolver.load_pil(real_path, size=_ASPECT_PROBE_SIZE)
            if image is None or image.height <= 0:
                return 1.0
            return max(image.width / image.height, 0.001)
        except Exception as e:
            AppLogger.warning(f"[zip] Aspect probe failed: {logical_path} ({e})", exc=e)
            return 1.0
