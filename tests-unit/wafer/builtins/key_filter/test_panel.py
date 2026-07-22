import pytest

from PySide6 import QtWidgets

from wafer.core.qt.dispatcher import Dispatcher
from wafer.plugin.key_filter import KeyFilter, MODE_BLACKLIST, MODE_WHITELIST

MODULE = "wafer.builtins.key_filter.panel"

KEY_ROWS = [("IFD0:Make", 100), ("IFD0:Model", 80), ("File:FileType", 50)]


class _SyncDispatcher(Dispatcher):
    def __init__(self):
        self._pool = None

    def post(self, fn, priority=5, cancel=None):
        fn()

    def invoke(self, fn):
        fn()


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    ini = tmp_path / "viewer_plugins.ini"
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(ini))
    monkeypatch.setattr(KeyFilter, "_broadcast_reload", staticmethod(lambda: None))
    KeyFilter._cache = None
    KeyFilter._subscribers = []
    yield
    KeyFilter._cache = None
    KeyFilter._subscribers = []


def _make_tab(qtbot, monkeypatch, prefix="exif"):
    from unittest.mock import patch
    with patch(f"{MODULE}._query_prefix_keys", return_value=list(KEY_ROWS)):
        from wafer.builtins.key_filter.panel import _FilterTab
        tab = _FilterTab(prefix, _SyncDispatcher())
        qtbot.addWidget(tab)
        tab.ensure_loaded()
    return tab


