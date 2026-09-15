from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class ElidingLabel(QtWidgets.QLabel):
    def __init__(
        self,
        text: str = "",
        parent=None,
        *,
        elide_mode: QtCore.Qt.TextElideMode = QtCore.Qt.ElideRight,
        minimum_hint_width: int = 0,
        width_margin: int = 0,
        horizontal_policy: QtWidgets.QSizePolicy.Policy = QtWidgets.QSizePolicy.Ignored,
    ):
        super().__init__(parent)
        self._full_text = ""
        self._elide_mode = elide_mode
        self._minimum_hint_width = max(0, int(minimum_hint_width))
        self._width_margin = max(0, int(width_margin))
        self.setMinimumWidth(0)
        self.setSizePolicy(horizontal_policy, QtWidgets.QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str):
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self.update_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event):
        self.update_elided_text()
        super().resizeEvent(event)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(self._minimum_hint_width)
        return hint

    def update_elided_text(self):
        width = max(0, self.width() - self._width_margin)
        super().setText(self.fontMetrics().elidedText(self._full_text, self._elide_mode, width))


class ElidingToolButton(QtWidgets.QToolButton):
    def __init__(
        self,
        text: str = "",
        parent=None,
        *,
        elide_mode: QtCore.Qt.TextElideMode = QtCore.Qt.ElideRight,
        minimum_hint_width: int = 0,
        width_margin: int = 0,
        horizontal_policy: QtWidgets.QSizePolicy.Policy = QtWidgets.QSizePolicy.Ignored,
    ):
        super().__init__(parent)
        self._full_text = ""
        self._elide_mode = elide_mode
        self._minimum_hint_width = max(0, int(minimum_hint_width))
        self._width_margin = max(0, int(width_margin))
        self.setMinimumWidth(0)
        self.setSizePolicy(horizontal_policy, QtWidgets.QSizePolicy.Preferred)
        self.setText(text)

    def setText(self, text: str):
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self.update_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event):
        self.update_elided_text()
        super().resizeEvent(event)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(self._minimum_hint_width)
        return hint

    def update_elided_text(self):
        width = max(0, self.width() - self._width_margin)
        super().setText(self.fontMetrics().elidedText(self._full_text, self._elide_mode, width))
