import os
import pytest
from unittest.mock import MagicMock, patch

from PySide6 import QtWidgets
from wafer.core.db.setting_db import SettingDB


@pytest.fixture(autouse=True)
def _isolate_widget(monkeypatch):
    monkeypatch.setattr(
        'wafer.builtins.plugin_manager.data_tab.list_setting_db_names',
        lambda: [],
    )


class TestDatabaseManagerWidget:

    def test_db_list_populated(self, qtbot, tmp_path, monkeypatch):
        names = ['alpha', 'beta', 'gamma']
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: list(names),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget

        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        items = [dlg._db_list.item(i).text() for i in range(dlg._db_list.count())]
        assert items == names

    def test_select_db_loads_detail(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'mydb.db')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder('/src/photos')
        sdb.add_ignore_folder('/src/photos/.cache')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['mydb'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget

        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)

        detail = dlg._detail_widget
        assert detail._source_list.count() == 1
        assert detail._ignore_list.count() == 1

    def test_add_database(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['existing'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.InputDialog.get_text',
            staticmethod(lambda *a, **kw: 'new_db'),
        )
        mock_new_main = MagicMock()
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.AppProcess.new_main',
            mock_new_main,
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget

        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)

        dlg._add_database()

        mock_new_main.assert_called_once_with('--indexer', 'new_db')

    def test_delete_database_with_node(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['keep', 'del_me'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.ConfirmDialog.ask',
            staticmethod(lambda *a, **kw: 'Delete'),
        )
        mock_node = MagicMock()
        from wafer.core.commands.binding.instance_registry import InstanceRegistry
        monkeypatch.setattr(InstanceRegistry.instance(), 'resolve_node', lambda: mock_node)
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget

        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(1)
        dlg._delete_database()

        mock_node.send_reliable.assert_called_once_with(
            'db.delete', 'del_me', dst='indexer', db='del_me',
        )

    def test_delete_database_no_node_removes_files(self, qtbot, tmp_path, monkeypatch):
        data_dir = tmp_path / 'data'
        data_dir.mkdir()
        dirs_dir = tmp_path / 'dirs'
        dirs_dir.mkdir()
        db_file = data_dir / 'del_me.db'
        db_file.write_text('')
        setting_file = dirs_dir / 'del_me.db'
        setting_file.write_text('')

        deleted = [False]
        def fake_names():
            if deleted[0]:
                return ['keep']
            return ['keep', 'del_me']

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            fake_names,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.data_db_path',
            lambda name: str(data_dir / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(dirs_dir / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.ConfirmDialog.ask',
            staticmethod(lambda *a, **kw: 'Delete'),
        )
        from wafer.core.commands.binding.instance_registry import InstanceRegistry
        monkeypatch.setattr(InstanceRegistry.instance(), 'resolve_node', lambda: None)
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget

        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(1)
        deleted[0] = True
        dlg._delete_database()

        assert not db_file.exists()
        assert not setting_file.exists()


class TestDatabaseDetailWidget:

    def test_add_source_folder(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: str(tmp_path / 'photos')),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        widget._add_source()
        assert widget._source_list.count() == 1
        assert widget._buffers['test'][0] == []

    def test_add_source_no_duplicate(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        folder = str(tmp_path / 'photos')
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: folder),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        widget._add_source()
        widget._add_source()
        assert widget._source_list.count() == 1

    def test_remove_source_folder(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        folder = str(tmp_path / 'my_folder')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder(folder)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        assert widget._source_list.count() == 1
        widget._source_list.setCurrentRow(0)
        widget._remove_source()
        assert widget._source_list.count() == 0
        assert sdb.get_all_parent_folders() == [folder.replace('\\', '/')]

    def test_add_ignore_folder(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: str(tmp_path / 'cache')),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        widget._add_ignore()
        assert widget._ignore_list.count() == 1
        assert widget._buffers['test'][1] == []

    def test_remove_ignore_folder(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        folder = str(tmp_path / 'my_cache')
        sdb = SettingDB(sdb_path)
        sdb.add_ignore_folder(folder)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        assert widget._ignore_list.count() == 1
        widget._ignore_list.setCurrentRow(0)
        widget._remove_ignore()
        assert widget._ignore_list.count() == 0
        assert sdb.get_all_ignore_folders() == [folder.replace('\\', '/')]

    def test_load_populates_both_lists(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'full.db')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder('/src/a')
        sdb.add_parent_folder('/src/b')
        sdb.add_ignore_folder('/src/a/.tmp')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('full')

        assert widget._source_list.count() == 2
        assert widget._ignore_list.count() == 1

    def test_has_changes_no_change(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        src = str(tmp_path / 'src_a').replace('\\', '/')
        ign = str(tmp_path / 'ign_b').replace('\\', '/')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder(src)
        sdb.add_ignore_folder(ign)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        initial = {'test': ([src], [ign])}
        assert not widget.has_changes(initial)

    def test_has_changes_with_change(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        src = str(tmp_path / 'src_a').replace('\\', '/')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder(src)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: '/src/b'),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')
        widget._add_source()

        initial = {'test': ([src], [])}
        assert widget.has_changes(initial)

    def test_commit_writes_to_db(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        sdb = SettingDB(sdb_path)
        new_folder = str(tmp_path / 'new_folder')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: new_folder),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')
        widget._add_source()

        initial = {'test': ([], [])}
        changed = widget.commit(initial)
        assert changed == ['test']
        assert len(sdb.get_all_parent_folders()) == 1

    def test_commit_skips_unchanged(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        src = str(tmp_path / 'src_a').replace('\\', '/')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder(src)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')

        initial = {'test': ([src], [])}
        changed = widget.commit(initial)
        assert changed == []

    def test_buffer_preserved_across_db_switch(self, qtbot, tmp_path, monkeypatch):
        sdb_path_a = str(tmp_path / 'db_a.db')
        sdb_path_b = str(tmp_path / 'db_b.db')
        SettingDB(sdb_path_a)
        SettingDB(sdb_path_b)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: '/added/path'),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)

        widget.load('db_a')
        widget._add_source()
        assert widget._source_list.count() == 1

        widget.load('db_b')
        assert widget._source_list.count() == 0

        widget.load('db_a')
        assert widget._source_list.count() == 1

    def test_revert_restores_buffers(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test.db')
        SettingDB(sdb_path)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: '/added'),
        )
        from wafer.builtins.database_manager.widget import _DatabaseDetailWidget
        widget = _DatabaseDetailWidget()
        qtbot.addWidget(widget)
        widget.load('test')
        widget._add_source()

        initial = {'test': ([], [])}
        widget.revert(initial)
        assert widget._buffers['test'] == ([], [])


class TestDatabaseManagerCommands:

    def test_toggle_or_standalone_with_mainwindow(self):
        from wafer.builtins.commands.app import _toggle_or_standalone
        mock_ctx = MagicMock()
        mock_w = MagicMock()
        mock_ctx.get_instance = lambda name: mock_w if name == "MainWindow" else None
        _toggle_or_standalone(mock_ctx, "Database Manager", lambda: None, "test")
        mock_w._layout_manager.toggle_panel.assert_called_once_with("Database Manager")

    def test_toggle_or_standalone_without_mainwindow(self, qtbot, monkeypatch):
        from PySide6 import QtCore
        from wafer.builtins.commands.app import _toggle_or_standalone, _standalone_dialogs

        class _FakeStore:
            def __init__(self, *a, **kw): pass
            def save(self, *a, **kw): pass
            def restore(self, *a, **kw): pass

        monkeypatch.setattr(
            'wafer.builtins.commands.app.DialogLayoutStore',
            _FakeStore,
        )
        mock_ctx = MagicMock()
        mock_ctx.get_instance = lambda name: None
        widget = QtWidgets.QWidget()
        _toggle_or_standalone(mock_ctx, "Test Panel", lambda: widget, "test_toggle")
        assert "test_toggle" in _standalone_dialogs
        dlg = _standalone_dialogs["test_toggle"]
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

    def test_open_standalone_reuses_existing(self, qtbot, monkeypatch):
        from PySide6 import QtCore
        from wafer.builtins.commands.app import _open_standalone, _standalone_dialogs

        class _FakeStore:
            def __init__(self, *a, **kw): pass
            def save(self, *a, **kw): pass
            def restore(self, *a, **kw): pass

        monkeypatch.setattr(
            'wafer.builtins.commands.app.DialogLayoutStore',
            _FakeStore,
        )
        _standalone_dialogs.clear()
        w1 = QtWidgets.QWidget()
        _open_standalone(lambda: w1, "Title", "reuse_key")
        dlg1 = _standalone_dialogs.get("reuse_key")
        assert dlg1 is not None
        dlg1.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg1)

        _open_standalone(lambda: QtWidgets.QWidget(), "Title", "reuse_key")
        assert _standalone_dialogs["reuse_key"] is dlg1


class TestDatabaseManagerSaveCancel:

    def test_has_changes_false_when_no_edit(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        sdb = SettingDB(sdb_path)
        sdb.add_parent_folder('/src/a')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)

        assert not dlg.has_changes()

    def test_has_changes_true_after_add(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        SettingDB(sdb_path)

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: '/new/folder'),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)
        dlg._detail_widget._add_source()

        assert dlg.has_changes()

    def test_on_save_commits_without_closing(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        SettingDB(sdb_path)
        save_folder = str(tmp_path / 'save_folder')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: save_folder),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)
        dlg._detail_widget._add_source()

        dlg._on_save()

        sdb = SettingDB(sdb_path)
        assert len(sdb.get_all_parent_folders()) == 1
        assert not dlg.has_changes()

    def test_on_revert_restores_state(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        SettingDB(sdb_path)
        revert_folder = str(tmp_path / 'revert_folder')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: revert_folder),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)
        dlg._detail_widget._add_source()
        assert dlg.has_changes()

        dlg._on_revert()
        assert not dlg.has_changes()

        sdb = SettingDB(sdb_path)
        assert sdb.get_all_parent_folders() == []

    def test_close_does_not_write(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        SettingDB(sdb_path)
        cancel_folder = str(tmp_path / 'cancel_folder')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: cancel_folder),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)
        dlg._detail_widget._add_source()

        dlg.close()

        sdb = SettingDB(sdb_path)
        assert sdb.get_all_parent_folders() == []

    def test_save_buttons_exist(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        save_btn = dlg.findChild(QtWidgets.QPushButton, 'save_btn')
        revert_btn = dlg.findChild(QtWidgets.QPushButton, 'cancel_btn')
        assert save_btn is not None
        assert revert_btn is not None
        assert revert_btn.text() == 'Cancel'

    def test_save_sends_rescan(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        SettingDB(sdb_path)
        folder = str(tmp_path / 'rescan_folder')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: folder),
        )
        mock_node = MagicMock()
        from wafer.core.commands.binding.instance_registry import InstanceRegistry
        monkeypatch.setattr(InstanceRegistry.instance(), 'resolve_node', lambda: mock_node)
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)
        dlg._detail_widget._add_source()

        dlg._on_save()

        mock_node.send_coalesced.assert_called_once_with('rescan')

    def test_save_no_rescan_without_node(self, qtbot, tmp_path, monkeypatch):
        sdb_path = str(tmp_path / 'test_db.db')
        SettingDB(sdb_path)
        folder = str(tmp_path / 'no_node_folder')

        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: sdb_path,
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.QtWidgets.QFileDialog.getExistingDirectory',
            staticmethod(lambda *a, **kw: folder),
        )
        from wafer.core.commands.binding.instance_registry import InstanceRegistry
        monkeypatch.setattr(InstanceRegistry.instance(), 'resolve_node', lambda: None)
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        dlg._db_list.setCurrentRow(0)
        dlg._detail_widget._add_source()

        dlg._on_save()

        sdb = SettingDB(sdb_path)
        assert len(sdb.get_all_parent_folders()) == 1


