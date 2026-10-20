from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from ....core.lang.manager import t
from ....core.store.workspace import WindowSlot
from ....qt.common.dpi import dpix
from ....qt.common.window_state import DialogLayoutStore
from ....qt.theme import ThemeManager
from .workspace_labels import slot_subtitle, slot_title, slot_tooltip

SLOT_ID_ROLE = QtCore.Qt.UserRole
SUBTITLE_ROLE = QtCore.Qt.UserRole + 1
LAYOUT_KEY = "workspace_picker"
DEFAULT_SIZE = (460, 420)
ROW_PADDING_H = 10
ROW_PADDING_V = 6
ROW_GAP = 2


@dataclass(frozen=True)
class PickResult:
    slot_id: str | None
    database_name: str


class WorkspaceRowDelegate(QtWidgets.QStyledItemDelegate):
    def title_font(self, option) -> QtGui.QFont:
        font = QtGui.QFont(option.font)
        font.setBold(True)
        return font

    def subtitle_font(self, option) -> QtGui.QFont:
        font = QtGui.QFont(option.font)
        font.setPointSizeF(max(font.pointSizeF() - 1, 1))
        return font

    def sizeHint(self, option, index) -> QtCore.QSize:
        title_h = QtGui.QFontMetrics(self.title_font(option)).height()
        height = title_h + 2 * dpix(ROW_PADDING_V)
        if index.data(SUBTITLE_ROLE):
            height += QtGui.QFontMetrics(self.subtitle_font(option)).height() + dpix(ROW_GAP)
        return QtCore.QSize(option.rect.width(), height)

    def paint(self, painter: QtGui.QPainter, option, index):
        p = ThemeManager.instance().palette
        enabled = bool(option.state & QtWidgets.QStyle.State_Enabled)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected) and enabled
        hovered = bool(option.state & QtWidgets.QStyle.State_MouseOver) and enabled
        painter.save()
        if selected:
            painter.fillRect(option.rect, QtGui.QColor(p.accent))
            title_color, subtitle_color = p.accent_text, p.accent_text
        else:
            if hovered:
                painter.fillRect(option.rect, QtGui.QColor(p.bg_hover))
            title_color = p.text_primary if enabled else p.text_muted
            subtitle_color = p.text_secondary if enabled else p.text_muted
        rect = option.rect.adjusted(dpix(ROW_PADDING_H), dpix(ROW_PADDING_V), -dpix(ROW_PADDING_H), -dpix(ROW_PADDING_V))
        title_font = self.title_font(option)
        title_h = QtGui.QFontMetrics(title_font).height()
        painter.setFont(title_font)
        painter.setPen(QtGui.QColor(title_color))
        painter.drawText(
            QtCore.QRect(rect.x(), rect.y(), rect.width(), title_h),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            QtGui.QFontMetrics(title_font).elidedText(index.data(QtCore.Qt.DisplayRole) or "", QtCore.Qt.ElideRight, rect.width()),
        )
        subtitle = index.data(SUBTITLE_ROLE)
        if subtitle:
            subtitle_font = self.subtitle_font(option)
            metrics = QtGui.QFontMetrics(subtitle_font)
            painter.setFont(subtitle_font)
            painter.setPen(QtGui.QColor(subtitle_color))
            painter.drawText(
                QtCore.QRect(rect.x(), rect.y() + title_h + dpix(ROW_GAP), rect.width(), metrics.height()),
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                metrics.elidedText(subtitle, QtCore.Qt.ElideMiddle, rect.width()),
            )
        painter.restore()


