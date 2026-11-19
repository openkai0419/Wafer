from __future__ import annotations

from ....plugin.collector.handler import collector_resolver
from .plugin_dispatcher import PluginDispatcher


class CollectorDispatcher(PluginDispatcher):
    KIND = "collector"
    BATCH_TOPIC = "collect.batch"
    resolver = collector_resolver
