import py_compile
import threading
from unittest.mock import MagicMock, patch

from wafer.app.indexer.main_indexer import IndexerProcess
from wafer.app.indexer.task import TaskPriority


def test_compile():
    py_compile.compile('wafer/app/indexer/main_indexer.py')


def test_compile_collector_receiver():
    py_compile.compile('wafer/app/indexer/collector_receiver.py')


def test_compile_scanner():
    py_compile.compile('wafer/app/indexer/scanner.py')


class TestIndexerProcessInit:

    @patch('wafer.app.indexer.main_indexer.Node')
    def test_accepts_stop_event(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        stop = threading.Event()
        proc = IndexerProcess('test', stop_event=stop)
        assert proc._stop_event is stop

    @patch('wafer.app.indexer.main_indexer.Node')
    def test_subscribes_to_db_delete(self, mock_node_cls):
        node = MagicMock()
        mock_node_cls.return_value = node
        IndexerProcess('test')
        topics = [call.args[0] for call in node.subscribe.call_args_list]
        assert 'db.delete' in topics


class TestOnDeleteRequested:

    @patch('wafer.app.indexer.main_indexer.Node')
    def test_without_scheduler_calls_delete_directly(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess('test')
        proc.scheduler = None
        proc.delete = MagicMock()
        proc._on_delete_requested()
        proc.delete.assert_called_once()

    @patch('wafer.app.indexer.main_indexer.Node')
    def test_with_scheduler_cancels_and_submits(self, mock_node_cls):
        mock_node_cls.return_value = MagicMock()
        proc = IndexerProcess('test')
        proc.scheduler = MagicMock()
        proc._on_delete_requested()
        proc.scheduler.cancel_all.assert_called_once()
        proc.scheduler.submit.assert_called_once()
        task = proc.scheduler.submit.call_args[0][0]
        assert task.priority == TaskPriority.SHUTDOWN
        assert task.name == 'db_delete'


class TestDelete:

    @patch('wafer.app.indexer.main_indexer.remove_orphan_databases')
    @patch('wafer.app.indexer.main_indexer.delete_database_files')
    @patch('wafer.app.indexer.main_indexer.Node')
    def test_delete_sends_db_deleted_and_sets_stop_event(
        self, mock_node_cls, mock_del_files, mock_orphan
    ):
        node = MagicMock()
        mock_node_cls.return_value = node
        stop = threading.Event()
        proc = IndexerProcess('test', stop_event=stop)
        proc.setting_db = MagicMock()
        proc.setting_db.db_name = 'test_setting.db'
        proc.delete()
        node.send.assert_called_with('db.deleted', 'test', dst='viewer')
        assert stop.is_set()

    @patch('wafer.app.indexer.main_indexer.remove_orphan_databases')
    @patch('wafer.app.indexer.main_indexer.delete_database_files')
    @patch('wafer.app.indexer.main_indexer.Node')
    def test_delete_without_stop_event(self, mock_node_cls, mock_del_files, mock_orphan):
        node = MagicMock()
        mock_node_cls.return_value = node
        proc = IndexerProcess('test')
        proc.setting_db = MagicMock()
        proc.setting_db.db_name = 'test_setting.db'
        proc.delete()
        node.send.assert_called_with('db.deleted', 'test', dst='viewer')

    @patch('wafer.app.indexer.main_indexer.remove_orphan_databases')
    @patch('wafer.app.indexer.main_indexer.delete_database_files')
    @patch('wafer.app.indexer.main_indexer.Node')
    def test_delete_with_setting_db_none(self, mock_node_cls, mock_del_files, mock_orphan):
        node = MagicMock()
        mock_node_cls.return_value = node
        proc = IndexerProcess('test')
        proc.setting_db = None
        proc.delete()
        mock_del_files.assert_called_once()
        node.send.assert_called_with('db.deleted', 'test', dst='viewer')
