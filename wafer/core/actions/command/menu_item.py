from __future__ import annotations
from typing import Callable
from PySide6 import QtCore, QtGui, QtWidgets
from ....utils.formatting import dpix
from ....utils.profiling import profiler
from ....utils.logs import AppLogger


class CommandMenuRow(QtWidgets.QWidget):
    _shared_style: str | None = None
    _px: dict[str, int] | None = None

    @classmethod
    def _ensure_px(cls) -> dict[str, int]:
        if cls._px is None:
            cls._px = {
                "mh": dpix(8), "mv": dpix(2), "mr": dpix(6),
                "ih": dpix(4), "ir": dpix(8),
                "sp": dpix(6), "chk": dpix(1),
                "opt": dpix(22), "icon": dpix(16),
                "sec": dpix(11), "pad": dpix(12),
            }
        return cls._px

    @profiler.profile
    def __init__(self, parent: QtWidgets.QWidget, text: str, hotkey: str, icon: str | None, has_options: bool, menu: QtWidgets.QMenu):
        super().__init__(parent)
        self.setObjectName("commandMenuRow")
        self._inited = False
        self._icon = icon
        self._hotkey = hotkey
        self._text = text
        self._has_options = bool(has_options)
        self._menu_ref = menu
        self._on_main_click: Callable[[], None] | None = None
        self._on_options_callback: Callable[[], None] | None = None

        px = self._ensure_px()

        l = QtWidgets.QHBoxLayout(self)
        l.setContentsMargins(px["mh"], px["mv"], px["mr"], px["mv"])
        l.setSpacing(0)

        self._main = QtWidgets.QWidget(self)
        self._main.setObjectName("rowMain")
        self._main.setCursor(QtCore.Qt.PointingHandCursor)
        self._main.setAttribute(QtCore.Qt.WA_Hover, True)
        self._ml = QtWidgets.QHBoxLayout(self._main)
        self._ml.setContentsMargins(px["ih"], px["mv"], px["ir"], px["mv"])
        self._ml.setSpacing(px["sp"])

        self._chk = QtWidgets.QLabel("", self._main)
        self._chk.setObjectName("checkMark")
        self._chk.setFixedWidth(px["chk"])
        self._chk.setAlignment(QtCore.Qt.AlignCenter)
        self._chk.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._ml.addWidget(self._chk, 0)

        self._tl = QtWidgets.QLabel(self._text, self._main)
        self._tl.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        self._ml.addWidget(self._tl, 1)

        l.addWidget(self._main, 1)

        self._icon_label: QtWidgets.QLabel | None = None
        self._hotkey_label: QtWidgets.QLabel | None = None
        self._options_btn: QtWidgets.QToolButton | None = None

        self._deferred_timer_started = False

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._inited and not self._deferred_timer_started:
            self._deferred_timer_started = True
            QtCore.QTimer.singleShot(0, self.ensure_initialized)

    def ensure_initialized(self):
        if self._inited:
            return
        if CommandMenuRow._shared_style is None:
            CommandMenuRow._shared_style = (
                "#commandMenuRow #rowMain{border:1px solid transparent;border-radius:4px;background:transparent;}"
                "#commandMenuRow #rowMain:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}" 
                "#commandMenuRow QToolButton{border:1px solid transparent;border-radius:4px;background:transparent;}"
                "#commandMenuRow QToolButton:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}" 
                "#commandMenuRow QLabel{background:transparent;}"
            )
        try:
            self.setStyleSheet(CommandMenuRow._shared_style)
        except Exception as e:
            AppLogger.warning("CommandMenuRow.setStyleSheet failed", exc=e)

        gutter_w = self._compute_gutter()
        try:
            self._chk.setFixedWidth(gutter_w)
        except Exception as e:
            AppLogger.warning("CommandMenuRow._chk.setFixedWidth failed", exc=e)

        px = self._ensure_px()

        if self._icon and self._icon_label is None:
            try:
                il = QtWidgets.QLabel(self._main)
                qicon = QtGui.QIcon(self._icon) if isinstance(self._icon, str) else self._icon
                pm = qicon.pixmap(px["icon"], px["icon"])
                il.setPixmap(pm)
                self._ml.insertWidget(1, il, 0)
                self._icon_label = il
            except Exception as e:
                AppLogger.warning("CommandMenuRow icon setup failed", exc=e)

        if self._hotkey and self._hotkey_label is None:
            try:
                raw = str(self._hotkey)
                ss_parsed = QtGui.QKeySequence(raw).toString() if raw else ""
                ss = (ss_parsed or raw).strip()
                if not ss:
                    return
                sl = QtWidgets.QLabel(ss, self._main)
                sl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self._ml.addWidget(sl, 0)
                self._hotkey_label = sl
            except Exception as e:
                AppLogger.warning("CommandMenuRow hotkey label setup failed", exc=e)

        if self._has_options and self._options_btn is None:
            try:
                btn = QtWidgets.QToolButton(self)
                btn.setText("□")
                btn.setAutoRaise(True)
                btn.setFixedWidth(px["opt"])
                btn.setCursor(QtCore.Qt.PointingHandCursor)
                btn.setFocusPolicy(QtCore.Qt.NoFocus)
                self.layout().addWidget(btn, 0)
                self._options_btn = btn
                if self._on_options_callback is not None:
                    try:
                        self._options_btn.clicked.connect(self._on_options_callback)
                    except Exception as e:
                        AppLogger.warning("CommandMenuRow options callback connect failed", exc=e)
            except Exception as e:
                AppLogger.warning("CommandMenuRow options button setup failed", exc=e)

        if self._on_main_click is not None:
            try:
                def _row_click(event):
                    if event.button() == QtCore.Qt.LeftButton:
                        try:
                            self._on_main_click()
                        except Exception as e:
                            AppLogger.warning("CommandMenuRow on_main_click failed", exc=e)
                self._main.mouseReleaseEvent = _row_click
            except Exception as e:
                AppLogger.warning("CommandMenuRow mouseReleaseEvent hook failed", exc=e)

        self._inited = True

    def _compute_gutter(self) -> int:
        try:
            style = self._menu_ref.style() if self._menu_ref is not None else self.style()
            icon_sz = style.pixelMetric(QtWidgets.QStyle.PM_SmallIconSize, None, self._menu_ref)
            return max(0, min(int(icon_sz), int(dpix(22))))
        except Exception as e:
            AppLogger.warning("CommandMenuRow gutter metric lookup failed", exc=e)
            return 22
