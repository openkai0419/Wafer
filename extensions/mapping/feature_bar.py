from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets

from wafer.core.lang.manager import t
from wafer.plugin.query.widgets import KeyPickerPopup
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets import FlowLayout

from .encoders import ENCODERS, PALETTE_KEY, OptionSpec
from .session import FeatureSpec

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
        self.flow = FlowLayout(self, spacing=dpix(4))
        self.flow.setContentsMargins(dpix(6), dpix(2), dpix(2), dpix(2))
        self.flow.addWidget(QtWidgets.QLabel(spec.key))
        self.encoder_combo = QtWidgets.QComboBox()
        key_group = ENCODERS[spec.encoder].KEY_GROUP
        for cls in ENCODERS.values():
            if key_group == cls.KEY_GROUP:
                self.encoder_combo.addItem(t(cls.DISPLAY_NAME), cls.NAME)
                self.encoder_combo.setItemData(self.encoder_combo.count() - 1, t(cls.DESCRIPTION), QtCore.Qt.ToolTipRole)
        self.encoder_combo.setCurrentIndex(self.encoder_combo.findData(spec.encoder))
        self.encoder_combo.setEnabled(self.encoder_combo.count() > 1)
        self.encoder_combo.currentIndexChanged.connect(self.on_encoder_changed)
        self.flow.addWidget(self.encoder_combo)
        self.option_widgets: list[QtWidgets.QWidget] = []
        self.option_combos: dict[str, QtWidgets.QComboBox] = {}
        self.option_spins: dict[str, QtWidgets.QSpinBox] = {}
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
        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setIcon(themed_icon("cross"))
        self.remove_button.setAutoRaise(True)
        self.remove_button.clicked.connect(lambda: self.removed.emit(self))
        for widget in (self.pattern_edit, self.weight_spin, self.remove_button):
            self.flow.addWidget(widget)
        self.build_options(spec.options)

    def sizeHint(self):
        return self.flow.single_line_size()

    def build_options(self, values: dict[str, str]):
        for widget in self.option_widgets:
            self.flow.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self.option_widgets.clear()
        self.option_combos.clear()
        self.option_spins.clear()
        for option in ENCODERS[self.encoder_combo.currentData()].OPTIONS:
            if option.numeric:
                self.add_number_option(option, values)
                continue
            if not option.choices:
                continue
            combo = QtWidgets.QComboBox()
            for value, label in option.choices:
                combo.addItem(t(label), value)
            combo.setCurrentIndex(max(0, combo.findData(values.get(option.name, option.default))))
            combo.setToolTip(t(option.description))
            combo.currentIndexChanged.connect(self.on_option_changed)
            self.add_option_widget(combo)
            self.option_combos[option.name] = combo
        self.pattern_edit.setText(values.get("pattern", ""))
        self.sync_pattern_visibility()
        self.updateGeometry()

    def add_option_widget(self, widget: QtWidgets.QWidget) -> None:
        self.flow.insertWidget(self.flow.indexOf(self.pattern_edit), widget)
        self.option_widgets.append(widget)

    def add_number_option(self, option: OptionSpec, values: dict[str, str]) -> None:
        spin = QtWidgets.QSpinBox()
        spin.setRange(option.minimum, option.maximum)
        spin.setPrefix(f"{t(option.label)} ")
        try:
            spin.setValue(int(values.get(option.name, option.default)))
        except ValueError:
            spin.setValue(int(option.default))
        spin.setToolTip(t(option.description))
        spin.valueChanged.connect(lambda _value: self.changed.emit())
        self.add_option_widget(spin)
        self.option_spins[option.name] = spin

    def sync_pattern_visibility(self):
        combo = self.option_combos.get("separator")
        self.pattern_edit.setVisible(combo is not None and combo.currentData() == "custom")

    def on_encoder_changed(self):
        self.build_options({})
        self.changed.emit()

    def on_option_changed(self):
        self.sync_pattern_visibility()
        self.changed.emit()

    def set_encoder(self, name: str) -> None:
        index = self.encoder_combo.findData(name)
        if index >= 0:
            self.encoder_combo.setCurrentIndex(index)

    def option_default(self, name: str) -> str:
        return next(option.default for option in ENCODERS[self.encoder_combo.currentData()].OPTIONS if option.name == name)

    def spec(self) -> FeatureSpec:
        options = {name: combo.currentData() for name, combo in self.option_combos.items() if combo.currentData() != self.option_default(name)}
        options.update({name: str(spin.value()) for name, spin in self.option_spins.items() if str(spin.value()) != self.option_default(name)})
        if self.pattern_edit.isVisibleTo(self) and self.pattern_edit.text():
            options["pattern"] = self.pattern_edit.text()
        return FeatureSpec(self.key, self.encoder_combo.currentData(), round(self.weight_spin.value(), 2), options)


class FeatureBar(QtWidgets.QWidget):
    features_changed = QtCore.Signal()

    def __init__(self, detect: Callable[[str], str], parent=None):
        super().__init__(parent)
        self.detect = detect
        self.keys: list[tuple[str, int]] = []
        self.key_picker: KeyPickerPopup | None = None
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
        self.insert_chip(FeatureSpec(key, "palette" if key == PALETTE_KEY else self.detect(key)))
        self.features_changed.emit()

    def set_encoder(self, key: str, encoder: str):
        for chip in self.feature_chips:
            if chip.key == key:
                chip.set_encoder(encoder)

    def insert_chip(self, spec: FeatureSpec):
        chip = FeatureChip(spec, self)
        chip.changed.connect(self.features_changed.emit)
        chip.removed.connect(self.remove_chip)
        self.flow.insertWidget(self.flow.indexOf(self.add_button), chip)
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
        popup = self.picker()
        used = {chip.key for chip in self.feature_chips}
        has_palette = any(key.startswith(PALETTE_KEY + ".") for key, _ in self.keys)
        extras = [(PALETTE_KEY, t("[Color] Palette"))] if has_palette and PALETTE_KEY not in used else []
        popup.set_catalog([(key, count) for key, count in self.keys if not key.startswith(PALETTE_KEY + ".")], extras=extras)
        popup.set_used(used)
        popup.open_below(self.add_button)

    def picker(self) -> KeyPickerPopup:
        if self.key_picker is None:
            self.key_picker = KeyPickerPopup(self)
            self.key_picker.picked.connect(self.add_feature)
        return self.key_picker
