from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QComboBox, QDialog, QFileIconProvider, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSizePolicy, QStyle, QVBoxLayout
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import QFileInfo
from shiboken6 import isValid
from ..common.dpi import dpix
from ...core.logs import AppLogger
from ..common.image import pil_to_qimage
from ...core.platform.thumbnails import FileThumbnailer
from ..common.dispatcher import Dispatcher
from ..common.thread import utility_pool
import os
from ...core.lang.manager import t


def _split_path(path: str, fallback_name: str = ""):
    p = str(path or "")
    if not p:
        return "", str(fallback_name or "")
    d = os.path.dirname(p)
    n = os.path.basename(p)
    if not n:
        n = str(fallback_name or "")
    return d, n


def _image_for_source(path: str, data, size: int) -> QImage | None:
    if isinstance(data, (bytes, bytearray)) and data:
        img = QImage()
        if img.loadFromData(bytes(data)):
            w, h = img.width(), img.height()
            if w > size or h > size:
                img = img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return img
    p = str(path or "")
    if p and os.path.exists(p):
        try:
            pil_img = FileThumbnailer().get_thumbnail(p, size=size)
            if pil_img is not None:
                return pil_to_qimage(pil_img)
        except Exception as e:
            AppLogger.warning(f"Thumbnail generation failed: {p}", exc=e)
    return None


def _apply_thumb(label: QLabel, img: QImage | None, path: str, size: int):
    if not isValid(label):
        return
    if img is not None and not img.isNull():
        pix = QPixmap.fromImage(img)
    else:
        prov = QFileIconProvider()
        pix = (prov.icon(QFileInfo(path)) if path else prov.icon(QFileIconProvider.File)).pixmap(size, size)
    label.setPixmap(pix)
    if not pix.isNull():
        label.setFixedSize(pix.size())


def thumbnail_label(dispatcher: Dispatcher, path: str, size: int, data=None) -> QLabel:
    label = QLabel()
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    label.setScaledContents(False)
    label.setFixedSize(size, size)
    path = str(path or "")

    def task():
        img = _image_for_source(path, data, size)
        dispatcher.invoke(lambda: _apply_thumb(label, img, path, size))

    dispatcher.post(task)
    return label


