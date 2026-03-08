from __future__ import annotations

from pathlib import Path

from ...core.db.file_db import FileDB
from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from .write_command import WriteCommand


class DatabaseWriter:

    def __init__(self, db_path: str | Path):
        self._db = FileDB(db_path)
        self._ops: dict[str, callable] = {}
        self._build_ops()

    def _build_ops(self):
        self._ops = {
            'delete_sources': self._exec_delete_sources,
            'rename_paths': self._exec_rename_paths,
            'upsert_sources': self._exec_upsert_sources,
            'upsert_results': self._exec_upsert_results,
            'insert_pending': self._exec_insert_pending,
            'mark_dispatched': self._exec_mark_dispatched,
            'reset_stale': self._exec_reset_stale,
            'purge_orphans': self._exec_purge_orphans,
            'checkpoint': self._exec_checkpoint,
        }

    @property
    def db(self) -> FileDB:
        return self._db

    def start(self):
        self._db.start()

    def close(self):
        self._db.close()

    def initialize(self):
        self._db.initialize_database()

    @profiler.profile
    def execute(self, command: WriteCommand):
        handler = self._ops.get(command.operation)
        if handler is None:
            AppLogger.warning(f'[DatabaseWriter] Unknown operation: {command.operation}')
            return
        data = command.data or {}
        try:
            handler(data)
        except Exception as e:
            AppLogger.error(f'[DatabaseWriter] {command.operation} failed: {e}', exc=e)

    def _exec_delete_sources(self, data: dict):
        self._db.delete_sources_by_paths(data['paths'])
        self._db.try_checkpoint('PASSIVE')

    def _exec_rename_paths(self, data: dict):
        self._db.rename_paths(data['pairs'])
        self._db.try_checkpoint('PASSIVE')

    def _exec_upsert_sources(self, data: dict):
        self._db.upsert_basic_sources(data['source_entries'], data['image_entries'])
        self._db.try_checkpoint('PASSIVE')

    def _exec_upsert_results(self, data: dict):
        self._db.upsert_collection_results(
            data['source_updates'],
            data['image_entries'],
            data['meta_info_entries'],
            data['tag_entries'],
            data['collector_status'],
        )
        self._db.try_checkpoint('PASSIVE')

    def _exec_insert_pending(self, data: dict):
        self._db.insert_pending_collection(data['sources'], data['collectors'])

    def _exec_mark_dispatched(self, data: dict):
        self._db.mark_dispatched(data['sources'], data['collector'])

    def _exec_reset_stale(self, data: dict):
        self._db.reset_stale_dispatched(data.get('collectors'))

    def _exec_purge_orphans(self, _data: dict):
        self._db.purge_orphan_records()

    def _exec_checkpoint(self, data: dict):
        self._db.try_checkpoint(data.get('mode', 'PASSIVE'))
