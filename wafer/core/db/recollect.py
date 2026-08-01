from __future__ import annotations

from collections.abc import Iterable

from .dispatch import DB_SCOPE_ALL, send_to_db_scope
from ...utils.logs import AppLogger


class Recollect:
    """Unified re-collection API. Routes requests to the indexer via the
    ``recollect`` IPC topic, fanning out over ``db_scope`` (current DB name,
    a list of names, or ``"*"`` for all databases).

    Modes:
      - ``reset``: re-collect a target. Optionally scoped by ``collector``,
        ``sources`` and/or ``prefixes``. ``keys`` deletes specific keys first,
        ``delete=True`` deletes the target's collected data first, and
        ``re_collect`` (default ``True``) marks it pending afterwards; set
        ``re_collect=False`` to only delete (e.g. disabling/uninstalling a
        collector or editing key filters). ``delete`` requires a ``collector``
        or a ``sources``/``prefixes`` scope; a whole-DB wipe must use ``forget``.
      - ``forget``: delete sources (files / folder subtrees / whole DB) and
        re-scan them, re-collecting from scratch.
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
    def reset(
        *,
        db_scope=DB_SCOPE_ALL,
        collector: str | None = None,
        sources: Iterable[str] | None = None,
        prefixes: Iterable[str] | None = None,
        keys: Iterable[str] | None = None,
        delete: bool = False,
        re_collect: bool = True,
    ) -> int:
        payload = {
            "mode": "reset",
            "collector": collector or None,
            "sources": list(sources) if sources else None,
            "prefixes": list(prefixes) if prefixes else None,
            "keys": list(keys) if keys else None,
            "delete": bool(delete),
            "re_collect": bool(re_collect),
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
