import os
import tempfile
import pytest
from unittest.mock import patch

from PySide6 import QtWidgets

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

        tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
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

        tab = CollectorsTab(collector_names=[], parser_names=[])
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

        tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        tab._matrix[("wd14", "db1")].setChecked(True)
        tab.refresh(["exif", "wd14"], [])

        assert tab._matrix[("exif", "db1")].isChecked()
        assert tab._matrix[("wd14", "db1")].isChecked()

    def test_same_heavy_extension_does_not_warn_twice(self, qtbot, _patch_paths, monkeypatch):
        setup, _ = _patch_paths
        setup({"db1": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(
            collector_names=["tag_a", "tag_b", "tag_c"],
            parser_names=[],
            heavy_collectors={"tag_a": "wd14", "tag_b": "wd14", "tag_c": "florence"},
        )
        qtbot.addWidget(tab)

        warnings = []
        monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

        tab._matrix[("tag_a", "db1")].setChecked(True)
        tab._matrix[("tag_b", "db1")].setChecked(True)
        assert warnings == []

        tab._matrix[("tag_c", "db1")].setChecked(True)
        assert len(warnings) == 1
        assert "wd14" in warnings[0]
        assert "florence" in warnings[0]

    def test_fresh_db_no_enabled(self, qtbot, _patch_paths):
        setup, paths = _patch_paths
        setup({"fresh": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], parser_names=[])
        qtbot.addWidget(tab)

        assert not tab._matrix[("exif", "fresh")].isChecked()

    def test_has_changes_detects_toggle(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert not tab.has_changes()
        tab._matrix[("wd14", "db1")].setChecked(True)
        assert tab.has_changes()

    def test_get_newly_disabled(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif", "wd14"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        tab._matrix[("wd14", "db1")].setChecked(False)
        disabled = tab.get_newly_disabled()
        assert ("db1", "wd14") in disabled

    def test_separate_collector_parser_groups(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif", "nai"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], parser_names=["nai"])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "db1")].isChecked()
        assert tab._matrix[("nai", "db1")].isChecked()

        per_db = tab.get_per_db_collectors()
        assert set(per_db["db1"]) == {"exif", "nai"}

    def test_parser_only(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["nai"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=[], parser_names=["nai"])
        qtbot.addWidget(tab)

        assert tab._matrix[("nai", "db1")].isChecked()
        assert tab.get_per_db_collectors() == {"db1": ["nai"]}

    def test_none_db_uses_defaults(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"fresh": None})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert tab._matrix[("exif", "fresh")].isChecked()
        assert not tab._matrix[("wd14", "fresh")].isChecked()

    def test_none_db_has_no_changes_without_edit(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"fresh": None})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert not tab.has_changes()

    def test_default_section_initial_state(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert tab._default_checks["exif"].isChecked()
        assert not tab._default_checks["wd14"].isChecked()

    def test_default_section_change_detected(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert not tab.has_changes()
        tab._default_checks["wd14"].setChecked(True)
        assert tab.has_changes()

    def test_get_default_collectors(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert set(tab.get_default_collectors()) == {"exif", "wd14"}
        tab._default_checks["wd14"].setChecked(False)
        assert tab.get_default_collectors() == ["exif"]

    def test_explicit_empty_not_uses_defaults(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif"], parser_names=[])
        qtbot.addWidget(tab)

        assert not tab._matrix[("exif", "db1")].isChecked()

    def test_toggle_all_via_name_click(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"], "db2": []})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=["exif"], parser_names=[])
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
            tab = CollectorsTab(collector_names=["exif"], parser_names=[])
        qtbot.addWidget(tab)

        assert tab._default_checks["exif"].isChecked()
        assert not tab._matrix

    def test_refresh_restores_defaults_after_async_init(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab = CollectorsTab(collector_names=[], parser_names=[])
        qtbot.addWidget(tab)

        assert tab._initial_defaults == set()

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab.refresh(["exif", "wd14"], [])

        assert tab._default_checks["exif"].isChecked()
        assert tab._default_checks["wd14"].isChecked()

    def test_incremental_refresh_preserves_defaults(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab = CollectorsTab(collector_names=[], parser_names=[])
        qtbot.addWidget(tab)

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab.refresh(["exif"], [])

        assert tab._default_checks["exif"].isChecked()

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif", "wd14"}):
            tab.refresh(["exif", "wd14"], [])

        assert tab._default_checks["exif"].isChecked()
        assert tab._default_checks["wd14"].isChecked()

    def test_refresh_preserves_default_checkbox_changes(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exif"]})

        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        with patch.object(CollectorsTab, "_load_defaults", return_value={"exif"}):
            tab = CollectorsTab(collector_names=["exif", "wd14"], parser_names=[])
        qtbot.addWidget(tab)

        assert tab._default_checks["exif"].isChecked()
        assert not tab._default_checks["wd14"].isChecked()

        tab._default_checks["wd14"].setChecked(True)
        tab.refresh(["exif", "wd14"], [])

        assert tab._default_checks["exif"].isChecked()
        assert tab._default_checks["wd14"].isChecked()


class TestParserRequirement:
    def _tab(self, qtbot, collector_names, parser_names):
        from wafer.builtins.plugin_manager.collectors_tab import CollectorsTab

        tab = CollectorsTab(collector_names=collector_names, parser_names=parser_names)
        qtbot.addWidget(tab)
        return tab

    def test_enable_prompts_and_autoenables_collector(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})
        tab = self._tab(qtbot, ["exiftool"], ["novelai"])

        with patch("wafer.plugin.parser.handler.parser_resolver.required_collectors", return_value={"exiftool": ["PNG:Comment"]}), patch.object(
            QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes
        ) as question:
            tab._matrix[("novelai", "db1")].setChecked(True)

        question.assert_called_once()
        assert tab._matrix[("exiftool", "db1")].isChecked()

    def test_enable_no_keeps_collector_disabled(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})
        tab = self._tab(qtbot, ["exiftool"], ["novelai"])

        with patch("wafer.plugin.parser.handler.parser_resolver.required_collectors", return_value={"exiftool": ["PNG:Comment"]}), patch.object(
            QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No
        ):
            tab._matrix[("novelai", "db1")].setChecked(True)

        assert not tab._matrix[("exiftool", "db1")].isChecked()
        assert tab._matrix[("novelai", "db1")].isChecked()

    def test_no_prompt_when_requirement_satisfied(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": ["exiftool"]})
        tab = self._tab(qtbot, ["exiftool"], ["novelai"])

        with patch("wafer.plugin.parser.handler.parser_resolver.required_collectors", return_value={"exiftool": ["PNG:Comment"]}), patch.object(
            QtWidgets.QMessageBox, "question"
        ) as question:
            tab._matrix[("novelai", "db1")].setChecked(True)

        question.assert_not_called()

    def test_missing_collector_warns_only(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})
        tab = self._tab(qtbot, ["exiftool"], ["novelai"])

        with patch("wafer.plugin.parser.handler.parser_resolver.required_collectors", return_value={"ffmpeg": ["Duration"]}), patch.object(
            QtWidgets.QMessageBox, "warning"
        ) as warning, patch.object(QtWidgets.QMessageBox, "question") as question:
            tab._matrix[("novelai", "db1")].setChecked(True)

        warning.assert_called_once()
        question.assert_not_called()
        assert "Do you want to enable the collector?" not in warning.call_args.args[2]

    def test_available_collector_prompts_without_missing_extensions(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})
        tab = self._tab(qtbot, ["exiftool"], ["novelai"])

        with patch(
            "wafer.plugin.parser.handler.parser_resolver.required_collectors",
            return_value={"exiftool": ["PNG:Comment"], "ffmpeg": ["Duration"]},
        ), patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No) as question:
            tab._matrix[("novelai", "db1")].setChecked(True)

        question.assert_called_once()
        text = question.call_args.args[2]
        assert "Do you want to enable the collector?" in text
        assert "Enable these extensions first:" not in text
        assert "ffmpeg" not in text

    def test_no_prompt_when_parser_has_no_requirements(self, qtbot, _patch_paths):
        setup, _ = _patch_paths
        setup({"db1": []})
        tab = self._tab(qtbot, ["exiftool"], ["plain"])

        with patch("wafer.plugin.parser.handler.parser_resolver.required_collectors", return_value={}), patch.object(
            QtWidgets.QMessageBox, "question"
        ) as question, patch.object(QtWidgets.QMessageBox, "warning") as warning:
            tab._matrix[("plain", "db1")].setChecked(True)

        question.assert_not_called()
        warning.assert_not_called()

