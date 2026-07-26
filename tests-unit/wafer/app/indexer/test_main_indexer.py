import py_compile
import threading
from unittest.mock import MagicMock, patch

from wafer.app.indexer.main_indexer import IndexerProcess
from wafer.app.indexer.runtime.task import TaskPriority


def test_compile():
    py_compile.compile("wafer/app/indexer/main_indexer.py")


def test_compile_collector_receiver():
    py_compile.compile("wafer/app/indexer/receivers/collector_receiver.py")


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
    def test_subscribes_to_recollect(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        IndexerProcess("test")
        topics = [call.args[0] for call in node.subscribe.call_args_list]
        assert "recollect" in topics

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_subscribes_to_kv_convert_scope(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        IndexerProcess("test")
        topics = [call.args[0] for call in node.subscribe.call_args_list]
        assert "kv.convert_scope" in topics

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_subscribes_to_keyfilter_reload(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        IndexerProcess("test")
        topics = [call.args[0] for call in node.subscribe.call_args_list]
        assert "keyfilter.reload" in topics


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

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_request_idle_rescan_delegates_to_watcher_refresh(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.folder_watcher = MagicMock()
        proc._request_idle_rescan()
        proc.folder_watcher.refresh_watch.assert_called_once()

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_request_idle_rescan_without_watcher(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.folder_watcher = None
        proc._request_idle_rescan()


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

    @patch("wafer.app.indexer.main_indexer.parser_resolver.batch_timeout", return_value=900.0)
    @patch("wafer.app.indexer.main_indexer.collector_resolver.batch_timeout", return_value=1200.0)
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_idle_base_delay_uses_child_batch_timeout(self, mock_node_cls, _collector_timeout, _parser_timeout):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._register_periodic_tasks(["florence"], ["novelai"])
        tasks = {call.args[0].name: call.args[0] for call in proc.scheduler.add_periodic_task.call_args_list}
        proc.scheduler.set_idle_base_delay.assert_called_once_with(1260.0)
        assert tasks["retry_stale_dispatched"].idle_delay == 60.0
        assert tasks["backfill_pending"].idle_delay == 120.0
        assert tasks["idle_rescan"].idle_delay == 300.0
        assert tasks["idle_progress_reset"].idle_delay == 30.0
        assert tasks["cleanup_optimize"].idle_delay == 1800.0

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_idle_base_delay_uses_grace_without_children(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.scheduler = MagicMock()
        proc._register_periodic_tasks()
        proc.scheduler.set_idle_base_delay.assert_called_once_with(60.0)


class TestOnRecollect:
    def _proc(self):
        proc = IndexerProcess("test")
        proc.writer = MagicMock()
        proc.scheduler = MagicMock()
        proc.scanner = MagicMock()
        proc._progress = MagicMock()
        return proc

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_invalid_payload_returns_true(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        msg = MagicMock()
        msg.payload = "not_a_dict"
        assert proc._on_recollect(msg) is True

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_returns_true_without_writer(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        proc.writer = None
        proc.scheduler = MagicMock()
        msg = MagicMock()
        msg.payload = {"mode": "reset"}
        assert proc._on_recollect(msg) is True

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_reset_with_sources(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "reset", "collector": "exif", "sources": ["/a"], "prefixes": None}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        assert task.name == "recollect_reset"
        assert task.priority == TaskPriority.USER_REQUEST
        task.run()
        proc.writer.recollect.assert_called_once_with("exif", ["/a"], None)
        task.on_complete()
        proc._progress.send_event.assert_called_with("update")

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_reset_all(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "reset"}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        task.run()
        proc.writer.recollect.assert_called_once_with(None, None, None)

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_forget_sources(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "forget", "sources": ["/a", "/b"]}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        assert task.name == "recollect_forget"
        task.run()
        proc.writer.delete_sources.assert_called_once_with(["/a", "/b"])
        task.on_complete()
        proc.scanner.request_update.assert_called_once_with(["/a", "/b"])

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_forget_prefixes(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "forget", "prefixes": ["/dir"]}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        task.run()
        proc.writer.delete_source_trees.assert_called_once_with(["/dir"])
        task.on_complete()
        proc.scanner.request_scan.assert_called_once_with(["/dir"])

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_forget_all(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        proc.rescan = MagicMock()
        msg = MagicMock()
        msg.payload = {"mode": "forget", "all": True}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        task.run()
        proc.writer.delete_all_sources.assert_called_once_with()
        task.on_complete()
        proc.rescan.assert_called_once_with()

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_purge_collector(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "purge", "collector": "color", "delete": True, "re_collect": True}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        assert task.name == "recollect_purge"
        task.run()
        proc.writer.delete_collector.assert_called_once_with("color", re_collect=True)

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_purge_keys_only(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "purge", "collector": "exif", "keys": ["exif.w"], "delete": False, "re_collect": True}
        proc._on_recollect(msg)
        task = proc.scheduler.submit.call_args[0][0]
        task.run()
        proc.writer.delete_keys.assert_called_once_with(["exif.w"])
        proc.writer.recollect.assert_called_once_with("exif")
        proc.writer.delete_collector.assert_not_called()

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_purge_noop(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = self._proc()
        msg = MagicMock()
        msg.payload = {"mode": "purge", "collector": "", "keys": []}
        proc._on_recollect(msg)
        proc.scheduler.submit.assert_not_called()


class TestOnKvConvertScope:
    @patch("wafer.app.indexer.main_indexer.Node")
    def test_invalid_payload_returns_true(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess("test")
        msg = MagicMock()
        msg.payload = "bad"
        assert proc._on_kv_convert_scope(msg) is True

    @patch("wafer.app.indexer.main_indexer.Node")
    def test_submits_convert_task(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        proc = IndexerProcess("test")
        proc.writer = MagicMock()
        proc.writer.convert_key_scope.return_value = {
            "key": "mark.1",
            "from_scope": "meta_info",
            "to_scope": "tag",
            "upserted": 2,
            "source_deleted": 1,
            "paths": ["/a.png"],
            "targets": {"/a.png": "h1"},
        }
        proc.scheduler = MagicMock()
        msg = MagicMock()
        msg.payload = {"key": "mark.1", "to_scope": "tag", "request_id": "rid"}
        assert proc._on_kv_convert_scope(msg) is True
        task = proc.scheduler.submit.call_args[0][0]
        assert task.name == "convert_key_scope"
        assert task.priority == TaskPriority.USER_REQUEST
        task.run()
        proc.writer.convert_key_scope.assert_called_once_with("mark.1", "tag")
        task.on_complete()
        node.send.assert_called_with(
            "tags.updated",
            {
                "paths": ["/a.png"],
                "scope": "*",
                "applied": {},
                "deleted": {},
                "targets": {"/a.png": "h1"},
                "request_id": "rid",
                "db": "test",
                "key": "mark.1",
                "from_scope": "meta_info",
                "to_scope": "tag",
                "upserted": 2,
                "source_deleted": 1,
            },
            dst="viewer",
        )