class TestFilterTab:
    def test_starts_clean(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        assert tab.is_dirty() is False

    def test_apply_persists_to_keyfilter(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._filter_keys = {"IFD0:Make"}
        assert tab.is_dirty() is True
        tab.apply()
        assert tab.is_dirty() is False
        assert KeyFilter.get("exif") == (MODE_BLACKLIST, frozenset({"IFD0:Make"}))

    def test_mode_change_inverts_selection(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._filter_keys = {"IFD0:Make"}
        tab._mode_combo.setCurrentIndex(1)
        assert tab._filter_mode == MODE_WHITELIST
        assert tab._filter_keys == {"IFD0:Model", "File:FileType"}

    def test_revert_restores_saved(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._filter_keys = {"IFD0:Make"}
        tab.revert()
        assert tab._filter_keys == set()
        assert tab.is_dirty() is False

    def test_check_all_toggles(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._on_check_all()
        assert tab._filter_keys == {"IFD0:Make", "IFD0:Model", "File:FileType"}
        tab._on_check_all()
        assert tab._filter_keys == set()

    def test_compute_delete_keys_blacklist(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._filter_keys = {"IFD0:Make"}
        assert tab.compute_delete_keys() == ["exif.IFD0:Make"]

    def test_compute_delete_keys_whitelist(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._filter_mode = MODE_WHITELIST
        tab._filter_keys = {"IFD0:Make"}
        deletes = set(tab.compute_delete_keys())
        assert deletes == {"exif.IFD0:Model", "exif.File:FileType"}


class TestSyncFromStore:
    def test_clean_tab_follows_store(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        KeyFilter.set_keys("exif", MODE_BLACKLIST, {"IFD0:Make"})
        tab.sync_from_store()
        assert tab._saved_keys == {"IFD0:Make"}
        assert tab._filter_keys == {"IFD0:Make"}
        assert tab.is_dirty() is False

    def test_clean_tab_follows_mode_change(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        KeyFilter.set_keys("exif", MODE_WHITELIST, {"IFD0:Make"})
        tab.sync_from_store()
        assert tab._filter_mode == MODE_WHITELIST
        assert tab._mode_combo.currentIndex() == 1
        assert tab.is_dirty() is False

    def test_dirty_tab_keeps_edits_updates_baseline(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        tab._filter_keys = {"IFD0:Model"}
        KeyFilter.set_keys("exif", MODE_BLACKLIST, {"IFD0:Make"})
        tab.sync_from_store()
        assert tab._filter_keys == {"IFD0:Model"}
        assert tab._saved_keys == {"IFD0:Make"}
        assert tab.is_dirty() is True

    def test_no_op_when_store_unchanged(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        rebuilt = []
        monkeypatch.setattr(tab, "_build_tree", lambda: rebuilt.append(True))
        tab.sync_from_store()
        assert rebuilt == []


class TestFilterChangeSubscription:
    def _make_widget(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._build_tabs", lambda self: None)
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._connect_bridge", lambda self: None)
        from wafer.builtins.key_filter.panel import KeyFilterWidget
        widget = KeyFilterWidget()
        widget._dispatcher = _SyncDispatcher()
        qtbot.addWidget(widget)
        return widget

    def test_show_subscribes_hide_unsubscribes(self, qtbot, monkeypatch):
        from PySide6 import QtGui
        widget = self._make_widget(qtbot, monkeypatch)
        widget.showEvent(QtGui.QShowEvent())
        assert widget._filter_callback in KeyFilter._subscribers
        widget.hideEvent(QtGui.QHideEvent())
        assert widget._filter_callback not in KeyFilter._subscribers

    def test_notify_routes_to_matching_tab(self, qtbot, monkeypatch):
        widget = self._make_widget(qtbot, monkeypatch)
        called = []

        class _T:
            def sync_from_store(self):
                called.append(True)

        widget._prefix_tabs = {"exif": _T()}
        widget._on_filter_changed("exif")
        widget._on_filter_changed("other")
        assert called == [True]


class TestPluginMeta:
    def test_source_is_builtin(self):
        from wafer.builtins.key_filter.panel import KeyFilterPanelPlugin
        assert KeyFilterPanelPlugin.SOURCE == "Builtin"

    def test_display_name(self):
        from wafer.builtins.key_filter.panel import KeyFilterPanelPlugin
        assert KeyFilterPanelPlugin.DISPLAY_NAME == "Metadata Filter"


class TestBuildTabs:
    def _make_widget(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._build_tabs", lambda self: None)
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._connect_bridge", lambda self: None)
        monkeypatch.setattr(f"{MODULE}._query_prefix_keys", lambda prefix: [])
        from wafer.builtins.key_filter.panel import KeyFilterWidget
        widget = KeyFilterWidget()
        widget._dispatcher = _SyncDispatcher()
        qtbot.addWidget(widget)
        return widget

    def test_populate_tabs_alphabetical(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.collector_resolver.names", lambda: ["exif"])
        widget = self._make_widget(qtbot, monkeypatch)
        widget._populate_tabs(["zebra", "alpha"])
        labels = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert labels == ["alpha", "exif", "zebra"]

    def test_populate_tabs_dedupes(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.collector_resolver.names", lambda: ["exif"])
        widget = self._make_widget(qtbot, monkeypatch)
        widget._populate_tabs(["exif", "wd14"])
        labels = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert labels == ["exif", "wd14"]

    def test_populate_tabs_includes_parsers(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.collector_resolver.names", lambda: ["exif"])
        monkeypatch.setattr(f"{MODULE}.parser_resolver.names", lambda: ["novelai"])
        widget = self._make_widget(qtbot, monkeypatch)
        widget._populate_tabs([])
        labels = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert labels == ["exif", "novelai"]


class _FakeTab:
    def __init__(self, prefix, dirty=True):
        self.prefix = prefix
        self._dirty = dirty
        self.applied = False
        self.stale = False

    def is_dirty(self):
        return self._dirty

    def apply(self):
        self.applied = True

    def compute_delete_keys(self):
        return [f"{self.prefix}.k"]

    def mark_stale(self):
        self.stale = True


class TestOnSaveReCollect:
    def _make_widget(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._build_tabs", lambda self: None)
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._connect_bridge", lambda self: None)
        from wafer.builtins.key_filter.panel import KeyFilterWidget
        widget = KeyFilterWidget()
        widget._dispatcher = _SyncDispatcher()
        qtbot.addWidget(widget)
        return widget

    def test_parser_prefix_forces_no_recollect(self, qtbot, monkeypatch):
        sent = []
        monkeypatch.setattr(f"{MODULE}.list_setting_db_names", lambda: ["db1"])
        monkeypatch.setattr(f"{MODULE}.parser_resolver.names", lambda: ["novelai"])
        monkeypatch.setattr(
            f"{MODULE}.KeyFilter.send_delete_keys",
            staticmethod(lambda db, keys, prefix, *, re_collect: sent.append((prefix, re_collect))),
        )

        class _Dlg:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return QtWidgets.QDialog.Accepted

            def delete_data(self):
                return True

            def recollect(self):
                return True

        monkeypatch.setattr(f"{MODULE}.FilterSaveConfirmDialog", _Dlg)
        widget = self._make_widget(qtbot, monkeypatch)
        widget._prefix_tabs = {"exif": _FakeTab("exif"), "novelai": _FakeTab("novelai")}
        widget._on_save()
        result = dict(sent)
        assert result["exif"] is True
        assert result["novelai"] is False


class TestReactiveReflection:
    def _make_widget(self, qtbot, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._build_tabs", lambda self: None)
        monkeypatch.setattr(f"{MODULE}.KeyFilterWidget._connect_bridge", lambda self: None)
        monkeypatch.setattr(f"{MODULE}._query_prefix_keys", lambda prefix: [])
        monkeypatch.setattr(f"{MODULE}.collector_resolver.names", lambda: [])
        monkeypatch.setattr(f"{MODULE}.parser_resolver.names", lambda: [])
        from wafer.builtins.key_filter.panel import KeyFilterWidget
        widget = KeyFilterWidget()
        widget._dispatcher = _SyncDispatcher()
        qtbot.addWidget(widget)
        return widget

    def test_db_update_marks_dirty_when_hidden(self, qtbot, monkeypatch):
        widget = self._make_widget(qtbot, monkeypatch)
        reloaded = []
        monkeypatch.setattr(widget, "_reload", lambda: reloaded.append(True))
        widget._on_db_updated("db1")
        assert widget._dirty is True
        assert reloaded == []

    def test_show_flushes_dirty(self, qtbot, monkeypatch):
        from PySide6 import QtGui
        widget = self._make_widget(qtbot, monkeypatch)
        reloaded = []
        monkeypatch.setattr(widget, "_reload", lambda: reloaded.append(True))
        widget._dirty = True
        widget.showEvent(QtGui.QShowEvent())
        assert widget._dirty is False
        assert reloaded == [True]

    def test_merge_adds_new_tab_and_marks_stale(self, qtbot, monkeypatch):
        widget = self._make_widget(qtbot, monkeypatch)
        widget._populate_tabs(["alpha"])
        existing = widget._prefix_tabs["alpha"]
        existing._loaded = True
        widget._merge_prefixes(["alpha", "zebra"])
        assert "zebra" in widget._prefix_tabs
        labels = [widget._tabs.tabText(i) for i in range(widget._tabs.count())]
        assert labels == ["alpha", "zebra"]

    def test_ensure_loaded_refreshes_when_stale(self, qtbot, monkeypatch):
        tab = _make_tab(qtbot, monkeypatch)
        loads = []
        monkeypatch.setattr(tab, "_load_keys", lambda: loads.append(True))
        tab.mark_stale()
        assert tab._stale is True
        tab.ensure_loaded()
        assert loads == [True]
        assert tab._stale is False



class TestQuerySampleValues:
    def _prep(self, monkeypatch):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
        conn.execute("CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT)")
        conn.execute("INSERT INTO meta_info VALUES ('/a.jpg', 'exif.Make', 'Canon')")
        conn.execute("INSERT INTO tags VALUES ('h1', 'exif.Make', 'Nikon')")
        conn.commit()
        monkeypatch.setattr(f"{MODULE}.list_setting_db_names", lambda: ["db1"])
        monkeypatch.setattr(f"{MODULE}._open_ro", lambda name: conn)
        return conn

    def test_returns_meta_and_tags(self, monkeypatch):
        from wafer.builtins.key_filter.panel import _query_sample_values
        self._prep(monkeypatch)
        rows = _query_sample_values("exif.Make")
        values = {r[2] for r in rows}
        assert values == {"Canon", "Nikon"}

    def test_respects_limit(self, monkeypatch):
        from wafer.builtins.key_filter.panel import _query_sample_values
        self._prep(monkeypatch)
        rows = _query_sample_values("exif.Make", limit=1)
        assert len(rows) == 1

    def test_orders_by_value_length_desc(self, monkeypatch):
        import sqlite3
        from wafer.builtins.key_filter.panel import _query_sample_values
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
        conn.execute("CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT)")
        for i, val in enumerate(["ab", "abcd", "a", "abc"]):
            conn.execute("INSERT INTO meta_info VALUES (?, 'k.v', ?)", (f"/{i}.jpg", val))
        conn.commit()
        monkeypatch.setattr(f"{MODULE}.list_setting_db_names", lambda: ["db1"])
        monkeypatch.setattr(f"{MODULE}._open_ro", lambda name: conn)
        rows = _query_sample_values("k.v", limit=3)
        assert [r[2] for r in rows] == ["abcd", "abc", "ab"]

    def test_fills_remaining_with_empty(self, monkeypatch, tmp_path):
        import sqlite3
        from wafer.builtins.key_filter.panel import _query_sample_values
        db_file = tmp_path / "sample.db"
        setup = sqlite3.connect(db_file)
        setup.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
        setup.execute("CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT)")
        setup.execute("INSERT INTO meta_info VALUES ('/x.jpg', 'k.v', 'meaningful')")
        setup.execute("INSERT INTO meta_info VALUES ('/y.jpg', 'k.v', NULL)")
        setup.execute("INSERT INTO meta_info VALUES ('/z.jpg', 'k.v', '')")
        setup.commit()
        setup.close()
        monkeypatch.setattr(f"{MODULE}.list_setting_db_names", lambda: ["db1"])
        monkeypatch.setattr(f"{MODULE}._open_ro", lambda name: sqlite3.connect(db_file))
        rows = _query_sample_values("k.v", limit=3)
        assert rows[0][2] == "meaningful"
        assert len(rows) == 3
        assert all(v in (None, "") for v in [r[2] for r in rows[1:]])

