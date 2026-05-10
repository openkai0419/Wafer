from __future__ import annotations

from dataclasses import dataclass


SCOPE_TAG = "tag"
SCOPE_META_INFO = "meta_info"
SCOPE_ALL = "*"

DATA_SCOPES = (SCOPE_TAG, SCOPE_META_INFO)


@dataclass(frozen=True, slots=True)
class KeyValueScopeSpec:
    scope: str
    table: str
    target_column: str
    key_column: str
    path_column: str
    from_clause: str


@dataclass(frozen=True, slots=True)
class KeyValueConversionSpec:
    from_scope: str
    to_scope: str
    affected_rows_sql: str
    insert_sql: str
    delete_sql: str


_SPECS = {
    SCOPE_TAG: KeyValueScopeSpec(
        scope=SCOPE_TAG,
        table="tags",
        target_column="file_hash",
        key_column="t.key",
        path_column="i.path",
        from_clause="tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source",
    ),
    SCOPE_META_INFO: KeyValueScopeSpec(
        scope=SCOPE_META_INFO,
        table="meta_info",
        target_column="path",
        key_column="mi.key",
        path_column="mi.path",
        from_clause="meta_info AS mi",
    ),
}

_KEY_PREFIX_LOOKUP_SQL = {
    scope: (
        f"SELECT {spec.path_column} AS path, {spec.key_column} AS key FROM {spec.from_clause} WHERE {spec.key_column} LIKE ?",
        spec.path_column,
    )
    for scope, spec in _SPECS.items()
}

_CONVERSION_SPECS = {
    SCOPE_TAG: KeyValueConversionSpec(
        from_scope=SCOPE_META_INFO,
        to_scope=SCOPE_TAG,
        affected_rows_sql=("SELECT mi.path AS path, s.file_hash AS target_id FROM meta_info AS mi JOIN files AS i ON i.path = mi.path LEFT JOIN sources AS s ON s.source = i.source WHERE mi.key = ?"),
        insert_sql=(
            "INSERT INTO tags (file_hash, key, value, value_num, locked) "
            "SELECT s.file_hash, mi.key, mi.value, mi.value_num, mi.locked "
            "FROM meta_info AS mi "
            "JOIN files AS i ON i.path = mi.path "
            "JOIN sources AS s ON s.source = i.source "
            "WHERE mi.key = ? AND s.file_hash IS NOT NULL "
            "ON CONFLICT(file_hash, key) DO UPDATE SET "
            "locked = CASE WHEN tags.locked != 0 OR excluded.locked != 0 THEN 1 ELSE 0 END"
        ),
        delete_sql="DELETE FROM meta_info WHERE key = ? AND locked = 0",
    ),
    SCOPE_META_INFO: KeyValueConversionSpec(
        from_scope=SCOPE_TAG,
        to_scope=SCOPE_META_INFO,
        affected_rows_sql=("SELECT i.path AS path, s.file_hash AS target_id FROM tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source WHERE t.key = ?"),
        insert_sql=(
            "INSERT INTO meta_info (path, key, value, value_num, locked) "
            "SELECT i.path, t.key, t.value, t.value_num, t.locked "
            "FROM tags AS t "
            "JOIN sources AS s ON s.file_hash = t.file_hash "
            "JOIN files AS i ON i.source = s.source "
            "WHERE t.key = ? "
            "ON CONFLICT(path, key) DO UPDATE SET "
            "locked = CASE WHEN meta_info.locked != 0 OR excluded.locked != 0 THEN 1 ELSE 0 END"
        ),
        delete_sql="DELETE FROM tags WHERE key = ? AND locked = 0",
    ),
}


def normalize_data_scope(scope: str | None, *, allow_all: bool = False) -> str:
    scope = str(scope or SCOPE_TAG)
    if scope in DATA_SCOPES or (allow_all and scope == SCOPE_ALL):
        return scope
    allowed = ", ".join((*DATA_SCOPES, SCOPE_ALL) if allow_all else DATA_SCOPES)
    raise ValueError(f"Unsupported key-value scope: {scope}; expected one of {allowed}")


def iter_data_scopes(scope: str | None) -> tuple[str, ...]:
    scope = normalize_data_scope(scope, allow_all=True)
    return DATA_SCOPES if scope == SCOPE_ALL else (scope,)


def other_data_scope(scope: str) -> str:
    scope = normalize_data_scope(scope)
    return SCOPE_META_INFO if scope == SCOPE_TAG else SCOPE_TAG


def scope_spec(scope: str) -> KeyValueScopeSpec:
    spec = _SPECS.get(scope)
    if spec is not None:
        return spec
    return _SPECS[normalize_data_scope(scope)]


def key_prefix_lookup_sql(scope: str) -> tuple[str, str]:
    sql = _KEY_PREFIX_LOOKUP_SQL.get(scope)
    if sql is not None:
        return sql
    return _KEY_PREFIX_LOOKUP_SQL[normalize_data_scope(scope)]


def conversion_spec(to_scope: str) -> KeyValueConversionSpec:
    spec = _CONVERSION_SPECS.get(to_scope)
    if spec is not None:
        return spec
    return _CONVERSION_SPECS[normalize_data_scope(to_scope)]
