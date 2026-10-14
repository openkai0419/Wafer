from extensions.mapping.feature_bar import FeatureBar
from extensions.mapping.session import FeatureSpec


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


def test_add_menu_lists_unused_keys_and_adds_on_pick(qtbot, monkeypatch):
    from extensions.mapping import feature_bar

    shown = []

    class FakeSpec:
        def __init__(self, items):
            self.items = items

        def exec(self):
            shown.append(self.items)

    class FakeSession:
        def menu(self, items):
            return FakeSpec(items)

    monkeypatch.setattr(feature_bar.Menu, "session", lambda parent, pos=None: FakeSession())
    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    bar.set_keys([("prompt", 12), ("tags", 7)])
    bar.add_feature("prompt")
    bar.add_button.click()
    items = shown[0]
    actions = [item for item in items if not isinstance(item, str)]
    assert [action.display for action in actions] == ["tags  (7)"]
    actions[0].func(None)
    assert [spec.key for spec in bar.features()] == ["prompt", "tags"]


def test_add_menu_builds_with_real_menu_session(qtbot):
    from wafer.qt.commands.bridge import ActionKit, Menu

    bar = FeatureBar(lambda key: "text")
    qtbot.addWidget(bar)
    items = [":Keys", ActionKit.Action(path="inline.mapping.add_key.1", display="tags  (7)", translate=False, func=lambda ctx: None)]
    assert Menu.session(bar).menu(items).build() is not None


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
