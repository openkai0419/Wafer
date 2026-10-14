from extensions.mapping.feature_bar import FeatureBar
from extensions.mapping.session import FeatureSpec
from wafer.plugin.query.widgets import KeyPickerPopup


def test_add_feature_uses_detected_encoder_and_emits(qtbot):
    bar = FeatureBar(lambda key: "numeric" if key == "modified" else "token_set")
    qtbot.addWidget(bar)
    emitted = []
    bar.features_changed.connect(lambda: emitted.append(1))
    bar.add_feature("modified")
    bar.add_feature("tags")
    assert bar.features() == [FeatureSpec("modified", "numeric"), FeatureSpec("tags", "token_set")]
    assert len(emitted) == 2


def test_duplicate_key_is_ignored(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.add_feature("prompt")
    bar.add_feature("prompt")
    assert len(bar.features()) == 1


def test_chip_edits_update_features(qtbot):
    bar = FeatureBar(lambda key: "token_set")
    qtbot.addWidget(bar)
    bar.set_features([FeatureSpec("tags", "token_set")])
    chip = bar.chips()[0]
    chip.weight_spin.setValue(2.0)
    chip.encoder_combo.setCurrentIndex(chip.encoder_combo.findData("text"))
    assert bar.features() == [FeatureSpec("tags", "text", 2.0, {})]
    chip.remove_button.click()
    assert bar.features() == []


def test_custom_separator_shows_pattern(qtbot):
    bar = FeatureBar(lambda key: "token_set")
    qtbot.addWidget(bar)
    bar.show()
    bar.set_features([FeatureSpec("tags", "token_set")])
    chip = bar.chips()[0]
    combo = chip.option_combos["separator"]
    combo.setCurrentIndex(combo.findData("custom"))
    assert chip.pattern_edit.isVisible()
    chip.pattern_edit.setText(r"\s*/\s*")
    chip.pattern_edit.editingFinished.emit()
    assert bar.features()[0].options == {"separator": "custom", "pattern": r"\s*/\s*"}
    bar.close()


def test_set_features_round_trips_without_emitting(qtbot):
    bar = FeatureBar(lambda key: "token_set")
    qtbot.addWidget(bar)
    emitted = []
    bar.features_changed.connect(lambda: emitted.append(1))
    features = [FeatureSpec("tags", "token_set", 1.5, {"separator": "custom", "pattern": ","}), FeatureSpec("prompt", "text", 0.5)]
    bar.set_features(features)
    assert bar.features() == features
    bar.set_features([])
    assert bar.features() == [] and emitted == []


def test_chip_encoder_choices_are_key_encoders(qtbot):
    bar = FeatureBar(lambda key: "token_set")
    qtbot.addWidget(bar)
    bar.add_feature("tags")
    combo = bar.chips()[0].encoder_combo
    assert [combo.itemData(i) for i in range(combo.count())] == ["numeric", "token_set", "text", "category"]
    assert combo.isEnabled()


def open_picker(bar, qtbot):
    bar.add_button.click()
    popup = bar.key_picker
    qtbot.addWidget(popup)
    return popup


def test_add_button_opens_key_picker_with_palette_extra(qtbot, monkeypatch):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_keys([("color.palette.1", 5), ("path", 9)])
    catalogs = []
    monkeypatch.setattr(KeyPickerPopup, "set_catalog", lambda self, datas, *, extras=(): catalogs.append((list(datas), list(extras))))
    monkeypatch.setattr(KeyPickerPopup, "open_below", lambda self, anchor: None)
    bar.add_button.click()
    datas, extras = catalogs[0]
    assert datas == [("path", 9)]
    assert extras[0][0] == "color.palette"


def test_picker_omits_palette_extra_without_palette_keys(qtbot, monkeypatch):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_keys([("path", 9)])
    catalogs = []
    monkeypatch.setattr(KeyPickerPopup, "set_catalog", lambda self, datas, *, extras=(): catalogs.append(list(extras)))
    monkeypatch.setattr(KeyPickerPopup, "open_below", lambda self, anchor: None)
    bar.add_button.click()
    assert catalogs == [[]]


def test_picked_key_adds_a_feature(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_keys([("color.palette.1", 5), ("path", 9)])
    popup = open_picker(bar, qtbot)
    popup.picked.emit("path")
    popup.picked.emit("color.palette")
    assert bar.features() == [FeatureSpec("path", "text"), FeatureSpec("color.palette", "palette")]


def test_picker_is_reused_and_marks_used_keys(qtbot, monkeypatch):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_keys([("path", 9)])
    bar.add_feature("path")
    used = []
    monkeypatch.setattr(KeyPickerPopup, "set_used", lambda self, keys: used.append(set(keys)))
    first = open_picker(bar, qtbot)
    second = open_picker(bar, qtbot)
    assert first is second and used == [{"path"}, {"path"}]


def test_set_read_only_disables_chips_and_add_button(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_features([FeatureSpec("tags", "token_set")])
    bar.set_read_only(True)
    assert not bar.add_button.isEnabled() and not bar.chips()[0].isEnabled()
    bar.set_read_only(False)
    assert bar.add_button.isEnabled() and bar.chips()[0].isEnabled()


def test_palette_key_uses_palette_encoder_without_detect(qtbot):
    def fail(key):
        raise AssertionError("detect must not be called")

    bar = FeatureBar(fail)
    qtbot.addWidget(bar)
    bar.add_feature("color.palette")
    assert bar.features() == [FeatureSpec("color.palette", "palette")]
    chip = bar.chips()[0]
    assert chip.encoder_combo.count() == 1 and not chip.encoder_combo.isEnabled()


def test_regular_chip_excludes_key_group_encoders(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.add_feature("prompt")
    combo = bar.chips()[0].encoder_combo
    assert combo.findData("palette") == -1 and combo.isEnabled()


def test_read_only_applies_to_chips_added_later(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_read_only(True)
    bar.set_features([FeatureSpec("tags", "token_set")])
    bar.insert_chip(FeatureSpec("prompt", "text"))
    assert [chip.isEnabled() for chip in bar.chips()] == [False, False]
    bar.set_read_only(False)
    assert [chip.isEnabled() for chip in bar.chips()] == [True, True]
    bar.add_feature("path")
    assert bar.chips()[-1].isEnabled()
