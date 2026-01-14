from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QFileIconProvider, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QStyle, QVBoxLayout
from PySide6.QtGui import QPixmap
from PySide6.QtCore import QFileInfo
from ..common.funcs import uipx
import os
from ..lang.manager import TranslatorMixin


def _split_path(path: str, fallback_name: str = ''):
    p = str(path or '')
    if not p:
        return '', str(fallback_name or '')
    d = os.path.dirname(p)
    n = os.path.basename(p)
    if not n:
        n = str(fallback_name or '')
    return d, n


def _limit_pixmap_size(pix: QPixmap, size: int) -> QPixmap:
    w = int(getattr(pix, 'width', lambda: 0)() or 0)
    h = int(getattr(pix, 'height', lambda: 0)() or 0)
    if w <= 0 or h <= 0:
        return pix
    if w <= size and h <= size:
        return pix
    return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _pixmap_for_source(path: str, data, size: int) -> QPixmap:
    if isinstance(data, (bytes, bytearray)) and data:
        pix = QPixmap()
        if pix.loadFromData(bytes(data)):
            return _limit_pixmap_size(pix, size)
    p = str(path or '')
    if p and os.path.exists(p):
        pix = QPixmap(p)
        if not pix.isNull():
            return _limit_pixmap_size(pix, size)
    prov = QFileIconProvider()
    ico = prov.icon(QFileInfo(p)) if p else prov.icon(QFileIconProvider.File)
    return ico.pixmap(size, size)


def _set_thumb(label: QLabel, path: str, data, size: int):
    pix = _pixmap_for_source(path, data, size)
    label.setPixmap(pix)
    if pix is not None and not pix.isNull():
        label.setFixedSize(pix.size())