class BaseDialog(QDialog):
    def __init__(self, message, title="Dialog", buttons=("OK", "Cancel"), icon_type=QStyle.SP_MessageBoxInformation, parent=None, disabled=()):
        super().__init__(parent)
        self.message = message
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.result_text = None
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        message_layout = QHBoxLayout()
        message_layout.setSpacing(dpix(10))
        if icon_type is not None:
            icon = self.style().standardIcon(icon_type)
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(dpix(32), dpix(32)))
            message_layout.addWidget(icon_label)
        message_layout.addWidget(self.message_label)
        self.btn_layout = QHBoxLayout()
        self.btn_layout.setSpacing(dpix(8))
        self.btn_layout.addStretch()
        for btn_text in buttons:
            btn = QPushButton(btn_text)
            btn.setStyleSheet(f"QPushButton {{ padding: {dpix(3)}px {dpix(16)}px; }}")
            btn.clicked.connect(lambda _, text=btn_text: self._on_button(text))
            btn.setEnabled(btn_text not in disabled)
            self.btn_layout.addWidget(btn)
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(dpix(16), dpix(14), dpix(16), dpix(12))
        self.main_layout.setSpacing(dpix(12))
        self.main_layout.addLayout(message_layout)
        self.content_layout = QVBoxLayout()
        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addLayout(self.btn_layout)
        self.setLayout(self.main_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.adjust_to_message()

    def adjust_to_message(self):
        min_width = dpix(100)
        max_width = dpix(800)
        message = self.message
        metrics = self.message_label.fontMetrics()
        lines = message.splitlines()
        line_widths = [metrics.boundingRect(line).width() for line in lines]
        max_line_width = max(line_widths, default=min_width) + dpix(50)
        final_width = max(min_width, min(max_line_width, max_width))
        self.message_label.setMinimumWidth(final_width)
        self.adjustSize()

    def _on_button(self, text):
        self.result_text = text
        self.accept()


class ConfirmDialog(BaseDialog):
    @staticmethod
    def ask(message, title="Confirm", buttons=("OK", "Cancel"), parent=None, disabled=()):
        dialog = ConfirmDialog(message, title, buttons, parent=parent, disabled=disabled)
        dialog.exec()
        return dialog.result_text


class ThumbnailConfirmDialog(BaseDialog):
    def __init__(self, message, *, paths=None, title="Confirm", buttons=("OK", "Cancel"), parent=None):
        super().__init__(message, title, buttons, parent=parent)
        ps = [str(p) for p in (paths or []) if p]
        if not ps:
            return
        size = dpix(256)
        dispatcher = Dispatcher(utility_pool, self)
        row = QHBoxLayout()
        row.addStretch(1)
        for p in ps:
            col = QVBoxLayout()
            thumb = thumbnail_label(dispatcher, p, size)
            _, name = _split_path(p, "")
            label = QLabel(name)
            label.setAlignment(Qt.AlignHCenter)
            label.setWordWrap(False)
            col.addWidget(thumb, alignment=Qt.AlignHCenter)
            col.addWidget(label, alignment=Qt.AlignHCenter)
            row.addLayout(col)
        row.addStretch(1)
        self.content_layout.addStretch(1)
        self.content_layout.addLayout(row)
        self.content_layout.addStretch(1)

    @staticmethod
    def ask(message, *, paths=None, title="Confirm", buttons=("OK", "Cancel"), parent=None):
        dialog = ThumbnailConfirmDialog(message, paths=paths, title=title, buttons=buttons, parent=parent)
        dialog.exec()
        return dialog.result_text


class InputDialog(BaseDialog):
    def __init__(self, message, title="Input", buttons=("OK", "Cancel"), parent=None, default=""):
        super().__init__(message, title, buttons, parent=parent)
        self.input_edit = QLineEdit()
        if default:
            self.input_edit.setText(default)
            self.input_edit.selectAll()
        else:
            self.input_edit.setPlaceholderText(t("Please enter text..."))
        self.content_layout.addWidget(self.input_edit)

    @staticmethod
    def get_text(message, title="Input", buttons=("OK", "Cancel"), parent=None, default=""):
        dialog = InputDialog(message, title, buttons, parent=parent, default=default)
        dialog.exec()
        if dialog.result_text and dialog.result_text == buttons[0]:
            return dialog.input_edit.text()
        else:
            return None


class DropOperationDialog(BaseDialog):
    COPY = "copy"
    MOVE = "move"

    def __init__(self, message, *, default="copy", title="Drop Files", parent=None):
        super().__init__(message, title, buttons=("OK", "Cancel"), parent=parent)
        self._group = QButtonGroup(self)
        self.copy_radio = QRadioButton(t("Copy"))
        self.move_radio = QRadioButton(t("Move"))
        self._group.addButton(self.copy_radio)
        self._group.addButton(self.move_radio)
        selected = self.normalize_operation(default)
        self.copy_radio.setChecked(selected == self.COPY)
        self.move_radio.setChecked(selected == self.MOVE)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.copy_radio)
        row.addWidget(self.move_radio)
        row.addStretch(1)
        self.content_layout.addLayout(row)

    def selected_operation(self) -> str:
        return self.MOVE if self.move_radio.isChecked() else self.COPY

    @classmethod
    def normalize_operation(cls, value, default="copy") -> str:
        v = str(value or "").lower()
        if v in (cls.COPY, cls.MOVE):
            return v
        d = str(default or cls.COPY).lower()
        return d if d in (cls.COPY, cls.MOVE) else cls.COPY

    @staticmethod
    def ask(message, *, default="copy", title="Drop Files", parent=None) -> str | None:
        dialog = DropOperationDialog(message, default=default, title=title, parent=parent)
        dialog.exec()
        if dialog.result_text == "OK":
            return dialog.selected_operation()
        return None


class DropTargetDialog(BaseDialog):
    def __init__(self, candidates, *, default=None, message=None, title="Choose Drop Target", parent=None):
        self.ok_text = t("OK")
        self.cancel_text = t("Cancel")
        super().__init__(message or t("Choose the destination for this drop."), title, buttons=(self.ok_text, self.cancel_text), parent=parent)
        self.candidates = self.normalize_candidates(candidates)
        self.selected_path = None
        self.combo = QComboBox()
        self.combo.setMinimumWidth(dpix(420))
        for path in self.candidates:
            self.combo.addItem(path, path)
        if default:
            try:
                idx = self.candidates.index(str(default))
                self.combo.setCurrentIndex(idx)
            except ValueError:
                pass
        self.content_layout.addWidget(self.combo)

    @staticmethod
    def normalize_candidates(candidates) -> list[str]:
        out = []
        seen = set()
        for candidate in candidates or []:
            text = str(candidate or "")
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _on_button(self, text):
        if text == self.ok_text and self.combo.count() > 0:
            self.selected_path = self.combo.currentData() or self.combo.currentText()
        super()._on_button(text)

    @staticmethod
    def ask(candidates, *, default=None, message=None, title="Choose Drop Target", parent=None) -> str | None:
        dialog = DropTargetDialog(candidates, default=default, message=message, title=title, parent=parent)
        if not dialog.candidates:
            return None
        dialog.exec()
        return dialog.selected_path


