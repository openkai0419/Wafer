from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from ...plugin.rename.base import (
    DropdownButton, ToggleButton,
    style_input, style_dropdown, style_action, style_toggle, style_spinbox,
)
from ...utils.formatting import dpix
from ...core.color.theme import ThemeManager
from .engine import RenameColumn


def _section_label(text, p):
    lbl = QtWidgets.QLabel(text)
    lbl.setStyleSheet(
        f"color: {p.text_accent}; font-size: {dpix(10)}px; "
        f"padding: {dpix(2)}px 0 0 0;"
    )
    return lbl


class ClickOutsideFilter(QtCore.QObject):
    closed = Signal()

    def __init__(self, target: QtWidgets.QWidget):
        super().__init__(target)
        self._target = target

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            gp = event.globalPosition().toPoint()
            if not self._target.geometry().contains(gp):
                if QtWidgets.QApplication.activePopupWidget():
                    return False
                self.closed.emit()
                return True
        return False


class ColumnSettingsPopup(QtWidgets.QFrame):
    changed = Signal()
    sort_requested = Signal(bool)
    move_requested = Signal(int)
    remove_requested = Signal()
    resequence_requested = Signal()

    def __init__(
        self, column: RenameColumn, *, is_ext=False, meta_keys=None, parent=None,
    ):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self._click_filter = ClickOutsideFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self._click_filter)
        self._click_filter.closed.connect(self.close)
        self._column = column
        self._anchor_window: QtWidgets.QWidget | None = None
        self._anchor_offset = QtCore.QPoint()
        p = ThemeManager.instance().palette
        self.setStyleSheet(
            f"ColumnSettingsPopup {{ background: {p.bg_elevated}; "
            f"border: 1px solid {p.border_default}; border-radius: {dpix(6)}px; }}"
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(dpix(10), dpix(8), dpix(10), dpix(8))
        lay.setSpacing(dpix(4))

        accent_bar = QtWidgets.QFrame()
        accent_bar.setFixedHeight(dpix(2))
        accent_bar.setStyleSheet(f"background: {p.accent};")
        lay.addWidget(accent_bar)

        title = QtWidgets.QLabel(column.source.DISPLAY)
        title.setStyleSheet(
            f"color: {p.text_accent}; font-size: {dpix(13)}px; font-weight: bold;"
        )
        lay.addWidget(title)

        lay.addWidget(_section_label('Source', p))
        config_w = column.source.create_config_widget(
            self, meta_keys=meta_keys,
        )
        if config_w is not None:
            config_w.changed.connect(self.changed)
            config_w.connect_extra(self)
            lay.addWidget(config_w)

        if not is_ext:
            self._sep(lay, p)
            mr = QtWidgets.QHBoxLayout()
            mr.setSpacing(dpix(4))
            for text, d in [('◀ Move left', -1), ('Move right ▶', 1)]:
                btn = QtWidgets.QPushButton(text)
                btn.setStyleSheet(style_action(p))
                btn.clicked.connect(lambda _, dd=d: self.move_requested.emit(dd))
                mr.addWidget(btn)
            lay.addLayout(mr)

            lay.addWidget(_section_label('Sort by this column', p))
            sort_row = QtWidgets.QHBoxLayout()
            sort_row.setSpacing(dpix(4))
            for label, asc in [('▲ Ascending', True), ('▼ Descending', False)]:
                btn = QtWidgets.QPushButton(label)
                btn.setStyleSheet(style_action(p))
                btn.clicked.connect(lambda _, a=asc: self.sort_requested.emit(a))
                sort_row.addWidget(btn)
            lay.addLayout(sort_row)

        en_cb = QtWidgets.QCheckBox('Include in filename')
        en_cb.setChecked(column.enabled)
        en_cb.setStyleSheet(
            f"color: {p.text_primary}; font-size: {dpix(11)}px;"
        )
        en_cb.toggled.connect(
            lambda v: (setattr(column, 'enabled', v), self.changed.emit())
        )
        lay.addWidget(en_cb)

        self._sep(lay, p)
        lay.addWidget(_section_label('Post-process', p))
        self._build_post(lay, p)

        if not is_ext:
            self._sep(lay, p)
            rm = QtWidgets.QPushButton('Remove column')
            rm.setStyleSheet(
                f"QPushButton {{ color: {p.error}; background: transparent; "
                f"border: none; font-size: {dpix(11)}px; padding: {dpix(3)}px; }}"
                f"QPushButton:hover {{ background: {p.bg_hover}; "
                f"border-radius: {dpix(3)}px; }}"
            )
            rm.clicked.connect(self.remove_requested.emit)
            lay.addWidget(rm)

    def _sep(self, lay, p):
        s = QtWidgets.QFrame()
        s.setFrameShape(QtWidgets.QFrame.HLine)
        s.setFixedHeight(dpix(1))
        s.setStyleSheet(f"background: {p.border_subtle};")
        lay.addWidget(s)

    def _build_post(self, lay, p):
        post = self._column.post
        si = style_input(p)
        ss = style_spinbox(p)
        st = style_toggle(p)
        sd = style_dropdown(p)

        has_trim = post.trim_start is not None or post.trim_end is not None
        tb = ToggleButton('Trim', has_trim)
        tb.setStyleSheet(st)
        lay.addWidget(tb)

        tw = QtWidgets.QWidget()
        tw.setVisible(has_trim)
        tl = QtWidgets.QHBoxLayout(tw)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(dpix(4))
        tss = QtWidgets.QSpinBox()
        tss.setRange(-999, 999)
        tss.setValue(post.trim_start or 0)
        tss.setPrefix('start:')
        tss.setMinimumWidth(dpix(80))
        tss.setStyleSheet(ss)
        tes = QtWidgets.QSpinBox()
        tes.setRange(-999, 999)
        tes.setValue(post.trim_end or 0)
        tes.setPrefix('end:')
        tes.setMinimumWidth(dpix(80))
        tes.setStyleSheet(ss)
        tl.addWidget(tss)
        tl.addWidget(tes)
        lay.addWidget(tw)

        def _trim_toggle(checked):
            tw.setVisible(checked)
            if not checked:
                post.trim_start = None
                post.trim_end = None
            self.changed.emit()
            self._resize_and_clamp()

        tb.toggled.connect(_trim_toggle)
        tss.valueChanged.connect(
            lambda v: (setattr(post, 'trim_start', v), self.changed.emit())
        )
        tes.valueChanged.connect(
            lambda v: (setattr(post, 'trim_end', v), self.changed.emit())
        )

        has_repl = bool(post.find)
        rb = ToggleButton('Replace', has_repl)
        rb.setStyleSheet(st)
        lay.addWidget(rb)

        rw = QtWidgets.QWidget()
        rw.setVisible(has_repl)
        rl = QtWidgets.QVBoxLayout(rw)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(dpix(2))
        find_e = QtWidgets.QLineEdit(post.find)
        find_e.setPlaceholderText('Find')
        find_e.setStyleSheet(si)
        repl_e = QtWidgets.QLineEdit(post.replace)
        repl_e.setPlaceholderText('Replace')
        repl_e.setStyleSheet(si)
        rx = QtWidgets.QCheckBox('Regex')
        rx.setChecked(post.find_regex)
        rx.setStyleSheet(f"color: {p.text_primary}; font-size: {dpix(11)}px;")
        rl.addWidget(find_e)
        rl.addWidget(repl_e)
        rl.addWidget(rx)
        lay.addWidget(rw)

        def _repl_toggle(checked):
            rw.setVisible(checked)
            if not checked:
                post.find = ''
                post.replace = ''
            self.changed.emit()
            self._resize_and_clamp()

        rb.toggled.connect(_repl_toggle)
        find_e.textChanged.connect(
            lambda t: (setattr(post, 'find', t), self.changed.emit())
        )
        repl_e.textChanged.connect(
            lambda t: (setattr(post, 'replace', t), self.changed.emit())
        )
        rx.toggled.connect(
            lambda v: (setattr(post, 'find_regex', v), self.changed.emit())
        )

        case_b = DropdownButton(
            'Case', ['none', 'upper', 'lower', 'title'], post.case_mode or 'none',
        )
        case_b.setStyleSheet(sd)
        case_b.value_changed.connect(
            lambda v: (
                setattr(post, 'case_mode', '' if v == 'none' else v),
                self.changed.emit(),
            )
        )
        lay.addWidget(case_b)

        has_ins = bool(post.prefix or post.suffix)
        ib = ToggleButton('Insert', has_ins)
        ib.setStyleSheet(st)
        lay.addWidget(ib)

        iw = QtWidgets.QWidget()
        iw.setVisible(has_ins)
        il = QtWidgets.QHBoxLayout(iw)
        il.setContentsMargins(0, 0, 0, 0)
        pe = QtWidgets.QLineEdit(post.prefix)
        pe.setPlaceholderText('prefix')
        pe.setStyleSheet(si)
        se = QtWidgets.QLineEdit(post.suffix)
        se.setPlaceholderText('suffix')
        se.setStyleSheet(si)
        il.addWidget(pe)
        il.addWidget(se)
        lay.addWidget(iw)

        def _ins_toggle(checked):
            iw.setVisible(checked)
            if not checked:
                post.prefix = ''
                post.suffix = ''
            self.changed.emit()
            self._resize_and_clamp()

        ib.toggled.connect(_ins_toggle)
        pe.textChanged.connect(
            lambda t: (setattr(post, 'prefix', t), self.changed.emit())
        )
        se.textChanged.connect(
            lambda t: (setattr(post, 'suffix', t), self.changed.emit())
        )

    def showEvent(self, event):
        super().showEvent(event)
        pw = self.parentWidget()
        if pw:
            win = pw.window()
            self._anchor_window = win
            self._anchor_offset = self.pos() - win.pos()
            win.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._anchor_window and event.type() == QtCore.QEvent.Move:
            self.move(self._anchor_window.pos() + self._anchor_offset)
        return False

    def _resize_and_clamp(self):
        screen = QtWidgets.QApplication.screenAt(self.pos())
        if not screen:
            screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            return
        self.adjustSize()
        geo = screen.availableGeometry()
        pos = self.pos()
        size = self.size()
        x = min(pos.x(), geo.right() - size.width())
        y = min(pos.y(), geo.bottom() - size.height())
        x = max(x, geo.left())
        y = max(y, geo.top())
        if x != pos.x() or y != pos.y():
            self.move(x, y)
        if self._anchor_window:
            self._anchor_offset = self.pos() - self._anchor_window.pos()

    def closeEvent(self, event):
        if self._anchor_window:
            self._anchor_window.removeEventFilter(self)
            self._anchor_window = None
        app = QtWidgets.QApplication.instance()
        if app and self._click_filter:
            app.removeEventFilter(self._click_filter)
            self._click_filter = None
        super().closeEvent(event)
