from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from wafer.core.lang.manager import t
from wafer.qt.commands.bridge import ActionKit, Menu
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets import FlowLayout

from .encoders import ENCODERS
from .session import FeatureSpec

MAX_MENU_KEYS = 100
WEIGHT_PREFIX = "\N{MULTIPLICATION SIGN}"


class FeatureChip(QtWidgets.QFrame):
    changed = QtCore.Signal()
    removed = QtCore.Signal(object)

    def __init__(self, spec: FeatureSpec, parent=None):
        super().__init__(parent)
        self.key = spec.key
        palette = ThemeManager.instance().palette
        self.setObjectName("FeatureChip")
        self.setStyleSheet(f"#FeatureChip {{ border: 1px solid {palette.border_default}; border-radius: {dpix(4)}px; }}")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(2), dpix(2), dpix(2))
        layout.setSpacing(dpix(4))
        layout.addWidget(QtWidgets.QLabel(spec.key))
        self.encoder_combo = QtWidgets.QComboBox()
        key_group = ENCODERS[spec.encoder].KEY_GROUP
        for cls in ENCODERS.values():
            if key_group == cls.KEY_GROUP:
                self.encoder_combo.addItem(t(cls.DISPLAY_NAME), cls.NAME)
                self.encoder_combo.setItemData(self.encoder_combo.count() - 1, t(cls.DESCRIPTION), QtCore.Qt.ToolTipRole)
        self.encoder_combo.setCurrentIndex(self.encoder_combo.findData(spec.encoder))
        self.encoder_combo.setEnabled(self.encoder_combo.count() > 1)
        self.encoder_combo.currentIndexChanged.connect(self.on_encoder_changed)
        layout.addWidget(self.encoder_combo)
        self.options_box = QtWidgets.QHBoxLayout()
        self.options_box.setSpacing(dpix(4))
        layout.addLayout(self.options_box)
        self.option_combos: dict[str, QtWidgets.QComboBox] = {}
        self.pattern_edit = QtWidgets.QLineEdit()
        self.pattern_edit.setPlaceholderText(t("Regex"))
        self.pattern_edit.editingFinished.connect(self.changed.emit)
        self.weight_spin = QtWidgets.QDoubleSpinBox()
        self.weight_spin.setRange(0.0, 3.0)
        self.weight_spin.setSingleStep(0.1)
        self.weight_spin.setValue(spec.weight)
        self.weight_spin.setPrefix(WEIGHT_PREFIX)
        self.weight_spin.setToolTip(t("How much this key counts."))
        self.weight_spin.valueChanged.connect(lambda _value: self.changed.emit())
        layout.addWidget(self.weight_spin)
        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setIcon(themed_icon("cross"))
        self.remove_button.setAutoRaise(True)
        self.remove_button.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.remove_button)
        self.build_options(spec.options)

    def build_options(self, values: dict[str, str]):
        while self.options_box.count():
            widget = self.options_box.takeAt(0).widget()
            if widget is not None and widget is not self.pattern_edit:
                widget.hide()
                widget.deleteLater()
        self.option_combos.clear()
        for option in ENCODERS[self.encoder_combo.currentData()].OPTIONS:
            if not option.choices:
                continue
            combo = QtWidgets.QComboBox()
            for value, label in option.choices:
                combo.addItem(t(label), value)
            combo.setCurrentIndex(max(0, combo.findData(values.get(option.name, option.default))))
            combo.setToolTip(t(option.description))
            combo.currentIndexChanged.connect(self.on_option_changed)
            self.options_box.addWidget(combo)
            self.option_combos[option.name] = combo
        self.pattern_edit.setText(values.get("pattern", ""))
        self.options_box.addWidget(self.pattern_edit)
        self.sync_pattern_visibility()

    def sync_pattern_visibility(self):
        combo = self.option_combos.get("separator")
        self.pattern_edit.setVisible(combo is not None and combo.currentData() == "custom")

    def on_encoder_changed(self):
        self.build_options({})
        self.changed.emit()

    def on_option_changed(self):
        self.sync_pattern_visibility()
        self.changed.emit()

    def option_default(self, name: str) -> str:
        return next(option.default for option in ENCODERS[self.encoder_combo.currentData()].OPTIONS if option.name == name)

    def spec(self) -> FeatureSpec:
        options = {name: combo.currentData() for name, combo in self.option_combos.items() if combo.currentData() != self.option_default(name)}
        if self.pattern_edit.isVisibleTo(self) and self.pattern_edit.text():
            options["pattern"] = self.pattern_edit.text()
        return FeatureSpec(self.key, self.encoder_combo.currentData(), round(self.weight_spin.value(), 2), options)


class FeatureBar(QtWidgets.QWidget):
    features_changed = QtCore.Signal()

    def __init__(self, detect: Callable[[str], str], parent=None):
        super().__init__(parent)
        self.detect = detect
        self.keys: list[tuple[str, int]] = []
        self.feature_chips: list[FeatureChip] = []
        self.flow = FlowLayout(self)
        self.add_button = QtWidgets.QToolButton()
        self.add_button.setIcon(themed_icon("plus"))
        self.add_button.setToolTip(t("Add a key"))
        self.add_button.clicked.connect(self.show_add_menu)
        self.flow.addWidget(self.add_button)

    def chips(self) -> list[FeatureChip]:
        return list(self.feature_chips)

    def features(self) -> list[FeatureSpec]:
        return [chip.spec() for chip in self.feature_chips]

    def set_keys(self, counts: list[tuple[str, int]]):
        self.keys = counts

    def set_features(self, features: list[FeatureSpec]):
        for chip in self.feature_chips:
            self.discard_chip(chip)
        self.feature_chips = []
        for spec in features:
            self.insert_chip(spec)

    def add_feature(self, key: str):
        if any(chip.key == key for chip in self.feature_chips):
            return
        self.insert_chip(FeatureSpec(key, self.detect(key)))
        self.features_changed.emit()

    def insert_chip(self, spec: FeatureSpec):
        chip = FeatureChip(spec, self)
        chip.changed.connect(self.features_changed.emit)
        chip.removed.connect(self.remove_chip)
        self.flow.removeWidget(self.add_button)
        self.flow.addWidget(chip)
        self.flow.addWidget(self.add_button)
        chip.show()
        self.feature_chips.append(chip)

    def discard_chip(self, chip: FeatureChip):
        self.flow.removeWidget(chip)
        chip.hide()
        chip.deleteLater()

    def remove_chip(self, chip: FeatureChip):
        self.feature_chips.remove(chip)
        self.discard_chip(chip)
        self.features_changed.emit()

    def show_add_menu(self):
        used = {chip.key for chip in self.feature_chips}
        items = [":" + t("Keys")]
        for key, count in [entry for entry in self.keys if entry[0] not in used][:MAX_MENU_KEYS]:
            items.append(ActionKit.Action(path=f"inline.mapping.add_key.{len(items)}", display=f"{key}  ({count})", translate=False, func=lambda ctx, k=key: self.add_feature(k)))
        pos = self.add_button.mapToGlobal(QtCore.QPoint(0, self.add_button.height()))
        spec = Menu.session(self, pos=pos).menu(items)
        if spec is not None:
            spec.exec()
