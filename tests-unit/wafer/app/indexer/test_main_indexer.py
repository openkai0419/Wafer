import py_compile
import threading
from unittest.mock import MagicMock, patch

from wafer.app.indexer.main_indexer import IndexerProcess
from wafer.app.indexer.task import TaskPriority


def test_compile():
    py_compile.compile("wafer/app/indexer/main_indexer.py")


def test_compile_collector_receiver():
    py_compile.compile("wafer/app/indexer/collector_receiver.py")


def test_compile_scanner():
    py_compile.compile("wafer/app/indexer/scanner.py")


class TestIndexerProcessInit:
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_accepts_stop_event(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        stop = threading.Event()
        proc = IndexerProcess("test", stop_event=stop)
        assert proc._stop_event is stop

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_subscribes_to_db_delete(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        IndexerProcess("test")
        topics = [call.args[0] for call in node.subscribe.call_args_list]
        assert "db.delete" in topics

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_subscribes_to_purge_keys(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        IndexerProcess("test")
        topics = [call.args[0] for call in node.subscribe.call_args_list]
        assert "purge.keys" in topics


class TestOnDeleteRequested:
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_without_scheduler_calls_delete_directly(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = None
        proc.delete = MagicMock()
        proc._on_delete_requested()
        proc.delete.assert_called_once()

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_with_scheduler_cancels_and_submits(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._on_delete_requested()
        proc.scheduler.cancel_all.assert_called_once()
        proc.scheduler.submit.assert_called_once()
        task = proc.scheduler.submit.call_args[0][0]
        assert task.priority == TaskPriority.SHUTDOWN
        assert task.name == "db_delete"


class TestDelete:
    @patch("wafer.app.indexer.main_indexer.remove_orphan_databases")
    @patch("wafer.app.indexer.main_indexer.delete_database_files")
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_delete_sends_db_deleted_and_sets_stop_event(self, mock_node_cls, mock_del_files, mock_orphan):
        node = MagicMock()
        mock_node_cls.return_value = node
        stop = threading.Event()
        proc = IndexerProcess("test", stop_event=stop)
        proc.setting_db = MagicMock()
        proc.setting_db.db_name = "test_setting.db"
        proc.delete()
        node.send.assert_called_with("db.deleted", "test", dst="viewer")
        assert stop.is_set()

    @patch("wafer.app.indexer.main_indexer.remove_orphan_databases")
    @patch("wafer.app.indexer.main_indexer.delete_database_files")
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_delete_without_stop_event(self, mock_node_cls, mock_del_files, mock_orphan):
        node = MagicMock()
        mock_node_cls.return_value = node
        proc = IndexerProcess("test")
        proc.setting_db = MagicMock()
        proc.setting_db.db_name = "test_setting.db"
        proc.delete()
        node.send.assert_called_with("db.deleted", "test", dst="viewer")

    @patch("wafer.app.indexer.main_indexer.remove_orphan_databases")
    @patch("wafer.app.indexer.main_indexer.delete_database_files")
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_delete_with_setting_db_none(self, mock_node_cls, mock_del_files, mock_orphan):
        node = MagicMock()
        mock_node_cls.return_value = node
        proc = IndexerProcess("test")
        proc.setting_db = None
        proc.delete()
        mock_del_files.assert_called_once()
        node.send.assert_called_with("db.deleted", "test", dst="viewer")


class TestPeriodicBackfill:
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_register_periodic_tasks_includes_backfill(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._register_periodic_tasks()
        names = [call.args[0].name for call in proc.scheduler.add_periodic_task.call_args_list]
        assert "backfill_pending" in names

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_request_backfill_delegates_to_scanner(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scanner = MagicMock()
        proc._request_backfill()
        proc.scanner.backfill_pending.assert_called_once()

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_request_backfill_without_scanner(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scanner = None
        proc._request_backfill()


class TestIdleProgressReset:
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_register_includes_idle_progress_reset(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._register_periodic_tasks()
        names = [call.args[0].name for call in proc.scheduler.add_periodic_task.call_args_list]
        assert "idle_progress_reset" in names

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_idle_progress_reset_calls_reset_when_active(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._progress = MagicMock()
        proc._progress.maximum = 100
        proc._register_periodic_tasks()
        tasks = {call.args[0].name: call.args[0] for call in proc.scheduler.add_periodic_task.call_args_list}
        task = tasks["idle_progress_reset"].create_task()
        task.run()
        proc._progress.reset.assert_called_once()

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_idle_progress_reset_skips_when_already_zero(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._progress = MagicMock()
        proc._progress.maximum = 0
        proc._register_periodic_tasks()
        tasks = {call.args[0].name: call.args[0] for call in proc.scheduler.add_periodic_task.call_args_list}
        task = tasks["idle_progress_reset"].create_task()
        task.run()
        proc._progress.reset.assert_not_called()


class TestPeriodicTaskConfig:
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_once_per_idle_flags(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._register_periodic_tasks()
        tasks = {call.args[0].name: call.args[0] for call in proc.scheduler.add_periodic_task.call_args_list}
        assert tasks["truncate_checkpoint"].once_per_idle is True
        assert tasks["cleanup_optimize"].once_per_idle is True
        assert tasks["idle_progress_reset"].once_per_idle is True
        assert tasks["retry_stale_dispatched"].once_per_idle is False
        assert tasks["backfill_pending"].once_per_idle is False
        assert tasks["idle_rescan"].once_per_idle is False

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_idle_rescan_is_retry_priority(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._register_periodic_tasks()
        tasks = {call.args[0].name: call.args[0] for call in proc.scheduler.add_periodic_task.call_args_list}
        task = tasks["idle_rescan"].create_task()
        assert task.priority == TaskPriority.RETRY