class ConflictDialog(BaseDialog):
    CHOICE_LABELS = {
        "overwrite": "Overwrite",
        "merge": "Merge",
        "rename": "Rename",
        "skip": "Skip",
        "cancel": "Cancel",
        "ok": "OK",
    }

    def __init__(self, message, *, choices, apply_all_text: str, show_apply_all: bool = True, title="Confirm", parent=None):
        self.choice_by_label = {t(self.CHOICE_LABELS[c]): c for c in choices}
        super().__init__(message, title, buttons=tuple(self.choice_by_label), icon_type=QStyle.SP_MessageBoxWarning, parent=parent)
        self.thumb_dispatcher = Dispatcher(utility_pool, self)
        self.apply_all_checkbox = QCheckBox(apply_all_text) if show_apply_all else None

    def add_columns(self, *columns: tuple[str, QLabel, str, str]):
        row = QHBoxLayout()
        for i, (heading, icon, path, name) in enumerate(columns):
            if i:
                row.addSpacing(dpix(12))
            folder, file_name = _split_path(path, name)
            dir_label = QLabel(folder)
            dir_label.setWordWrap(True)
            col = QVBoxLayout()
            col.addStretch(1)
            col.addWidget(QLabel(heading), alignment=Qt.AlignHCenter)
            col.addWidget(icon, alignment=Qt.AlignHCenter)
            col.addStretch(1)
            col.addWidget(dir_label)
            col.addWidget(QLabel(file_name))
            row.addLayout(col)
        self.content_layout.addLayout(row)
        self.content_layout.setSpacing(dpix(4))
        self.content_layout.addSpacing(dpix(2))
        if self.apply_all_checkbox is not None:
            self.content_layout.addWidget(self.apply_all_checkbox)

    def choice(self) -> str | None:
        return self.choice_by_label.get(self.result_text)

    def apply_all(self) -> bool:
        return self.apply_all_checkbox is not None and self.apply_all_checkbox.isChecked()

    def run(self) -> tuple[str | None, bool]:
        self.exec()
        return self.choice(), self.apply_all()


def _side_titles(op: str) -> tuple[str, str]:
    if op == "move":
        return t("Move Source"), t("Move Target")
    return t("Copy Source"), t("Copy Target")


class FileConflictDialog(ConflictDialog):
    def __init__(
        self,
        message,
        *,
        src_path: str,
        dst_path: str,
        src_name: str = "",
        dst_name: str = "",
        src_bytes=None,
        op: str = "copy",
        show_apply_all: bool = True,
        choices=("overwrite", "rename", "skip", "cancel"),
        title="Confirm",
        parent=None,
    ):
        super().__init__(message, choices=choices, apply_all_text=t("Apply to all remaining conflicts"), show_apply_all=show_apply_all, title=title, parent=parent)
        size = dpix(256)
        src_title, dst_title = _side_titles(op)
        self.add_columns(
            (src_title, thumbnail_label(self.thumb_dispatcher, src_path, size, src_bytes), src_path, src_name),
            (dst_title, thumbnail_label(self.thumb_dispatcher, dst_path, size), dst_path, dst_name),
        )

    @staticmethod
    def ask(message, **kwargs) -> tuple[str | None, bool]:
        return FileConflictDialog(message, **kwargs).run()


class FolderConflictDialog(ConflictDialog):
    def __init__(self, message, *, src_path: str, dst_path: str, src_name: str = "", dst_name: str = "", op: str = "copy", show_apply_all: bool = True, title="Confirm", parent=None):
        super().__init__(
            message,
            choices=("merge", "rename", "skip", "cancel"),
            apply_all_text=t("Apply to all remaining folder conflicts"),
            show_apply_all=show_apply_all,
            title=title,
            parent=parent,
        )
        folder_pix = QFileIconProvider().icon(QFileIconProvider.Folder).pixmap(dpix(64), dpix(64))
        icons = []
        for _ in range(2):
            icon = QLabel()
            icon.setPixmap(folder_pix)
            icons.append(icon)
        src_title, dst_title = _side_titles(op)
        self.add_columns((src_title, icons[0], src_path, src_name), (dst_title, icons[1], dst_path, dst_name))

    @staticmethod
    def ask(message, **kwargs) -> tuple[str | None, bool]:
        return FolderConflictDialog(message, **kwargs).run()


class SingleFileConflictDialog(ConflictDialog):
    def __init__(self, message, *, path: str, name: str = "", src_bytes=None, op: str = "copy", show_apply_all: bool = True, title="Confirm", parent=None):
        super().__init__(message, choices=("ok",), apply_all_text=t("Apply to all remaining conflicts"), show_apply_all=show_apply_all, title=title, parent=parent)
        heading = t("Move Target") if op == "move" else t("Copy Target")
        self.add_columns((heading, thumbnail_label(self.thumb_dispatcher, path, dpix(256), src_bytes), path, name))

    @staticmethod
    def ask(message, **kwargs) -> tuple[str | None, bool]:
        return SingleFileConflictDialog(message, **kwargs).run()
