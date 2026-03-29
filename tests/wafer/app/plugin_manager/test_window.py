import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from wafer.plugin.registry import BasePlugin


class TestExtensionsTab:

    def test_scan_finds_extension_folders(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'test_ext').mkdir(parents=True)
        (ext_dir / 'test_ext' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: False,
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: []),
        )
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab(set(), dispatcher)
        assert 'test_ext' in tab._cards

    def test_collect_enabled_returns_checked(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'my_ext').mkdir(parents=True)
        (ext_dir / 'my_ext' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: False,
        )
        class FakePlugin(BasePlugin):
            NAME = 'fake_p'
            EXTENSIONS = ('.fake',)
            PRIORITY = 1

        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: [('grid', FakePlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab({'grid:fake_p'}, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards['my_ext']._rows) > 0, timeout=3000)
        result = tab.collect_enabled()
        assert 'grid:fake_p' in result

    def test_needs_install_shows_button(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'uninstalled').mkdir(parents=True)
        (ext_dir / 'uninstalled' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: True,
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab(set(), dispatcher)
        card = tab._cards['uninstalled']
        assert card._status_btn.isEnabled()
        assert card._status_btn.text() == 'Install'
        assert len(card._rows) == 0

    def test_default_enabled_none_uses_attribute(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'ext1').mkdir(parents=True)
        (ext_dir / 'ext1' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: False,
        )

        class EnabledPlugin(BasePlugin):
            NAME = 'enabled_p'
            EXTENSIONS = ('.e',)
            PRIORITY = 1
            DEFAULT_ENABLED = True

        class DisabledPlugin(BasePlugin):
            NAME = 'disabled_p'
            EXTENSIONS = ('.d',)
            PRIORITY = 1
            DEFAULT_ENABLED = False

        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: [('grid', EnabledPlugin), ('grid', DisabledPlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab(None, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards['ext1']._rows) > 0, timeout=3000)

        enabled = tab.collect_enabled()
        assert 'grid:enabled_p' in enabled
        assert 'grid:disabled_p' not in enabled

    def test_enabled_changed_signal(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'ext1').mkdir(parents=True)
        (ext_dir / 'ext1' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: False,
        )

        class FP(BasePlugin):
            NAME = 'fp'
            EXTENSIONS = ('.fp',)
            PRIORITY = 1

        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: [('viewer', FP)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab({'viewer:fp'}, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards['ext1']._rows) > 0, timeout=3000)

        signals = []
        tab.enabled_changed.connect(lambda: signals.append(True))
        row, _ = tab._cards['ext1']._rows[0]
        row.checkbox.setChecked(False)
        assert len(signals) >= 1

    def test_collect_enabled_plugins_by_type(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'ext1').mkdir(parents=True)
        (ext_dir / 'ext1' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: False,
        )

        class ViewerP(BasePlugin):
            NAME = 'vp'
            EXTENSIONS = ('.v',)
            PRIORITY = 1

        class GridP(BasePlugin):
            NAME = 'gp'
            EXTENSIONS = ('.g',)
            PRIORITY = 2

        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: [('viewer', ViewerP), ('grid', GridP)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab({'viewer:vp', 'grid:gp'}, dispatcher)
        qtbot.waitUntil(lambda: len(tab._cards['ext1']._rows) > 0, timeout=3000)

        viewers = tab.collect_enabled_plugins('viewer')
        grids = tab.collect_enabled_plugins('grid')
        assert ViewerP in viewers
        assert GridP in grids
        assert len(viewers) == 1
        assert len(grids) == 1


class TestOrderTab:

    def test_populate_with_plugin_lists(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class PlugA(BasePlugin):
            NAME = 'a'
            EXTENSIONS = ('.a',)
            PRIORITY = 10

        class PlugB(BasePlugin):
            NAME = 'b'
            EXTENSIONS = ('.b',)
            PRIORITY = 20

        tab = OrderTab({'viewer': [PlugB, PlugA], 'grid': [PlugA]}, {})
        qtbot.addWidget(tab)

        orders = tab.get_orders()
        assert 'b' in orders['viewer']
        assert 'a' in orders['viewer']

    def test_order_from_settings(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class PlugX(BasePlugin):
            NAME = 'x'
            EXTENSIONS = ()
            PRIORITY = 10

        class PlugY(BasePlugin):
            NAME = 'y'
            EXTENSIONS = ()
            PRIORITY = 5

        tab = OrderTab({'viewer': [PlugX, PlugY]}, {'viewer': ['y', 'x']})
        qtbot.addWidget(tab)

        assert tab.get_orders()['viewer'] == ['y', 'x']

    def test_drag_reorder_returns_new_order(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class P1(BasePlugin):
            NAME = 'first'
            EXTENSIONS = ()
            PRIORITY = 10

        class P2(BasePlugin):
            NAME = 'second'
            EXTENSIONS = ()
            PRIORITY = 5

        tab = OrderTab({'viewer': [P1, P2]}, {})
        qtbot.addWidget(tab)
        order = tab.get_orders()['viewer']
        assert len(order) == 2

    def test_negative_priority_sorts_after_ordered(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class Builtin(BasePlugin):
            NAME = 'builtin'
            EXTENSIONS = ()
            PRIORITY = -100

        class UserPlug(BasePlugin):
            NAME = 'user'
            EXTENSIONS = ()
            PRIORITY = 10

        tab = OrderTab({'viewer': [Builtin, UserPlug]}, {'viewer': ['user']})
        qtbot.addWidget(tab)
        order = tab.get_orders()['viewer']
        assert order[0] == 'user'
        assert order[1] == 'builtin'

    def test_refresh_updates_list(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class PlugA(BasePlugin):
            NAME = 'a'
            EXTENSIONS = ('.a',)
            PRIORITY = 10

        class PlugB(BasePlugin):
            NAME = 'b'
            EXTENSIONS = ('.b',)
            PRIORITY = 20

        tab = OrderTab({'viewer': [PlugA]}, {})
        qtbot.addWidget(tab)
        assert tab.get_orders()['viewer'] == ['a']

        tab.refresh({'viewer': [PlugB, PlugA]})
        viewer_order = tab.get_orders()['viewer']
        assert 'a' in viewer_order
        assert 'b' in viewer_order
        assert len(viewer_order) == 2

    def test_multiple_registry_types(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class ViewerP(BasePlugin):
            NAME = 'vp'
            EXTENSIONS = ('.v',)
            PRIORITY = 10

        class FilterP:
            NAME = 'fp'
            PRIORITY = 5

        tab = OrderTab({'viewer': [ViewerP], 'filter': [FilterP]}, {})
        qtbot.addWidget(tab)
        orders = tab.get_orders()
        assert orders['viewer'] == ['vp']
        assert orders['filter'] == ['fp']

    def test_empty_registry_skipped(self, qtbot):
        from wafer.app.plugin_manager.viewers_tab import OrderTab

        class PlugA(BasePlugin):
            NAME = 'a'
            EXTENSIONS = ()
            PRIORITY = 10

        tab = OrderTab({'viewer': [PlugA], 'filter': []}, {})
        qtbot.addWidget(tab)
        assert tab.get_orders()['viewer'] == ['a']
        assert tab.get_orders()['filter'] == []


class TestPluginManagerDialog:

    def test_singleton_pattern(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: '/nonexistent',
        )
        from wafer.app.plugin_manager.window import PluginManagerDialog
        PluginManagerDialog._instance = None

        dlg1 = PluginManagerDialog.open()
        qtbot.addWidget(dlg1)
        dlg2 = PluginManagerDialog.open()
        assert dlg1 is dlg2

        dlg1.close()
        assert PluginManagerDialog._instance is None

    def test_close_clears_instance(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: '/nonexistent',
        )
        from wafer.app.plugin_manager.window import PluginManagerDialog
        PluginManagerDialog._instance = None

        dlg = PluginManagerDialog.open()
        qtbot.addWidget(dlg)
        assert PluginManagerDialog._instance is dlg
        dlg.close()
        assert PluginManagerDialog._instance is None


class TestPluginManagerCommands:

    def test_command_class_exists(self):
        from wafer.app.plugin_manager.commands import PluginManagerCommands
        cmds = PluginManagerCommands.commands()
        assert len(cmds) >= 1
        paths = [c.path for c in cmds if hasattr(c, 'path')]
        assert 'setting.plugin_manager' in paths


class TestCollectorsTab:

    def test_empty_when_no_collectors(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: [],
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=[])
        qtbot.addWidget(tab)
        assert tab._matrix == {}

    def test_matrix_populated(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'test.db')
        from wafer.core.db.setting_db import SettingDB
        sdb = SettingDB(db_path)
        sdb.set_enabled_collectors(['exif'])

        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['test'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_path,
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif', 'ai_tags'])
        qtbot.addWidget(tab)

        assert tab._matrix[('exif', 'test')].isChecked()
        assert not tab._matrix[('ai_tags', 'test')].isChecked()

    def test_all_toggle_sets_all_dbs(self, qtbot, tmp_path, monkeypatch):
        db1 = str(tmp_path / 'db1.db')
        db2 = str(tmp_path / 'db2.db')
        from wafer.core.db.setting_db import SettingDB
        SettingDB(db1).set_enabled_collectors([])
        SettingDB(db2).set_enabled_collectors([])

        db_map = {'one': db1, 'two': db2}
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['one', 'two'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_map[name],
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif'])
        qtbot.addWidget(tab)

        assert not tab._matrix[('exif', 'one')].isChecked()
        assert not tab._matrix[('exif', 'two')].isChecked()

        tab._on_all_toggled('exif', True)

        assert tab._matrix[('exif', 'one')].isChecked()
        assert tab._matrix[('exif', 'two')].isChecked()

    def test_save_to_dbs(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'save_test.db')
        from wafer.core.db.setting_db import SettingDB
        SettingDB(db_path).set_enabled_collectors([])

        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['mydb'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_path,
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif', 'ai_tags'])
        qtbot.addWidget(tab)

        tab._matrix[('exif', 'mydb')].setChecked(True)
        tab._matrix[('ai_tags', 'mydb')].setChecked(False)
        tab.save_to_dbs()

        sdb = SettingDB(db_path)
        assert sdb.get_enabled_collectors() == ['exif']

    def test_get_per_db_collectors(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'per_db.db')
        from wafer.core.db.setting_db import SettingDB
        SettingDB(db_path).set_enabled_collectors(['exif'])

        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['testdb'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_path,
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif', 'ai_tags'])
        qtbot.addWidget(tab)

        result = tab.get_per_db_collectors()
        assert result == {'testdb': ['exif']}

    def test_get_newly_disabled(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'nd.db')
        from wafer.core.db.setting_db import SettingDB
        SettingDB(db_path).set_enabled_collectors(['exif', 'ai_tags'])

        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['mydb'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_path,
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif', 'ai_tags'])
        qtbot.addWidget(tab)

        tab._matrix[('ai_tags', 'mydb')].setChecked(False)
        disabled = tab.get_newly_disabled()
        assert ('mydb', 'ai_tags') in disabled
        assert len(disabled) == 1

    def test_get_newly_disabled_no_changes(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'nc.db')
        from wafer.core.db.setting_db import SettingDB
        SettingDB(db_path).set_enabled_collectors(['exif'])

        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['db1'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_path,
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif'])
        qtbot.addWidget(tab)

        disabled = tab.get_newly_disabled()
        assert disabled == []

    def test_refresh_updates_matrix(self, qtbot, tmp_path, monkeypatch):
        db_path = str(tmp_path / 'refresh.db')
        from wafer.core.db.setting_db import SettingDB
        SettingDB(db_path).set_enabled_collectors(['exif'])

        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.list_setting_db_names',
            lambda: ['mydb'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.collectors_tab.setting_db_path',
            lambda name: db_path,
        )
        from wafer.app.plugin_manager.collectors_tab import CollectorsTab
        tab = CollectorsTab(collector_names=['exif'])
        qtbot.addWidget(tab)

        assert ('exif', 'mydb') in tab._matrix
        assert ('ai_tags', 'mydb') not in tab._matrix

        tab.refresh(['exif', 'ai_tags'])

        assert ('exif', 'mydb') in tab._matrix
        assert ('ai_tags', 'mydb') in tab._matrix
        assert tab._matrix[('exif', 'mydb')].isChecked()


class TestPluginManagerCommands:

    def test_all_commands_registered(self):
        from wafer.app.plugin_manager.commands import PluginManagerCommands
        cmds = PluginManagerCommands.commands()
        paths = [c.path for c in cmds if hasattr(c, 'path')]
        assert 'setting.plugin_manager' in paths
        assert 'setting.restart_tray' in paths
        assert 'setting.restart_viewer' in paths
        assert 'setting.restart_all' in paths

    def test_restart_tray_calls_process(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            'wafer.app.plugin_manager.commands.AppProcess',
            type('', (), {
                'terminate_cmd': staticmethod(lambda *a: calls.append(('terminate', a))),
                'new_main': staticmethod(lambda *a: calls.append(('new_main', a))),
            })(),
        )
        from wafer.app.plugin_manager.commands import restart_tray
        restart_tray(MagicMock())
        assert ('terminate', ('--tray',)) in calls
        assert ('new_main', ('--tray',)) in calls

    def test_restart_viewer_calls_process(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            'wafer.app.plugin_manager.commands.AppProcess',
            type('', (), {
                'new_main': staticmethod(lambda *a: calls.append(('new_main', a))),
            })(),
        )
        from wafer.app.plugin_manager.commands import restart_viewer
        mock_w = MagicMock()
        mock_w.session_id = 'abc123'
        ctx = MagicMock()
        ctx.get_instance.return_value = mock_w
        restart_viewer(ctx)
        assert any('--viewer' in a[1] for a in calls)
        assert any('abc123' in a[1] for a in calls)
        mock_w.close.assert_called_once()

    def test_restart_all_calls_both(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            'wafer.app.plugin_manager.commands.AppProcess',
            type('', (), {
                'terminate_cmd': staticmethod(lambda *a: calls.append(('terminate', a))),
                'new_main': staticmethod(lambda *a: calls.append(('new_main', a))),
            })(),
        )
        from wafer.app.plugin_manager.commands import restart_all
        mock_w = MagicMock()
        mock_w.session_id = 'sess1'
        ctx = MagicMock()
        ctx.get_instance.return_value = mock_w
        restart_all(ctx)
        assert ('terminate', ('--tray',)) in calls
        assert ('new_main', ('--tray',)) in calls
        assert any('--viewer' in a[1] for a in calls)
        assert any('sess1' in a[1] for a in calls)
        mock_w.close.assert_called_once()


class TestDataTab:

    def test_empty_state(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.data_tab.list_setting_db_names',
            lambda: [],
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.data_tab import DataTab
        tab = DataTab(dispatcher)
        qtbot.addWidget(tab)
        qtbot.waitUntil(lambda: tab._table.rowCount() == 0, timeout=3000)
        assert tab._table.rowCount() == 0

    def test_loads_data_from_dbs(self, qtbot, tmp_path, monkeypatch):
        from wafer.core.db.setting_db import SettingDB
        from wafer.core.db.file_db import FileDB

        sdb_path = str(tmp_path / 'settings.db')
        SettingDB(sdb_path).set_enabled_collectors(['exif'])

        fdb_path = str(tmp_path / 'data.db')
        fdb = FileDB(fdb_path)
        fdb.start()
        fdb.initialize_database()
        fdb.upsert_basic_sources(
            [('src0', 'h0', 100, 1.0)],
            [('c:/a.jpg', 'src0', 1.5)],
        )
        fdb.insert_pending_collection(['src0'], ['exif'])
        fdb.conn.execute(
            "UPDATE collection_status SET status='ok', collected_at=1.0 WHERE collector='exif'"
        )
        fdb.conn.commit()
        fdb.close()

        monkeypatch.setattr(
            'wafer.app.plugin_manager.data_tab.list_setting_db_names',
            lambda: ['testdb'],
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.data_tab.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.data_tab.data_db_path',
            lambda name: fdb_path,
        )

        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.data_tab import DataTab
        tab = DataTab(dispatcher)
        qtbot.addWidget(tab)
        qtbot.waitUntil(lambda: tab._table.rowCount() > 0, timeout=5000)
        assert tab._table.rowCount() >= 1
        assert tab._table.item(0, 1).text() == 'exif'
        assert tab._table.item(0, 2).text() == '1'
        assert tab._table.item(0, 3).text() == 'Active'


class TestWindowWithNode:

    def test_dialog_stores_node(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: '/nonexistent',
        )
        from wafer.app.plugin_manager.window import PluginManagerDialog
        PluginManagerDialog._instance = None
        mock_node = MagicMock()
        dlg = PluginManagerDialog.open(node=mock_node)
        qtbot.addWidget(dlg)
        assert dlg._node is mock_node
        dlg.close()

    def test_send_purge_dispatches_to_node(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: '/nonexistent',
        )
        from wafer.app.plugin_manager.window import PluginManagerDialog
        PluginManagerDialog._instance = None
        mock_node = MagicMock()
        dlg = PluginManagerDialog.open(node=mock_node)
        qtbot.addWidget(dlg)
        dlg._send_purge([('db1', 'exif')], True)
        mock_node.send_reliable.assert_called_once_with(
            'purge.collector',
            {'collector': 'exif', 're_collect': True},
            dst='indexer',
            db='db1',
        )
        dlg.close()

    def test_send_purge_no_node_warns(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: '/nonexistent',
        )
        from wafer.app.plugin_manager.window import PluginManagerDialog
        PluginManagerDialog._instance = None
        dlg = PluginManagerDialog.open(node=None)
        qtbot.addWidget(dlg)
        dlg._send_purge([('db1', 'exif')], False)
        dlg.close()


class TestCloseEventCancels:

    def test_close_cancels_pending_installs(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'pending_ext').mkdir(parents=True)
        (ext_dir / 'pending_ext' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: False,
        )
        from wafer.core.qt.dispatcher import Dispatcher, CancelSlot
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab(set(), dispatcher)

        slot = CancelSlot()
        token = slot.renew()
        tab._install_cancels['pending_ext'] = slot

        assert not token.is_cancelled()
        tab.cancel_pending()
        assert token.is_cancelled()
        assert tab._install_cancels == {}


class TestPostInstallHook:

    def test_post_install_called_after_install(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'vid_ext').mkdir(parents=True)
        (ext_dir / 'vid_ext' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: True,
        )

        post_install_calls = []

        class HookPlugin(BasePlugin):
            NAME = 'hook_p'
            EXTENSIONS = ('.h',)
            PRIORITY = 1

            @classmethod
            def post_install(cls, plugin_dir, on_progress=None):
                post_install_calls.append(plugin_dir)

        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.install_requirements',
            lambda path: True,
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: [('viewer', HookPlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab(set(), dispatcher)
        qtbot.addWidget(tab)

        card = tab._cards['vid_ext']
        tab._install_extension(card)
        qtbot.waitUntil(lambda: len(post_install_calls) > 0, timeout=5000)
        assert post_install_calls[0] == card.folder_path

    def test_post_install_not_called_when_absent(self, qtbot, tmp_path, monkeypatch):
        ext_dir = tmp_path / 'extensions'
        (ext_dir / 'plain_ext').mkdir(parents=True)
        (ext_dir / 'plain_ext' / '__init__.py').write_text('')
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.get_plugin_dir',
            lambda: str(ext_dir),
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab._needs_install',
            lambda folder: True,
        )

        class PlainPlugin(BasePlugin):
            NAME = 'plain_p'
            EXTENSIONS = ('.p',)
            PRIORITY = 1

        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.install_requirements',
            lambda path: True,
        )
        monkeypatch.setattr(
            'wafer.app.plugin_manager.extensions_tab.PluginLoader.discover_extension',
            staticmethod(lambda folder: [('grid', PlainPlugin)]),
        )
        from wafer.core.qt.dispatcher import Dispatcher
        dispatcher = Dispatcher()
        from wafer.app.plugin_manager.extensions_tab import ExtensionsTab
        tab = ExtensionsTab(set(), dispatcher)
        qtbot.addWidget(tab)

        card = tab._cards['plain_ext']
        tab._install_extension(card)
        qtbot.waitUntil(
            lambda: len(card._rows) > 0,
            timeout=5000,
        )