class TestDatabaseManagerTabs:

    def test_tabs_exist(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        assert dlg._tabs.count() == 2
        assert dlg._tabs.tabText(0) == 'Paths'
        assert dlg._tabs.tabText(1) == 'Data'

    def test_send_purge(self, qtbot, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['db1'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        mock_node = MagicMock()
        from wafer.core.commands.binding.instance_registry import InstanceRegistry
        monkeypatch.setattr(InstanceRegistry.instance(), 'resolve_node', lambda: mock_node)
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)

        dlg._send_purge([('db1', 'exif')], True)
        mock_node.send_reliable.assert_called_once_with(
            'purge.collector',
            {'collector': 'exif', 're_collect': True},
            dst='indexer', db='db1',
        )

    def test_paths_tab_uses_scroll_area(self, qtbot, tmp_path, monkeypatch):
        from PySide6 import QtWidgets
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.list_setting_db_names',
            lambda: ['test_db'],
        )
        monkeypatch.setattr(
            'wafer.builtins.database_manager.widget.setting_db_path',
            lambda name: str(tmp_path / f'{name}.db'),
        )
        from wafer.builtins.database_manager.widget import DatabaseManagerWidget
        dlg = DatabaseManagerWidget()
        qtbot.addWidget(dlg)
        paths_widget = dlg._tabs.widget(0)
        assert isinstance(paths_widget, QtWidgets.QScrollArea)


class TestDialogLayoutStore:

    def test_save_and_restore_geometry(self, qtbot, tmp_path, monkeypatch):
        from PySide6 import QtWidgets
        monkeypatch.setattr(
            'wafer.utils.paths.resolve_data_path',
            lambda name: tmp_path / name,
        )
        from wafer.core.qt.window import DialogLayoutStore

        store = DialogLayoutStore('test_dialog')

        dlg = QtWidgets.QDialog()
        qtbot.addWidget(dlg)
        dlg.resize(400, 300)
        dlg.move(100, 100)

        store.save(dlg)

        dlg2 = QtWidgets.QDialog()
        qtbot.addWidget(dlg2)
        store.restore(dlg2)

    def test_save_and_restore_splitter(self, qtbot, tmp_path, monkeypatch):
        from PySide6 import QtWidgets, QtCore
        monkeypatch.setattr(
            'wafer.utils.paths.resolve_data_path',
            lambda name: tmp_path / name,
        )
        from wafer.core.qt.window import DialogLayoutStore

        store = DialogLayoutStore('test_splitter')

        dlg = QtWidgets.QDialog()
        qtbot.addWidget(dlg)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        w1 = QtWidgets.QWidget()
        w2 = QtWidgets.QWidget()
        splitter.addWidget(w1)
        splitter.addWidget(w2)
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(splitter)

        dlg.resize(400, 600)
        dlg.show()
        splitter.setSizes([200, 400])

        store.save(dlg, main=splitter)

        dlg2 = QtWidgets.QDialog()
        qtbot.addWidget(dlg2)
        splitter2 = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter2.addWidget(QtWidgets.QWidget())
        splitter2.addWidget(QtWidgets.QWidget())
        layout2 = QtWidgets.QVBoxLayout(dlg2)
        layout2.addWidget(splitter2)
        dlg2.resize(400, 600)
        dlg2.show()

        store.restore(dlg2, main=splitter2)
        sizes = splitter2.sizes()
        assert sizes[0] > 0
        assert sizes[1] > sizes[0]
        dlg.close()
        dlg2.close()