class BaseDialog(QDialog):

    def __init__(self, message, title='Dialog', buttons=('OK', 'Cancel'), icon_type=QStyle.SP_MessageBoxInformation, parent=None):
        super().__init__(parent)
        self.message = message
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.result_text = None
        icon = self.style().standardIcon(icon_type)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        message_layout = QHBoxLayout()
        message_layout.addWidget(icon_label)
        message_layout.addWidget(self.message_label)
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()
        for btn_text in buttons:
            btn = QPushButton(btn_text)
            btn.clicked.connect(lambda _, text=btn_text: self._on_button(text))
            self.btn_layout.addWidget(btn)
        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(message_layout)
        self.content_layout = QVBoxLayout()
        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addLayout(self.btn_layout)
        self.setLayout(self.main_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.adjust_to_message()

    def adjust_to_message(self):
        min_width = 300
        max_width = 800
        message = self.message
        metrics = self.message_label.fontMetrics()
        lines = message.splitlines()
        line_widths = [metrics.boundingRect(line).width() for line in lines]
        max_line_width = max(line_widths, default=min_width) + 50
        final_width = max(min_width, min(max_line_width, max_width))
        self.message_label.setMinimumWidth(final_width)
        self.adjustSize()

    def _on_button(self, text):
        self.result_text = text
        self.accept()

class ConfirmDialog(BaseDialog):

    @staticmethod
    def ask(message, title='Confirm', buttons=('OK', 'Cancel'), parent=None):
        dialog = ConfirmDialog(message, title, buttons, parent=parent)
        dialog.exec()
        return dialog.result_text

class InputDialog(BaseDialog, TranslatorMixin):

    def __init__(self, message, title='Input', buttons=('OK', 'Cancel'), parent=None):
        super().__init__(message, title, buttons, parent=parent)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(self.t.tr('Please enter text...'))
        self.content_layout.addWidget(self.input_edit)

    @staticmethod
    def get_text(message, title='Input', buttons=('OK', 'Cancel'), parent=None):
        dialog = InputDialog(message, title, buttons, parent=parent)
        dialog.exec()
        if dialog.result_text and dialog.result_text == buttons[0]:
            return dialog.input_edit.text()
        else:
            return None


class FileConflictDialog(BaseDialog):

    def __init__(self, message, *, src_path: str, dst_path: str, src_name: str = '', dst_name: str = '', src_bytes=None, op: str = 'copy', show_apply_all: bool = True, title='Confirm', parent=None):
        super().__init__(message, title, buttons=('上書き', '別名で保存', 'キャンセル'), icon_type=QStyle.SP_MessageBoxWarning, parent=parent)
        self.apply_all_checkbox = None
        if show_apply_all:
            self.apply_all_checkbox = QCheckBox('同じ処理を以降すべての競合に適用')
            self.apply_all_checkbox.setChecked(False)

        thumb_size = uipx(256)
        self.src_thumb = QLabel()
        self.dst_thumb = QLabel()
        self.src_thumb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.dst_thumb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.src_thumb.setScaledContents(False)
        self.dst_thumb.setScaledContents(False)

        src_dir, src_file = _split_path(src_path, src_name)
        dst_dir, dst_file = _split_path(dst_path, dst_name)

        self.src_dir_label = QLabel(src_dir)
        self.src_file_label = QLabel(src_file)
        self.dst_dir_label = QLabel(dst_dir)
        self.dst_file_label = QLabel(dst_file)
        self.src_dir_label.setWordWrap(True)
        self.dst_dir_label.setWordWrap(True)
        self.src_file_label.setWordWrap(False)
        self.dst_file_label.setWordWrap(False)

        _set_thumb(self.src_thumb, src_path, src_bytes, thumb_size)
        _set_thumb(self.dst_thumb, dst_path, None, thumb_size)

        row = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()
        src_title = '移動元' if op == 'move' else 'コピー元'
        dst_title = '移動先' if op == 'move' else 'コピー先'
        left.addStretch(1)
        left.addWidget(QLabel(src_title), alignment=Qt.AlignHCenter)
        left.addWidget(self.src_thumb, alignment=Qt.AlignHCenter)
        left.addStretch(1)
        left.addWidget(self.src_dir_label)
        left.addWidget(self.src_file_label)
        right.addStretch(1)
        right.addWidget(QLabel(dst_title), alignment=Qt.AlignHCenter)
        right.addWidget(self.dst_thumb, alignment=Qt.AlignHCenter)
        right.addStretch(1)
        right.addWidget(self.dst_dir_label)
        right.addWidget(self.dst_file_label)
        row.addLayout(left)
        row.addSpacing(uipx(12))
        row.addLayout(right)
        self.content_layout.addLayout(row)
        self.content_layout.setSpacing(uipx(4))
        self.content_layout.addSpacing(uipx(2))
        if self.apply_all_checkbox is not None:
            self.content_layout.addWidget(self.apply_all_checkbox)

    @staticmethod
    def ask(message, *, src_path: str, dst_path: str, src_name: str = '', dst_name: str = '', src_bytes=None, op: str = 'copy', show_apply_all: bool = True, title='Confirm', parent=None):
        dialog = FileConflictDialog(message, src_path=src_path, dst_path=dst_path, src_name=src_name, dst_name=dst_name, src_bytes=src_bytes, op=op, show_apply_all=show_apply_all, title=title, parent=parent)
        dialog.exec()
        return dialog.result_text, bool(dialog.apply_all_checkbox.isChecked()) if dialog.apply_all_checkbox is not None else False

    @staticmethod
    def parse_choice(result_text: str | None) -> str | None:
        t = str(result_text or '')
        if not t:
            return None
        if t in ('キャンセル', 'Cancel'):
            return 'cancel'
        if t in ('別名で保存', 'Rename'):
            return 'rename'
        if t in ('上書き', '上書きする', 'Overwrite'):
            return 'overwrite'
        return None


class SingleFileConflictDialog(BaseDialog):

    def __init__(self, message, *, path: str, name: str = '', src_bytes=None, op: str = 'copy', show_apply_all: bool = True, title='Confirm', parent=None):
        super().__init__(message, title, buttons=('OK',), icon_type=QStyle.SP_MessageBoxWarning, parent=parent)
        self.apply_all_checkbox = None
        if show_apply_all:
            self.apply_all_checkbox = QCheckBox('同じ処理を以降すべての同一パスに適用')
            self.apply_all_checkbox.setChecked(False)

        thumb_size = uipx(256)
        self.thumb = QLabel()
        self.thumb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.thumb.setScaledContents(False)

        d, n = _split_path(path, name)
        self.dir_label = QLabel(d)
        self.file_label = QLabel(n)
        self.dir_label.setWordWrap(True)
        self.file_label.setWordWrap(False)
        _set_thumb(self.thumb, path, src_bytes, thumb_size)

        col = QVBoxLayout()
        col.addStretch(1)
        col.addWidget(QLabel('移動対象' if op == 'move' else 'コピー対象'), alignment=Qt.AlignHCenter)
        col.addWidget(self.thumb, alignment=Qt.AlignHCenter)
        col.addStretch(1)
        col.addWidget(self.dir_label)
        col.addWidget(self.file_label)
        self.content_layout.addLayout(col)
        self.content_layout.setSpacing(uipx(4))
        self.content_layout.addSpacing(uipx(2))
        if self.apply_all_checkbox is not None:
            self.content_layout.addWidget(self.apply_all_checkbox)

    @staticmethod
    def ask(message, *, path: str, name: str = '', src_bytes=None, op: str = 'copy', show_apply_all: bool = True, title='Confirm', parent=None):
        dialog = SingleFileConflictDialog(message, path=path, name=name, src_bytes=src_bytes, op=op, show_apply_all=show_apply_all, title=title, parent=parent)
        dialog.exec()
        return dialog.result_text, bool(dialog.apply_all_checkbox.isChecked()) if dialog.apply_all_checkbox is not None else False
