from __future__ import annotations

from wafer.plugin import PluginConfig

SWEEP_INTERVAL_SECONDS: float = 5 * 60
ENTRY_IDLE_SECONDS: float = 10 * 60
METADATA_ENCODING: str | None = "cp932"
CACHE_LIMIT_DEFAULT_GB = 5
GIBIBYTE = 1024 * 1024 * 1024

zip_config = PluginConfig("zip", {"cache_limit_gb": CACHE_LIMIT_DEFAULT_GB})
