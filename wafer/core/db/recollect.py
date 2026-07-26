from __future__ import annotations

from collections.abc import Iterable

from .dispatch import DB_SCOPE_ALL, send_to_db_scope
from ...utils.logs import AppLogger


class Recollect:
    """Unified re-collection API. Routes requests to the indexer via the
    ``recollect`` IPC topic, fanning out over ``db_scope`` (current DB name,
    a list of names, or ``"*"`` for all databases).

    Modes:
      - ``reset``: mark collection_status as pending so collectors re-run
        (optionally scoped by ``collector`` and/or ``sources``).
      - ``forget``: delete sources (files / folder subtrees / whole DB) and
        re-scan them, re-collecting from scratch.
      - ``purge``: delete a collector's data and/or specific keys, optionally
        re-collecting afterwards (used when disabling/uninstalling collectors
        or editing key filters).
    """

    @staticmethod
    def _node():
        from ..commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node is None:
            AppLogger.warning("[Recollect] No IPC node available; request skipped")
        return node

    @staticmethod
    def _send(payload: dict, db_scope) -> int:
        node = Recollect._node()
        if node is None:
            return 0
        sent = send_to_db_scope(node, "recollect", payload, db_scope=db_scope)
        AppLogger.info(f"[Recollect] {payload.get('mode')} sent to {sent} db(s) (scope={db_scope})")
        return sent

    @staticmethod
    def reset(*, db_scope=DB_SCOPE_ALL, collector: str | None = None, sources: Iterable[str] | None = None, prefixes: Iterable[str] | None = None) -> int:
        payload = {
            "mode": "reset",
            "collector": collector or None,
            "sources": list(sources) if sources else None,
            "prefixes": list(prefixes) if prefixes else None,
        }
        return Recollect._send(payload, db_scope)

    @staticmethod
    def forget(*, db_scope=DB_SCOPE_ALL, sources: Iterable[str] | None = None, prefixes: Iterable[str] | None = None, all: bool = False) -> int:
        payload = {
            "mode": "forget",
            "sources": list(sources) if sources else None,
            "prefixes": list(prefixes) if prefixes else None,
            "all": bool(all),
        }
        return Recollect._send(payload, db_scope)

    @staticmethod
    def purge(*, db_scope=DB_SCOPE_ALL, collector: str | None = None, keys: Iterable[str] | None = None, delete: bool = True, re_collect: bool = False) -> int:
        payload = {
            "mode": "purge",
            "collector": collector or "",
            "keys": list(keys) if keys else [],
            "delete": bool(delete),
            "re_collect": bool(re_collect),
        }
        return Recollect._send(payload, db_scope)
