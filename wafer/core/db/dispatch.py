from __future__ import annotations

from collections.abc import Iterable

from ...utils.logs import AppLogger
from ...utils.paths import list_data_db_names


DB_SCOPE_ALL = "*"


def resolve_db_scope(db_scope: str | Iterable[str] | None = DB_SCOPE_ALL) -> list[str]:
    if db_scope is None or db_scope == DB_SCOPE_ALL:
        return list_data_db_names()
    if isinstance(db_scope, str):
        name = db_scope.strip()
        return [name] if name else []
    return [str(name).strip() for name in db_scope if str(name).strip()]


def send_to_db_scope(node, topic: str, payload: dict, *, db_scope: str | Iterable[str] | None = DB_SCOPE_ALL, dst: str = "indexer", reliable: bool = True) -> int:
    db_names = resolve_db_scope(db_scope)
    sent = 0
    for db_name in db_names:
        try:
            if reliable:
                node.send_reliable(topic, dict(payload), dst=dst, db=db_name)
            else:
                node.send(topic, dict(payload), dst=dst, db=db_name)
            sent += 1
        except Exception as exc:
            AppLogger.warning(f"[DBDispatch] send failed topic={topic} db={db_name}: {exc}", exc=exc)
    return sent