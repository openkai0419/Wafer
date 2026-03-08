import py_compile

from unittest.mock import MagicMock

import pytest


def test_compile():
    py_compile.compile('wafer/app/viewer/widgets/dev_log_panel.py')


@pytest.fixture
def panel(qtbot):
    from wafer.app.viewer.widgets.dev_log_panel import DevLogPanel
    p = DevLogPanel()
    qtbot.addWidget(p)
    return p


class TestDevLogPanel:
    def test_append_log_adds_entry(self, panel):
        panel.append_log('info', 'test message', src='viewer-123')
        assert len(panel._entries) == 1
        assert panel._entries[0]['text'] == 'test message'
        assert panel._entries[0]['level'] == 'info'
        assert panel._entries[0]['src'] == 'viewer-123'

    def test_all_tab_receives_entries(self, panel):
        panel.append_log('info', 'hello', src='viewer-1')
        text = panel._all_tab.toPlainText()
        assert 'hello' in text

    def test_src_tab_created(self, panel):
        panel.append_log('info', 'from viewer', src='viewer-100')
        panel.append_log('info', 'from indexer', src='indexer-200')
        assert 'viewer-100' in panel._src_tabs
        assert 'indexer-200' in panel._src_tabs
        assert panel._tab_widget.count() == 3  # All + 2 src tabs

    def test_src_tab_isolation(self, panel):
        panel.append_log('info', 'from viewer', src='viewer-100')
        panel.append_log('info', 'from indexer', src='indexer-200')
        viewer_text = panel._src_tabs['viewer-100'].toPlainText()
        indexer_text = panel._src_tabs['indexer-200'].toPlainText()
        assert 'from viewer' in viewer_text
        assert 'from indexer' not in viewer_text
        assert 'from indexer' in indexer_text
        assert 'from viewer' not in indexer_text

    def test_level_filter(self, panel):
        panel.append_log('debug', 'debug msg', src='v-1')
        panel.append_log('info', 'info msg', src='v-1')
        panel.append_log('warning', 'warn msg', src='v-1')
        panel.append_log('error', 'error msg', src='v-1')
        assert len(panel._entries) == 4

        panel._level_combo.setCurrentText('WARNING')
        text = panel._all_tab.toPlainText()
        assert 'debug msg' not in text
        assert 'info msg' not in text
        assert 'warn msg' in text
        assert 'error msg' in text

    def test_db_filter(self, panel):
        panel.append_log('info', 'db1 msg', src='v-1', db='mydb')
        panel.append_log('info', 'db2 msg', src='v-1', db='otherdb')
        assert panel._db_combo.count() == 3  # ALL + mydb + otherdb

        panel._db_combo.setCurrentText('mydb')
        text = panel._all_tab.toPlainText()
        assert 'db1 msg' in text
        assert 'db2 msg' not in text

    def test_clear(self, panel):
        panel.append_log('info', 'msg', src='v-1')
        panel._clear()
        assert len(panel._entries) == 0
        assert panel._all_tab.toPlainText() == ''

    def test_instance(self, panel):
        from wafer.app.viewer.widgets.dev_log_panel import DevLogPanel
        assert DevLogPanel.instance() is panel
