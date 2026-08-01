from __future__ import annotations

from collections.abc import Iterable

from PySide6 import QtWidgets

from .collector.handler import collector_resolver
from .parser.handler import parser_resolver
from ..core.lang.manager import t
from ..utils.formatting import dpix


def recollect_target_lines(prefixes: Iterable[str]) -> list[str]:
    lines: list[str] = []
    for prefix in prefixes:
        if collector_resolver.registry.get(prefix) is not None:
            lines.append(f"  {prefix}")
        elif parser_resolver.registry.get(prefix) is not None:
            lines.append(t("  {prefix}: parser (delete only)").format(prefix=prefix))
        else:
            lines.append(t("  {prefix}: no collector (delete only)").format(prefix=prefix))
    return lines


class FilterSaveConfirmDialog(QtWidgets.QDialog):
    def __init__(
        self,
        prefixes: Iterable[str],
        *,
        parent=None,
        title: str = "Metadata Filter Manager",
        intro: str = "Filter settings have been modified.\nThis will apply to all databases.",
        delete_label: str = "Delete existing filtered data",
        delete_default: bool = True,
        recollect_default: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(t(title))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))
        layout.addWidget(QtWidgets.QLabel(t(intro)))

        prefixes = list(prefixes)
        lines = recollect_target_lines(prefixes)
        if lines:
            layout.addWidget(QtWidgets.QLabel(t("Targets:")))
            targets = QtWidgets.QLabel("\n".join(lines))
            layout.addWidget(targets)

        has_collector = any(collector_resolver.registry.get(p) is not None for p in prefixes)

        self._delete_cb = QtWidgets.QCheckBox(t(delete_label))
        self._delete_cb.setChecked(delete_default)
        self._recollect_cb = QtWidgets.QCheckBox(t("Re-collect"))
        self._recollect_cb.setChecked(recollect_default and has_collector)
        layout.addWidget(self._delete_cb)
        layout.addWidget(self._recollect_cb)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QtWidgets.QPushButton(t("Save"))
        cancel_btn = QtWidgets.QPushButton(t("Cancel"))
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def delete_data(self) -> bool:
        return self._delete_cb.isChecked()

    def recollect(self) -> bool:
        return self._recollect_cb.isChecked()
