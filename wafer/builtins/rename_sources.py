from __future__ import annotations

import random
import string
from datetime import datetime

from PySide6 import QtCore, QtWidgets

from ..plugin.rename.base import (
    BaseRenameSourcePlugin, SegmentInfo, RenameConfigWidget,
    DropdownButton, style_input, style_dropdown, style_action, style_spinbox,
)
from ..utils.formatting import dpix
from ..core.color.theme import ThemeManager


class NameSource(BaseRenameSourcePlugin):
    NAME = 'name'
    DISPLAY = 'Name'
    PRIORITY = 100

    def evaluate(self, segment):
        return segment.stem


class FixedSource(BaseRenameSourcePlugin):
    NAME = 'fixed'
    DISPLAY = 'Fixed'
    PRIORITY = 90

    def __init__(self, text: str = '_'):
        self.text = text
        self.overrides: dict[str, str] = {}

    def evaluate(self, segment):
        return self.overrides.get(str(segment.original_path), self.text)

    def serialise(self):
        return {'type': self.NAME, 'text': self.text, 'overrides': self.overrides}

    def _apply(self, data):
        self.text = data.get('text', '_')
        self.overrides = data.get('overrides', {})

    def create_config_widget(self, parent=None, **context):
        w = RenameConfigWidget(parent)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        p = ThemeManager.instance().palette
        ed = QtWidgets.QLineEdit(self.text, w)
        ed.setPlaceholderText('text')
        ed.setStyleSheet(style_input(p))
        ed.textChanged.connect(
            lambda t: (setattr(self, 'text', t), w.changed.emit())
        )
        lay.addWidget(ed)
        return w


class SequentialSource(BaseRenameSourcePlugin):
    NAME = 'seq'
    DISPLAY = 'Sequential'
    PRIORITY = 80

    def __init__(self, start: int = 1, step: int = 1, padding: int = 3):
        self.start = start
        self.step = step
        self.padding = padding

    def evaluate(self, segment):
        num = self.start + segment.index * self.step
        return str(num).zfill(self.padding)

    def serialise(self):
        return {
            'type': self.NAME, 'start': self.start,
            'step': self.step, 'padding': self.padding,
        }

    def _apply(self, data):
        self.start = data.get('start', 1)
        self.step = data.get('step', 1)
        self.padding = data.get('padding', 3)

    def create_config_widget(self, parent=None, **context):
        w = _SequentialConfigWidget(self, parent)
        return w