class WorkspacePickerDialog(QtWidgets.QDialog):
    def __init__(
        self,
        slots: list[WindowSlot],
        open_ids: set[str],
        *,
        allow_open: bool,
        databases: list[str],
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(t("Open Workspace"))
        self.databases = list(databases)
        self.layout_store = DialogLayoutStore(LAYOUT_KEY)
        self.picked: PickResult | None = None

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setItemDelegate(WorkspaceRowDelegate(self.list_widget))
        self.list_widget.setMouseTracking(True)
        self.list_widget.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.populate(slots, open_ids, allow_open)

        self.database_combo = QtWidgets.QComboBox()
        self.database_combo.addItems(self.databases)
        self.database_label = QtWidgets.QLabel(t("Database"))
        show_database = len(self.databases) >= 2
        self.database_label.setVisible(show_database)
        self.database_combo.setVisible(show_database)
        database_row = QtWidgets.QHBoxLayout()
        database_row.setSpacing(dpix(8))
        database_row.addWidget(self.database_label)
        database_row.addWidget(self.database_combo, 1)

        self.open_button = QtWidgets.QPushButton(t("Open"))
        self.open_button.setDefault(True)
        cancel_button = QtWidgets.QPushButton(t("Cancel"))
        for button in (self.open_button, cancel_button):
            button.setStyleSheet(f"QPushButton {{ padding: {dpix(3)}px {dpix(16)}px; }}")
        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(dpix(8))
        button_row.addStretch()
        button_row.addWidget(self.open_button)
        button_row.addWidget(cancel_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(12), dpix(12), dpix(12), dpix(10))
        layout.setSpacing(dpix(10))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(database_row)
        layout.addLayout(button_row)

        self.open_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list_widget.currentItemChanged.connect(self.update_open_button)

        self.resize(dpix(DEFAULT_SIZE[0]), dpix(DEFAULT_SIZE[1]))
        self.layout_store.restore(self)
        self.select_default_row()

    def populate(self, slots: list[WindowSlot], open_ids: set[str], allow_open: bool):
        new_item = QtWidgets.QListWidgetItem(t("New workspace"))
        new_item.setData(SLOT_ID_ROLE, None)
        self.list_widget.addItem(new_item)
        for slot in slots:
            is_open = slot.slot_id in open_ids
            subtitle = slot_subtitle(slot)
            if is_open:
                subtitle = f"{subtitle} · {t('Open')}" if subtitle else t("Open")
            item = QtWidgets.QListWidgetItem(slot_title(slot))
            item.setData(SLOT_ID_ROLE, slot.slot_id)
            item.setData(SUBTITLE_ROLE, subtitle)
            item.setToolTip(slot_tooltip(slot))
            if is_open and not allow_open:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
            self.list_widget.addItem(item)

    def select_default_row(self):
        for row in range(1, self.list_widget.count()):
            if self.list_widget.item(row).flags() & QtCore.Qt.ItemIsEnabled:
                self.list_widget.setCurrentRow(row)
                break
        else:
            self.list_widget.setCurrentRow(0)
        self.update_open_button()

    def update_open_button(self, *_):
        item = self.list_widget.currentItem()
        self.open_button.setEnabled(item is not None and bool(item.flags() & QtCore.Qt.ItemIsEnabled))

    def on_item_double_clicked(self, item: QtWidgets.QListWidgetItem):
        if item.flags() & QtCore.Qt.ItemIsEnabled:
            self.list_widget.setCurrentItem(item)
            self.accept()

    def database_name(self) -> str:
        return self.database_combo.currentText() if self.databases else ""

    def result_value(self) -> PickResult | None:
        return self.picked

    def accept(self):
        item = self.list_widget.currentItem()
        if item is None or not item.flags() & QtCore.Qt.ItemIsEnabled:
            return
        self.picked = PickResult(item.data(SLOT_ID_ROLE), self.database_name())
        super().accept()

    def done(self, code: int):
        self.layout_store.save(self)
        super().done(code)

    @staticmethod
    def ask(
        slots: list[WindowSlot],
        open_ids: set[str],
        *,
        allow_open: bool,
        databases: list[str],
        parent: QtWidgets.QWidget | None = None,
    ) -> PickResult | None:
        dialog = WorkspacePickerDialog(slots, open_ids, allow_open=allow_open, databases=databases, parent=parent)
        dialog.exec()
        return dialog.result_value()
