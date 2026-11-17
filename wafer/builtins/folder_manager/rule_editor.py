from collections.abc import Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from wafer.app.viewer.widgets.search_container import SearchContainer
from wafer.core.lang.manager import t
from wafer.plugin.query.handler import filter_registry
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets.color_picker import ColorPickerDialog
from wafer.qt.widgets.eliding import ElidingLabel

from .rules import METRICS, OPERATORS, Condition, HighlightRule

METRIC_LABELS = dict(zip(METRICS, ("Files", "All files", "Folders", "All folders")))
OPERATOR_LABELS = {">=": "≥", "<=": "≤", "==": "="}
CONDITION_MAX = 1_000_000_000


def describe_query(bars: Sequence[dict]) -> str:
    parts = []
    for bar in bars:
        if not bar.get("enabled", True):
            continue
        filter_cls = filter_registry.get(bar.get("filter", ""))
        name = t(filter_cls.DISPLAY_NAME or filter_cls.NAME) if filter_cls is not None else str(bar.get("filter", ""))
        params = bar.get("params", {})
        value = params.get("keywords") or next((v for v in params.values() if isinstance(v, str) and v), "")
        text = f'{name} "{value}"' if value else name
        op = bar.get("op")
        parts.append(f"{op} {text}" if parts and op and op != "AND" else text)
    return " ".join(parts)


def describe_rule(rule: HighlightRule) -> str:
    query = describe_query(rule.bars) or t("All files")
    conditions = f" {t('and')} ".join(f"{t(METRIC_LABELS[c.metric])} {OPERATOR_LABELS[c.op]} {c.value}" for c in rule.conditions)
    return f"{query} · {conditions}" if conditions else query


def color_icon(color: str) -> QtGui.QIcon:
    size = dpix(14)
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(color))
    painter.drawRoundedRect(QtCore.QRectF(1, 1, size - 2, size - 2), dpix(3), dpix(3))
    painter.end()
    return QtGui.QIcon(pixmap)


def tool_button(icon: str, tooltip: str, text: str = "") -> QtWidgets.QToolButton:
    button = QtWidgets.QToolButton()
    button.setIcon(themed_icon(icon))
    button.setAutoRaise(True)
    button.setToolTip(tooltip)
    if text:
        button.setText(text)
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    return button


class DragHandle(QtWidgets.QLabel):
    dragged = QtCore.Signal(QtCore.QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPixmap(themed_icon("menu").pixmap(dpix(14), dpix(14)))
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self.setToolTip(t("Drag to reorder"))

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)


class NameEdit(QtWidgets.QLineEdit):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFrame(False)
        self.setReadOnly(True)
        self.setToolTip(t("Double-click to rename"))
        self.textChanged.connect(self.fit_text)
        self.fit_text()

    def fit_text(self) -> None:
        self.setFixedWidth(max(dpix(40), self.fontMetrics().horizontalAdvance(self.text()) + dpix(12)))

    def mouseDoubleClickEvent(self, event):
        self.setReadOnly(False)
        self.selectAll()
        self.setFocus()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setReadOnly(True)


class ConditionRow(QtWidgets.QWidget):
    changed = QtCore.Signal()
    remove_requested = QtCore.Signal(object)

    def __init__(self, condition: Condition, parent=None):
        super().__init__(parent)
        self.condition = condition
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))
        self.metric_combo = QtWidgets.QComboBox()
        for metric in METRICS:
            self.metric_combo.addItem(t(METRIC_LABELS[metric]), metric)
        self.metric_combo.setCurrentIndex(METRICS.index(condition.metric))
        self.op_combo = QtWidgets.QComboBox()
        for op in OPERATORS:
            self.op_combo.addItem(OPERATOR_LABELS[op], op)
        self.op_combo.setCurrentIndex(OPERATORS.index(condition.op))
        self.value_spin = QtWidgets.QSpinBox()
        self.value_spin.setRange(0, CONDITION_MAX)
        self.value_spin.setValue(condition.value)
        self.remove_button = tool_button("cross", t("Remove condition"))
        for widget in (self.metric_combo, self.op_combo, self.value_spin, self.remove_button):
            layout.addWidget(widget)
        layout.addStretch(1)
        self.metric_combo.currentIndexChanged.connect(self.read)
        self.op_combo.currentIndexChanged.connect(self.read)
        self.value_spin.valueChanged.connect(self.read)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))

    def read(self) -> None:
        self.condition.metric = self.metric_combo.currentData()
        self.condition.op = self.op_combo.currentData()
        self.condition.value = self.value_spin.value()
        self.changed.emit()