class _SequentialConfigWidget(RenameConfigWidget):
    resequence_requested = QtCore.Signal()

    def __init__(self, source, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(dpix(2))
        p = ThemeManager.instance().palette
        si = style_spinbox(p)
        for lbl, attr in [('Start', 'start'), ('Step', 'step'), ('Pad', 'padding')]:
            sp = QtWidgets.QSpinBox(self)
            sp.setRange(0, 9999)
            sp.setValue(getattr(source, attr))
            sp.setPrefix(f'{lbl}: ')
            sp.setStyleSheet(si)
            sp.valueChanged.connect(
                lambda v, a=attr: (setattr(source, a, v), self.changed.emit())
            )
            lay.addWidget(sp)
        reseq = QtWidgets.QPushButton('↻ Re-sequence (current order)', self)
        reseq.setStyleSheet(style_action(p))
        reseq.clicked.connect(self.resequence_requested)
        lay.addWidget(reseq)

    def connect_extra(self, target):
        self.resequence_requested.connect(target.resequence_requested)


class MetaSource(BaseRenameSourcePlugin):
    NAME = 'meta'
    DISPLAY = 'Meta (Raw)'
    PRIORITY = 60

    def __init__(self, key: str = ''):
        self.key = key

    def evaluate(self, segment):
        return segment.metadata.get(self.key, '')

    def serialise(self):
        return {'type': self.NAME, 'key': self.key}

    def _apply(self, data):
        self.key = data.get('key', '')

    def create_config_widget(self, parent=None, **context):
        meta_keys = context.get('meta_keys') or ['width', 'height', 'dpi', 'name', 'size']
        initial = self.key or (meta_keys[0] if meta_keys else '')
        if not self.key and initial:
            self.key = initial
        w = RenameConfigWidget(parent)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        p = ThemeManager.instance().palette
        kb = DropdownButton('Key', meta_keys, initial, w)
        kb.setStyleSheet(style_dropdown(p))
        kb.value_changed.connect(
            lambda v: (setattr(self, 'key', v), w.changed.emit())
        )
        lay.addWidget(kb)
        return w


class DateSource(BaseRenameSourcePlugin):
    NAME = 'datetime'
    DISPLAY = 'Datetime'
    PRIORITY = 70

    DEFAULT_FMT = '%Y%m%d_%H%M%S'

    def __init__(self, source: str = 'modified', fmt: str = ''):
        self.source = source
        self.fmt = fmt or self.DEFAULT_FMT

    def evaluate(self, segment):
        ts = None
        if self.source == 'modified' and segment.stat:
            ts = segment.stat.st_mtime
        elif self.source == 'created' and segment.stat:
            ts = segment.stat.st_ctime
        elif self.source == 'now':
            ts = datetime.now().timestamp()
        if not ts:
            return ''
        try:
            return datetime.fromtimestamp(ts).strftime(self.fmt)
        except ValueError:
            return '?'

    def serialise(self):
        return {'type': self.NAME, 'source': self.source, 'fmt': self.fmt}

    def _apply(self, data):
        self.source = data.get('source', 'modified')
        self.fmt = data.get('fmt', '') or self.DEFAULT_FMT

    def create_config_widget(self, parent=None, **context):
        w = RenameConfigWidget(parent)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(dpix(2))
        p = ThemeManager.instance().palette
        sb = DropdownButton('Source', ['modified', 'created', 'now'], self.source, w)
        sb.setStyleSheet(style_dropdown(p))
        sb.value_changed.connect(
            lambda v: (setattr(self, 'source', v), w.changed.emit())
        )
        lay.addWidget(sb)
        fe = QtWidgets.QLineEdit(self.fmt, w)
        fe.setPlaceholderText('format e.g. %Y%m%d')
        fe.setStyleSheet(style_input(p))
        fe.textChanged.connect(
            lambda t: (setattr(self, 'fmt', t), w.changed.emit())
        )
        lay.addWidget(fe)
        return w


class RandomSource(BaseRenameSourcePlugin):
    NAME = 'random'
    DISPLAY = 'Random'
    PRIORITY = 50

    _POOLS = {
        'alphanum': string.ascii_lowercase + string.digits,
        'hex': string.hexdigits[:16],
        'digits': string.digits,
        'alpha': string.ascii_lowercase,
    }

    def __init__(self, chars: str = 'alphanum', length: int = 6):
        self.chars = chars
        self.length = length
        self._cache: dict[str, str] = {}

    def evaluate(self, segment):
        key = str(segment.original_path)
        if key not in self._cache:
            pool = self._POOLS.get(self.chars, self._POOLS['alphanum'])
            self._cache[key] = ''.join(random.choices(pool, k=self.length))
        return self._cache[key]

    def serialise(self):
        return {'type': self.NAME, 'chars': self.chars, 'length': self.length}

    def _apply(self, data):
        self.chars = data.get('chars', 'alphanum')
        self.length = data.get('length', 6)

    def create_config_widget(self, parent=None, **context):
        w = RenameConfigWidget(parent)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(dpix(2))
        p = ThemeManager.instance().palette
        cb = DropdownButton(
            'Chars', ['alphanum', 'hex', 'digits', 'alpha'], self.chars, w,
        )
        cb.setStyleSheet(style_dropdown(p))
        cb.value_changed.connect(
            lambda v: (
                setattr(self, 'chars', v),
                self._cache.clear(),
                w.changed.emit(),
            )
        )
        lay.addWidget(cb)
        ls = QtWidgets.QSpinBox(w)
        ls.setRange(1, 32)
        ls.setValue(self.length)
        ls.setPrefix('Len: ')
        ls.setStyleSheet(style_spinbox(p))
        ls.valueChanged.connect(
            lambda v: (
                setattr(self, 'length', v),
                self._cache.clear(),
                w.changed.emit(),
            )
        )
        lay.addWidget(ls)
        return w


class ExtSource(BaseRenameSourcePlugin):
    NAME = 'ext'
    DISPLAY = '.ext'
    PRIORITY = 0

    def __init__(self, mode: str = 'keep', custom: str = ''):
        self.mode = mode
        self.custom = custom

    def evaluate(self, segment):
        if self.mode == 'keep':
            return f'.{segment.ext}' if segment.ext else ''
        if self.mode == 'remove':
            return ''
        return f'.{self.custom}' if self.custom else ''

    def serialise(self):
        return {'type': self.NAME, 'mode': self.mode, 'custom': self.custom}

    def _apply(self, data):
        self.mode = data.get('mode', 'keep')
        self.custom = data.get('custom', '')

    def create_config_widget(self, parent=None, **context):
        w = RenameConfigWidget(parent)
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(dpix(2))
        p = ThemeManager.instance().palette
        mb = DropdownButton('Mode', ['keep', 'custom', 'remove'], self.mode, w)
        mb.setStyleSheet(style_dropdown(p))
        mb.value_changed.connect(
            lambda v: (setattr(self, 'mode', v), w.changed.emit())
        )
        lay.addWidget(mb)
        ce = QtWidgets.QLineEdit(self.custom, w)
        ce.setPlaceholderText('ext (no dot)')
        ce.setStyleSheet(style_input(p))
        ce.textChanged.connect(
            lambda t: (setattr(self, 'custom', t), w.changed.emit())
        )
        lay.addWidget(ce)
        return w
