import shutil

import pytest

from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.runtime.progress_aggregator import ProgressAggregator
from wafer.app.indexer.runtime.scheduler import TaskScheduler
from wafer.app.indexer.scanner import DirectoryScanner
from wafer.app.indexer.watch import folder_watcher as folder_watcher_module
from wafer.app.indexer.watch.folder_watcher import FolderWatcher
from wafer.app.viewer.ipc_bridge import UPDATE_TOPICS, ViewerIpcBridge
from wafer.builtins.folder_manager import widget as widget_module
from wafer.builtins.folder_manager.database import FolderSettings
from wafer.builtins.folder_manager.stats import FolderValues
from wafer.builtins.folder_manager.widget import FolderManagerWidget
from wafer.core.common.paths import normalize_path
from wafer.core.ipc.message import Message
from wafer.plugin.collector.handler import collector_resolver


class LoopbackNode:
    def __init__(self, role):
        self.role = role
        self.handlers = {}

    def subscribe(self, topic, handler):
        self.handlers[topic] = handler
        return self

    def send(self, topic, payload=None, *, dst="ALL", db=""):
        handler = self.handlers.get(topic)
        if handler is not None and dst in ("ALL", self.role):
            handler(Message.build(topic, payload, dst=dst, db=db))

    send_coalesced = send


@pytest.fixture(autouse=True)
def fast_watch_timing(monkeypatch):
    monkeypatch.setattr(folder_watcher_module, "_BATCH_TIMEOUT", 0.1)
    monkeypatch.setattr(folder_watcher_module, "_MOVE_INFER_WINDOW", 0.3)


@pytest.fixture
def watched_panel(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "watched"
    for folder, files in {"a/moving": 2, "b": 1}.items():
        (root / folder).mkdir(parents=True)
        for number in range(files):
            (root / folder / f"f{number}.png").write_bytes(b"x")
    norm_root = normalize_path(str(root))
    node = LoopbackNode("tray")
    bridge = ViewerIpcBridge.for_updates(node)
    monkeypatch.setattr(widget_module, "read_folder_settings", lambda name: FolderSettings([norm_root], set(), None))
    monkeypatch.setattr(widget_module, "query_sources", lambda db_path, entries: [])
    progress = ProgressAggregator("test", node)
    db_path = tmp_path / "test.db"
    writer = DatabaseWriter(db_path)
    writer.start()
    writer.initialize()
    scheduler = TaskScheduler()
    scanner = DirectoryScanner(db_path, scheduler, writer, progress, collector_resolver.summary())
    watcher = FolderWatcher(scheduler, writer, scanner, progress)
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)
    panel.set_database("test")
    qtbot.waitUntil(lambda: panel.model.disk is not None and panel.model.disk.finished and not panel.scanning, timeout=5000)
    scheduler.start()
    scanner.start()
    watcher.start([str(root)])
    try:
        yield panel, root, norm_root
    finally:
        watcher.stop()
        scanner.stop()
        scheduler.stop()
        writer.close()
        bridge.stop_updates()


def test_the_tray_panel_follows_folders_moved_and_files_added_on_disk(qtbot, watched_panel):
    panel, root, norm = watched_panel
    disk = panel.model.disk
    assert disk.values(f"{norm}/b") == FolderValues(1, 1, 0, 0)

    shutil.move(str(root / "a" / "moving"), str(root / "b" / "moving"))
    (root / "b" / "new.png").write_bytes(b"x")

    def followed():
        return disk.values(f"{norm}/b") == FolderValues(2, 4, 1, 1) and disk.values(f"{norm}/a") == FolderValues(0, 0, 0, 0) and not panel.scanning

    qtbot.waitUntil(followed, timeout=15000)
    assert panel.model.disk is disk
    assert disk.values(f"{norm}/b/moving") == FolderValues(2, 2, 0, 0)
