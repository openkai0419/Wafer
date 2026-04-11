import time

import pytest
from PIL import Image
from PySide6 import QtCore, QtWidgets
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unstable

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.indexer import FileIndexer
from wafer.core.db.setting_db import SettingDB
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.collector_receiver import _parse_batch


def _create_test_image(path, width=200, height=150, fmt="JPEG"):
    Image.new("RGB", (width, height), color=(100, 150, 200)).save(str(path), format=fmt)


def _write_results_to_db(db, results):
    data = _parse_batch(results)
    db.upsert_collection_results(
        data["image_entries"],
        data["meta_info_entries"],
        data["tag_entries"],
        data["collector_status"],
    )


def _build_populated_db(tmp_path, images):
    img_dir = tmp_path / "photos"
    img_dir.mkdir(exist_ok=True)
    for name, w, h in images:
        _create_test_image(img_dir / name, w, h)

    collectors = collector_resolver.summary()
    db_path = tmp_path / "data" / "smoketest.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with FileIndexer(str(db_path), collectors=collectors) as idx:
        idx.initialize()
        idx.update_index(str(img_dir))

        plugin = collector_resolver.registry.get("exiftool")()
        pending = idx.db.get_pending_sources("exiftool")
        if pending:
            paths = [row[0] for row in pending]
            file_info_map = {row[0]: (row[1], row[2]) for row in pending}
            idx.db.mark_dispatched(paths, "exiftool")
            results = []
            for p in paths:
                info = file_info_map.get(p, (0.0, 0))
                r = plugin.process(p, info).to_dict()
                r["collector"] = "exiftool"
                results.append(r)
            _write_results_to_db(idx.db, results)

    return str(db_path), str(img_dir)


def _process_events_until(predicate, timeout_ms=15000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


@pytest.fixture(autouse=True, scope="module")
def _disable_mpv():
    try:
        from extensions.video.widget import MpvGLOverlay

        orig = MpvGLOverlay._mpv, MpvGLOverlay._proc_addr_cb, MpvGLOverlay._init_attempted
        MpvGLOverlay._init_attempted = True
        MpvGLOverlay._mpv = None
        MpvGLOverlay._proc_addr_cb = None
        yield
        MpvGLOverlay._mpv, MpvGLOverlay._proc_addr_cb, MpvGLOverlay._init_attempted = orig
    except ImportError:
        yield


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    from wafer.core.commands.command.state import CommandOptionStore

    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("smoke_viewer") / "cmd.json")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


@pytest.fixture()
def smoke_env(tmp_path):
    images = [
        ("alpha.jpg", 300, 200),
        ("beta.png", 100, 100),
        ("gamma.jpg", 400, 300),
    ]
    db_path, img_dir = _build_populated_db(tmp_path, images)

    setting_db_path = str(tmp_path / "dirs" / "smoketest.db")
    (tmp_path / "dirs").mkdir(parents=True, exist_ok=True)
    sdb = SettingDB(setting_db_path)
    sdb.add_parent_folder(img_dir)

    return db_path, setting_db_path, img_dir


class _StubNode:
    def __init__(self):
        self.profile_id = ""

    def subscribe(self, *a, **kw):
        return self

    def start(self, *a, **kw):
        pass

    def stop(self):
        pass

    def send(self, *a, **kw):
        pass

    def send_coalesced(self, *a, **kw):
        pass


class TestSmokeViewer:
    def test_mainwindow_boots_and_searches(self, smoke_env, qtbot, tmp_path):
        db_path, setting_db_path, img_dir = smoke_env

        from wafer.core.profile import ProfileStore

        prev_instance = ProfileStore._instance
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        ProfileStore._instance = store

        stub_node = _StubNode()

        try:
            with patch("wafer.app.viewer.mainwindow.Node", return_value=stub_node):
                with patch("wafer.utils.logs.AppLogger.set_node"):
                    from wafer.app.viewer.mainwindow import MainWindow

                    win = MainWindow(icon=None, profile_id=None)
                    qtbot.addWidget(win)
                    win.show()

                    win.database_path = db_path
                    win.database_name = "smoketest"
                    win.setting_db = SettingDB(setting_db_path)
                    win.folder_view.set_folders(
                        win.setting_db.get_all_parent_folders(),
                        win.setting_db.get_all_ignore_folders(),
                    )

                    from wafer.core.db.query import FileSearchEngine
                    from wafer.plugin.query.composer import SearchComposer

                    engine = FileSearchEngine(db_path)
                    keys = SearchComposer().list_all_keys(engine, [])
                    win.search_row_widget._key_store.set_data(keys)
                    QtWidgets.QApplication.instance().processEvents()

                    win.search_service.reset_state()
                    win.search(force=True)

                    search_done = {}
                    orig_finished = win._on_search_finished

                    def _intercept(paths, sources, aspects):
                        search_done["paths"] = paths
                        orig_finished(paths, sources, aspects)

                    win.search_service.search_finished.connect(_intercept)

                    _process_events_until(lambda: len(search_done.get("paths", [])) == 3)
                    assert len(search_done["paths"]) == 3

                    assert win.grid_view is not None
                    assert win.file_viewer is not None
                    assert win.folder_view is not None

                    win.close()
                    QtWidgets.QApplication.instance().processEvents()
        finally:
            ProfileStore._instance = prev_instance

    def test_mainwindow_handles_empty_db(self, qtbot, tmp_path):
        from wafer.core.db.indexer import FileIndexer

        db_path = str(tmp_path / "data" / "empty.db")
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        collectors = collector_resolver.summary()
        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()

        from wafer.core.profile import ProfileStore

        prev_instance = ProfileStore._instance
        store = ProfileStore(path=str(tmp_path / "profiles.json"))
        ProfileStore._instance = store

        stub_node = _StubNode()

        try:
            with patch("wafer.app.viewer.mainwindow.Node", return_value=stub_node):
                with patch("wafer.utils.logs.AppLogger.set_node"):
                    from wafer.app.viewer.mainwindow import MainWindow

                    win = MainWindow(icon=None, profile_id=None)
                    qtbot.addWidget(win)

                    win.database_path = db_path
                    win.database_name = "empty"
                    win.search_service.reset_state()
                    win.search(force=True)

                    search_done = {}

                    def _intercept(paths, sources, aspects):
                        search_done["result"] = (paths, sources, aspects)

                    win.search_service.search_finished.connect(_intercept)
                    _process_events_until(lambda: "result" in search_done)

                    paths, sources, aspects = search_done["result"]
                    assert len(paths) == 0

                    win.close()
                    QtWidgets.QApplication.instance().processEvents()
        finally:
            ProfileStore._instance = prev_instance
