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
    assert [combo.itemData(i) for i in range(combo.count())] == ["numeric", "token_set", "path", "text", "category"]
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


def test_set_encoder_updates_the_matching_chip_and_emits(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_features([FeatureSpec("score", "text"), FeatureSpec("tags", "text")])
    emitted = []
    bar.features_changed.connect(lambda: emitted.append(1))
    bar.set_encoder("score", "numeric")
    bar.set_encoder("missing", "numeric")
    assert bar.features() == [FeatureSpec("score", "numeric"), FeatureSpec("tags", "text")]
    assert emitted == [1]


def test_number_options_appear_on_the_chip_and_only_changes_are_saved(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.add_feature("prompt")
    chip = bar.chips()[0]
    assert set(chip.option_spins) == {"min_chars", "max_chars", "summary"}
    assert bar.features()[0].options == {}
    chip.option_spins["max_chars"].setValue(8)
    chip.option_spins["summary"].setValue(120)
    assert bar.features()[0].options == {"max_chars": "8", "summary": "120"}
    bar.set_features([FeatureSpec("prompt", "text", 1.0, {"min_chars": "3"})])
    assert bar.chips()[0].option_spins["min_chars"].value() == 3


def test_switching_encoder_rebuilds_number_options(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.add_feature("prompt")
    chip = bar.chips()[0]
    chip.set_encoder("numeric")
    assert chip.option_spins == {}
    chip.set_encoder("token_set")
    assert set(chip.option_spins) == {"summary"}


def test_a_wide_key_wraps_to_fit_a_narrow_panel(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_features([FeatureSpec("novelai.prompt", "text")])
    chip = bar.chips()[0]
    natural = chip.sizeHint().width()
    assert bar.minimumSizeHint().width() < natural // 2
    assert bar.heightForWidth(natural // 2) > bar.heightForWidth(natural * 2)
    bar.resize(natural // 2, bar.heightForWidth(natural // 2))
    bar.show()
    qtbot.waitUntil(lambda: chip.width() <= natural // 2)
    assert chip.remove_button.geometry().right() <= chip.width()
    bar.close()


def test_option_order_survives_an_encoder_switch(qtbot):
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.add_feature("prompt")
    chip = bar.chips()[0]
    chip.set_encoder("token_set")
    layout = chip.layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert order[-2:] == [chip.weight_spin, chip.remove_button]
    assert order.index(chip.option_combos["separator"]) > order.index(chip.encoder_combo)


def test_unreadable_number_option_falls_back_to_the_default_and_is_logged(qtbot, monkeypatch):
    from extensions.mapping import encoders

    warnings = []
    monkeypatch.setattr(encoders.AppLogger, "warning", lambda message, exc=None: warnings.append(message))
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_features([FeatureSpec("prompt", "text", 1.0, {"min_chars": "x", "max_chars": "99"})])
    spins = bar.chips()[0].option_spins
    assert spins["min_chars"].value() == 2 and spins["max_chars"].value() == 12
    assert len(warnings) == 1 and "min_chars" in warnings[0]
