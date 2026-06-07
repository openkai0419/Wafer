import os
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6 import QtCore, QtWidgets
from unittest.mock import MagicMock

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.receivers.collector_receiver import _parse_batch
from wafer.app.viewer.grid.items import GridItemModel
from wafer.app.viewer.search import SearchService
from test_support.scan_harness import ScanHarness


def _create_test_image(path, width=100, height=80, fmt="JPEG"):
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(str(path), format=fmt)


def _process_events_until(predicate, timeout_ms=10000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


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
    for name, w, h, fmt in images:
        _create_test_image(img_dir / name, w, h, fmt)

    collectors = collector_resolver.summary()
    db_path = tmp_path / "test.db"

    with ScanHarness(db_path, collectors=collectors) as harness:
        harness.scan_and_wait(img_dir, expected=len(images))
        assert harness.wait_for(lambda: len(harness.db.get_pending_sources("exiftool")) >= len(images))
        plugin = collector_resolver.registry.get("exiftool")()
        pending = harness.db.get_pending_sources("exiftool")
        if pending:
            paths = [row[0] for row in pending]
            file_info_map = {row[0]: (row[1], row[2]) for row in pending}
            harness.db.mark_dispatched(paths, "exiftool")
            results = []
            for p in paths:
                info = file_info_map.get(p, (0.0, 0))
                r = plugin.process(p, info).to_dict()
                r["collector"] = "exiftool"
                results.append(r)
            _write_results_to_db(harness.db, results)

    return db_path, img_dir


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    from wafer.core.commands.command.state import CommandOptionStore

    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("search_grid") / "cmd.json")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


class TestSearchToGrid:
    def test_search_results_populate_grid_model(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("a.jpg", 200, 100, "JPEG"),
                ("b.png", 64, 64, "PNG"),
                ("c.jpg", 300, 200, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        paths, sources, aspects = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )
        assert len(paths) == 3

        model = GridItemModel()
        model.set_items(paths, sources, aspects)

        assert model.count() == 3
        assert model.paths == paths
        assert model.sources == sources
        assert model.aspect_ratios == aspects
        assert model.selected_count() == 0

    def test_grid_model_selection_after_search(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("x.jpg", 100, 80, "JPEG"),
                ("y.png", 64, 64, "PNG"),
                ("z.jpg", 120, 90, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        paths, sources, aspects = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )

        model = GridItemModel()
        model.set_items(paths, sources, aspects)

        model.set_selected([0, 2])
        assert model.selected_count() == 2
        assert 0 in model.selected_indices()
        assert 2 in model.selected_indices()
        selected_paths = model.selected_paths()
        assert len(selected_paths) == 2

    def test_empty_search_clears_grid(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("a.jpg", 100, 80, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        paths, sources, aspects = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )

        model = GridItemModel()
        model.set_items(paths, sources, aspects)
        assert model.count() == 1

        no_paths, no_sources, no_aspects = engine.search(
            SearchQuery(
                keys="path",
                keywords="nonexistent_file_xyz",
            )
        )
        model.set_items(no_paths, no_sources, no_aspects)
        assert model.count() == 0
        assert model.selected_count() == 0

    def test_search_service_delivers_results(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("alpha.jpg", 200, 100, "JPEG"),
                ("beta.png", 64, 64, "PNG"),
            ],
        )

        received = {}

        def on_finished(paths, sources, aspects):
            received["paths"] = paths
            received["sources"] = sources
            received["aspects"] = aspects

        svc = SearchService(lambda: str(db_path))
        svc.search_finished.connect(on_finished)
        svc.set_keys("path")

        svc.execute(force=True)
        _process_events_until(lambda: "paths" in received, timeout_ms=10000)

        assert "paths" in received
        assert len(received["paths"]) == 2

    def test_search_with_filter_reduces_results(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("keep.jpg", 200, 100, "JPEG"),
                ("drop.jpg", 64, 64, "JPEG"),
            ],
        )

        received = {}

        def on_finished(paths, sources, aspects):
            received["paths"] = paths

        svc = SearchService(lambda: str(db_path))
        svc.search_finished.connect(on_finished)
        svc.set_param("keywords", "keep")
        svc.set_keys("path")

        svc.execute(force=True)
        _process_events_until(lambda: "paths" in received, timeout_ms=10000)

        assert len(received["paths"]) == 1
        assert "keep" in received["paths"][0]

    def test_search_results_to_model_to_path_lookup(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("one.jpg", 100, 80, "JPEG"),
                ("two.png", 64, 64, "PNG"),
                ("three.jpg", 200, 150, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        paths, sources, aspects = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )

        model = GridItemModel()
        model.set_items(paths, sources, aspects)

        for i, p in enumerate(paths):
            assert model.index_of_path(p) == i

        assert model.index_of_path("nonexistent") is None

    def test_aspect_ratios_passed_through(self, tmp_path, qtbot):
        db_path, img_dir = _build_populated_db(
            tmp_path,
            [
                ("wide.jpg", 400, 100, "JPEG"),
                ("square.png", 200, 200, "PNG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        paths, sources, aspects = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )

        model = GridItemModel()
        model.set_items(paths, sources, aspects)

        names = [os.path.basename(p) for p in model.paths]
        sq_idx = names.index("square.png")
        wide_idx = names.index("wide.jpg")

        assert model.aspect_ratios[sq_idx] == 1.0
        assert model.aspect_ratios[wide_idx] == 4.0
