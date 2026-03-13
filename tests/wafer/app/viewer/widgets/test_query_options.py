import py_compile
from unittest.mock import patch, MagicMock

import pytest
from PySide6 import QtWidgets


def test_compile():
    py_compile.compile('wafer/app/viewer/widgets/query_options.py')


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture()
def search_bar(qapp):
    from wafer.app.viewer.widgets.query_options import SearchOptionsBar
    bar = SearchOptionsBar()
    yield bar


class TestRunFolderWorker:

    def test_first_call_with_empty_paths_should_run(self, search_bar):
        with patch.object(search_bar, '_dispatcher') as mock_disp:
            search_bar.run_folder_worker('dummy.db', [])
            assert mock_disp.post.call_count == 1

    def test_duplicate_call_skipped(self, search_bar):
        with patch.object(search_bar, '_dispatcher') as mock_disp:
            search_bar.run_folder_worker('dummy.db', ['/a'])
            search_bar.run_folder_worker('dummy.db', ['/a'])
            assert mock_disp.post.call_count == 1

    def test_different_paths_not_skipped(self, search_bar):
        with patch.object(search_bar, '_dispatcher') as mock_disp:
            search_bar.run_folder_worker('dummy.db', ['/a'])
            search_bar.run_folder_worker('dummy.db', ['/b'])
            assert mock_disp.post.call_count == 2
