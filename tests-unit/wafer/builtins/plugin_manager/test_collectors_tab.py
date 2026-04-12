import os
import tempfile
import pytest
from unittest.mock import patch

from wafer.core.db.setting_db import SettingDB


def _make_dbs(tmp_path, config: dict[str, list[str] | None]):
    paths = {}
    for name, collectors in config.items():
        p = str(tmp_path / f"{name}.db")
        paths[name] = p
        sdb = SettingDB(p)
        if collectors is not None:
            sdb.set_enabled_collectors(collectors)
    return paths


@pytest.fixture
def _patch_paths(tmp_path):
    paths = {}
    db_names = []

    def setup(config: dict[str, list[str] | None]):
        paths.clear()
        paths.update(_make_dbs(tmp_path, config))
        db_names[:] = list(config.keys())

    patcher_names = patch(
        "wafer.builtins.plugin_manager.collectors_tab.list_setting_db_names",
        side_effect=lambda: list(db_names),
    )
    patcher_path = patch(
        "wafer.builtins.plugin_manager.collectors_tab.setting_db_path",
        side_effect=lambda n: paths[n],
    )
    with patcher_names, patcher_path:
        yield setup, paths


class TestCollectorsTab:
    def test_basic_roundtrip(self, qtbot, _patch_paths):
        setup, paths = _patch_paths
        setup({"db1": ["exif", "wd14"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "db1")].isChecked()
        assert tab._matrix[("wd14", "db1")].isChecked()

        tab.save_to_dbs()
        sdb = SettingDB(paths["db1"])
        assert set(sdb.get_enabled_collectors()) == {"exif", "wd14"}

    def test_incremental_discover_preserves_state(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup(
            {
                "default": ["exif"],
                "lora": ["wd14", "exif"],
            }
        )

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=[], detacher_names=[])
        qtbot.addWidget(tab)

        tab.refresh(["wd14"], [])
        assert tab._matrix[("wd14", "lora")].isChecked()
        assert not tab._matrix[("wd14", "default")].isChecked()

        tab.refresh(["wd14", "exif"], [])
        assert tab._matrix[("exif", "default")].isChecked()
        assert tab._matrix[("exif", "lora")].isChecked()
        assert tab._matrix[("wd14", "lora")].isChecked()
        assert not tab._matrix[("wd14", "default")].isChecked()

        per_db = tab.get_per_db_collectors()
        assert per_db == {"default": ["exif"], "lora": ["wd14", "exif"]}

    def test_refresh_preserves_user_changes(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        tab._matrix[("wd14", "db1")].setChecked(True)
        tab.refresh(["exif", "wd14"], [])

        assert tab._matrix[("exif", "db1")].isChecked()
        assert tab._matrix[("wd14", "db1")].isChecked()

    def test_fresh_db_no_enabled(self, qtbot, _patch_paths):
        setup, paths = _patch_paths
        setup({"fresh": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        assert not tab._matrix[("exif", "fresh")].isChecked()

    def test_has_changes_detects_toggle(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert not tab.has_changes()
        tab._matrix[("wd14", "db1")].setChecked(True)
        assert tab.has_changes()

    def test_get_newly_disabled(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif", "wd14"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        tab._matrix[("wd14", "db1")].setChecked(False)
        disabled = tab.get_newly_disabled()
        assert ("db1", "wd14") in disabled

    def test_separate_collector_detacher_groups(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif", "nai"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=["nai"])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "db1")].isChecked()
        assert tab._matrix[("nai", "db1")].isChecked()

        per_db = tab.get_per_db_collectors()
        assert set(per_db["db1"]) == {"exif", "nai"}

    def test_detacher_only(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["nai"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=[], detacher_names=["nai"])
        qtbot.addWidget(tab)

        assert tab._matrix[("nai", "db1")].isChecked()
        assert tab.get_per_db_collectors() == {"db1": ["nai"]}

    def test_none_db_uses_defaults(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"fresh": None})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "fresh")].isChecked()
        assert not tab._matrix[("wd14", "fresh")].isChecked()

    def test_none_db_has_no_changes_without_edit(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"fresh": None})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert not tab.has_changes()

    def test_default_section_initial_state(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert tab._default_checks["exif"].isChecked()
        assert not tab._default_checks["wd14"].isChecked()

    def test_default_section_change_detected(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert not tab.has_changes()
        tab._default_checks["wd14"].setChecked(True)
        assert tab.has_changes()

    def test_get_default_collectors(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], detacher_names=[])
        qtbot.addWidget(tab)

        assert set(tab.get_default_collectors()) == {"exif", "wd14"}
        tab._default_checks["wd14"].setChecked(False)
        assert tab.get_default_collectors() == ["exif"]

    def test_explicit_empty_not_uses_defaults(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        assert not tab._matrix[("exif", "db1")].isChecked()

    def test_toggle_all_via_name_click(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"], "db2": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "db1")].isChecked()
        assert not tab._matrix[("exif", "db2")].isChecked()

        tab._toggle_all("exif")
        assert tab._matrix[("exif", "db1")].isChecked()
        assert tab._matrix[("exif", "db2")].isChecked()

        tab._toggle_all("exif")
        assert not tab._matrix[("exif", "db1")].isChecked()
        assert not tab._matrix[("exif", "db2")].isChecked()

    def test_no_db_shows_defaults_only(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif"], detacher_names=[])
        qtbot.addWidget(tab)

        assert tab._default_checks["exif"].isChecked()
        assert not tab._matrix