class RuleRow(QtWidgets.QWidget):
    edited = QtCore.Signal(object)
    remove_requested = QtCore.Signal(object)
    drag_moved = QtCore.Signal(object, QtCore.QPoint)

    def __init__(self, rule: HighlightRule, parent=None):
        super().__init__(parent)
        self.rule = rule
        self.search: SearchContainer | None = None
        self.body: QtWidgets.QWidget | None = None
        self.condition_layout: QtWidgets.QVBoxLayout | None = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))
        layout.addWidget(self.build_header())

    def build_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))
        self.handle = DragHandle()
        self.handle.dragged.connect(lambda pos: self.drag_moved.emit(self, pos))
        self.enabled_check = QtWidgets.QCheckBox()
        self.enabled_check.setChecked(self.rule.enabled)
        self.enabled_check.setToolTip(t("Highlight with this rule"))
        self.enabled_check.toggled.connect(self.set_enabled)
        self.color_button = tool_button("empty", t("Choose rule color"))
        self.color_button.setIcon(color_icon(self.rule.color))
        self.color_button.clicked.connect(self.pick_color)
        self.name_edit = NameEdit(self.rule.name)
        self.name_edit.editingFinished.connect(self.commit_name)
        self.summary_label = ElidingLabel(describe_rule(self.rule))
        self.summary_label.setStyleSheet(f"color: {ThemeManager.instance().palette.text_secondary};")
        self.expand_button = tool_button("chevron_right", t("Edit query and conditions"))
        self.expand_button.clicked.connect(lambda: self.set_expanded(not self.is_expanded()))
        self.remove_button = tool_button("cross", t("Remove rule"))
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        for widget in (self.handle, self.enabled_check, self.color_button, self.name_edit):
            layout.addWidget(widget)
        layout.addWidget(self.summary_label, 1)
        layout.addWidget(self.expand_button)
        layout.addWidget(self.remove_button)
        return header

    def is_expanded(self) -> bool:
        return self.body is not None and not self.body.isHidden()

    def set_expanded(self, expanded: bool) -> None:
        if expanded and self.body is None:
            self.layout().addWidget(self.build_body())
        if self.body is not None:
            self.body.setVisible(expanded)
        self.expand_button.setIcon(themed_icon("chevron_down" if expanded else "chevron_right"))

    def build_body(self) -> QtWidgets.QWidget:
        self.body = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.body)
        layout.setContentsMargins(dpix(22), 0, 0, dpix(4))
        layout.setSpacing(dpix(2))
        self.search = SearchContainer()
        if self.rule.bars:
            self.search.apply_bars(self.rule.bars)
        self.search.filter_changed.connect(self.read_query)
        self.condition_layout = QtWidgets.QVBoxLayout()
        self.condition_layout.setSpacing(dpix(2))
        for condition in self.rule.conditions:
            self.add_condition_row(condition)
        add_button = tool_button("plus", t("Add condition"), t("Add condition"))
        add_button.clicked.connect(self.add_condition)
        layout.addWidget(QtWidgets.QLabel(t("Query")))
        layout.addWidget(self.search)
        layout.addWidget(QtWidgets.QLabel(t("Highlight when")))
        layout.addLayout(self.condition_layout)
        layout.addWidget(add_button, 0, QtCore.Qt.AlignLeft)
        return self.body

    def add_condition_row(self, condition: Condition) -> None:
        row = ConditionRow(condition)
        row.changed.connect(self.emit_edited)
        row.remove_requested.connect(self.remove_condition)
        self.condition_layout.addWidget(row)

    def add_condition(self) -> None:
        condition = Condition("files", ">=", 1)
        self.rule.conditions.append(condition)
        self.add_condition_row(condition)
        self.emit_edited()

    def remove_condition(self, row: ConditionRow) -> None:
        self.rule.conditions.remove(row.condition)
        self.condition_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.emit_edited()

    def read_query(self) -> None:
        self.rule.bars = self.search.get_bars()
        self.emit_edited()

    def set_enabled(self, enabled: bool) -> None:
        self.rule.enabled = enabled
        self.emit_edited()

    def pick_color(self) -> None:
        color = ColorPickerDialog.get_color(self.rule.color, self, t("Choose rule color"), with_alpha=False, scope="folder_manager")
        if color is None:
            return
        self.rule.color = color.name()
        self.color_button.setIcon(color_icon(self.rule.color))
        self.emit_edited()

    def commit_name(self) -> None:
        self.name_edit.setReadOnly(True)
        name = self.name_edit.text().strip()
        if not name or name == self.rule.name:
            self.name_edit.setText(self.rule.name)
            return
        self.rule.name = name
        self.emit_edited()

    def emit_edited(self) -> None:
        self.summary_label.setText(describe_rule(self.rule))
        self.edited.emit(self.rule)


class RuleList(QtWidgets.QWidget):
    rule_edited = QtCore.Signal(object)
    rule_removed = QtCore.Signal(object)
    order_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[RuleRow] = []
        self.row_layout = QtWidgets.QVBoxLayout(self)
        self.row_layout.setContentsMargins(dpix(2), 0, dpix(2), 0)
        self.row_layout.setSpacing(dpix(2))

    @property
    def rules(self) -> list[HighlightRule]:
        return [row.rule for row in self.rows]

    def set_rules(self, rules: Sequence[HighlightRule]) -> None:
        for row in self.rows:
            self.row_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows = []
        for rule in rules:
            self.append_row(rule)

    def append_row(self, rule: HighlightRule) -> RuleRow:
        row = RuleRow(rule, self)
        row.edited.connect(self.rule_edited)
        row.remove_requested.connect(self.remove_row)
        row.drag_moved.connect(self.drag_row)
        self.rows.append(row)
        self.row_layout.addWidget(row)
        return row

    def remove_row(self, row: RuleRow) -> None:
        self.rows.remove(row)
        self.row_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.rule_removed.emit(row.rule)

    def drag_row(self, row: RuleRow, global_pos: QtCore.QPoint) -> None:
        y = self.mapFromGlobal(global_pos).y()
        target = next((n for n, other in enumerate(self.rows) if y < other.geometry().bottom()), len(self.rows) - 1)
        self.move_rule(self.rows.index(row), target)

    def move_rule(self, source: int, target: int) -> None:
        if source == target:
            return
        row = self.rows.pop(source)
        self.rows.insert(target, row)
        self.row_layout.removeWidget(row)
        self.row_layout.insertWidget(target, row)
        self.order_changed.emit()
